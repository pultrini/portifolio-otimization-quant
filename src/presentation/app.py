"""Entrypoint Streamlit e composition root da aplicação.

Único lugar que conhece implementações concretas: monta o cliente Supabase e o repositório
e os injeta nos use cases. As funções de tela só chamam use cases e repositórios via
abstrações. Só a chave pública (anon/publishable) é usada aqui; a `service_role` nunca.
"""

import logging

import streamlit as st
from supabase import Client, create_client

from application.dtos.allocation import SaveAllocationTargetsRequest
from application.use_cases.save_allocation_targets import SaveAllocationTargets
from domain.exceptions import DomainError
from domain.value_objects.asset_class import AssetClass
from infrastructure.config import Settings
from infrastructure.persistence.supabase_portfolio_repository import SupabasePortfolioRepository

logger = logging.getLogger(__name__)

# Chaves do `st.session_state`. O Streamlit reexecuta o script inteiro a cada interação,
# então tudo que precisa sobreviver entre execuções (cliente, usuário) fica no estado.
SESSION_USER = "user_id"
SESSION_CLIENT = "supabase_client"

# Tolerância da soma dos alvos, em pontos percentuais (CLAUDE.md 5.1).
ALLOCATION_TOLERANCE_PP = 0.01


def _build_client(settings: Settings) -> Client:
    """Cria o cliente Supabase com a chave pública (nunca a service_role)."""
    return create_client(settings.supabase_url, settings.supabase_anon_key)


def _start_session(client: Client, user_id: str, access_token: str) -> None:
    """Guarda o usuário na sessão e garante que o PostgREST use o JWT dele.

    O supabase-py já troca o cabeçalho do PostgREST quando a sessão muda, inclusive no
    refresh do token. A chamada explícita é só uma garantia: sem o JWT do usuário,
    o RLS trataria as requisições como anônimas e nada seria lido ou gravado.
    """
    client.postgrest.auth(access_token)
    st.session_state[SESSION_USER] = user_id


def _sign_in(client: Client, email: str, password: str) -> None:
    result = client.auth.sign_in_with_password({"email": email, "password": password})
    if result.session is None or result.user is None:
        raise ValueError("Sessão não retornada pelo Supabase.")
    _start_session(client, result.user.id, result.session.access_token)


def _auth_page(client: Client) -> None:
    """Tela de entrada com abas de login e cadastro."""
    st.title("Otimização de Portfólio")
    login_tab, signup_tab = st.tabs(["Entrar", "Criar conta"])

    with login_tab, st.form("login"):
        email = st.text_input("E-mail")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar")
    if submitted:
        try:
            _sign_in(client, email, password)
        except Exception:
            # Mensagem genérica para não revelar se o e-mail existe; detalhe vai para o log.
            logger.exception("Falha ao autenticar")
            st.error("Não foi possível entrar. Verifique e-mail e senha.")
        else:
            st.rerun()

    with signup_tab, st.form("signup"):
        new_email = st.text_input("E-mail", key="signup_email")
        new_password = st.text_input("Senha", type="password", key="signup_password")
        created = st.form_submit_button("Criar conta")
    if created:
        try:
            result = client.auth.sign_up({"email": new_email, "password": new_password})
        except Exception:
            logger.exception("Falha ao criar conta")
            st.error("Não foi possível criar a conta.")
            return
        if result.session is not None and result.user is not None:
            # Projeto sem confirmação de e-mail: o cadastro já devolve uma sessão válida.
            _start_session(client, result.user.id, result.session.access_token)
            st.rerun()
        # Com confirmação de e-mail ativa, a sessão só existe depois do clique no link.
        st.success("Conta criada. Confirme o e-mail e depois entre.")


def _new_portfolio_form(repo: SupabasePortfolioRepository, user_id: str) -> None:
    with st.form("new_portfolio", clear_on_submit=True):
        name = st.text_input("Nome da carteira", max_chars=80)
        submitted = st.form_submit_button("Criar carteira")
    if submitted and name.strip():
        repo.create_portfolio(user_id=user_id, name=name.strip())
        st.rerun()


def _allocation_page(client: Client, user_id: str) -> None:
    st.header("Perfil de Alocação Alvo")
    repo = SupabasePortfolioRepository(client)
    portfolios = repo.list_portfolios()

    # Sem carteira não há onde guardar o perfil, então a primeira ação é criar uma.
    if not portfolios:
        st.info("Crie uma carteira para começar.")
        _new_portfolio_form(repo, user_id)
        return

    with st.expander("Nova carteira"):
        _new_portfolio_form(repo, user_id)

    # O selectbox mostra o nome; o id é o que vai para o banco.
    options = {portfolio.name: portfolio.id for portfolio in portfolios}
    selected_name = st.selectbox("Carteira", list(options))
    portfolio_id = options[selected_name]
    current = repo.get_allocation_targets(portfolio_id)

    with st.form("allocation_targets"):
        inputs: dict[AssetClass, float] = {}
        # Um campo por classe, pré-preenchido com o alvo salvo (ou 0 se ainda não existe).
        for asset_class in AssetClass:
            inputs[asset_class] = st.number_input(
                f"{asset_class.label_pt} (%)",
                min_value=0.0,
                max_value=100.0,
                step=0.5,
                format="%.2f",
                value=float(current.get(asset_class.value, 0.0)),
            )
        submitted = st.form_submit_button("Salvar perfil")

    # Aviso antecipado na tela; quem barra de fato é o AllocationProfile no domínio.
    total = sum(inputs.values())
    if abs(total - 100.0) > ALLOCATION_TOLERANCE_PP:
        st.warning(f"A soma dos alvos é {total:.2f}%. O perfil deve fechar em 100,00%.")

    if submitted:
        use_case = SaveAllocationTargets(repo)
        try:
            response = use_case.execute(
                SaveAllocationTargetsRequest(
                    user_id=user_id, portfolio_id=portfolio_id, targets=inputs
                )
            )
        except DomainError as error:
            # Regra de negócio violada: a mensagem do domínio já está em português.
            st.error(str(error))
            return
        st.success("Perfil salvo.")
        logger.info("Perfil salvo para carteira %s: %s", portfolio_id, response.targets)


def main() -> None:
    """Monta dependências e decide qual tela mostrar conforme a sessão."""
    st.set_page_config(page_title="Otimização de Portfólio", layout="wide")
    settings = Settings()
    logging.basicConfig(level=settings.log_level.upper())

    if not settings.supabase_url or not settings.supabase_anon_key:
        st.error("Configure SUPABASE_URL e SUPABASE_ANON_KEY no arquivo .env.")
        st.stop()

    # Um cliente por sessão de navegador: a sessão de auth do usuário fica dentro dele,
    # então não pode ser compartilhado entre usuários (por isso não usa st.cache_resource).
    if SESSION_CLIENT not in st.session_state:
        st.session_state[SESSION_CLIENT] = _build_client(settings)
    client: Client = st.session_state[SESSION_CLIENT]

    if SESSION_USER not in st.session_state:
        _auth_page(client)
        return

    with st.sidebar:
        st.write("Sessão ativa")
        if st.button("Sair"):
            client.auth.sign_out()
            # Descarta o cliente também, para a próxima sessão começar sem token antigo.
            for key in (SESSION_USER, SESSION_CLIENT):
                st.session_state.pop(key, None)
            st.rerun()

    _allocation_page(client, st.session_state[SESSION_USER])


main()
