"""Entrypoint Streamlit: autenticação, composition root e navegação entre páginas.

Só a chave pública (anon/publishable) do Supabase é usada aqui; a `service_role` nunca.
A montagem dos use cases fica em `presentation.container`.
"""

import logging
from collections.abc import Callable

import streamlit as st
from supabase import Client, create_client

from infrastructure.config import Settings
from presentation.components.session import (
    SESSION_CLIENT,
    SESSION_PORTFOLIO,
    SESSION_USER,
    PageContext,
    select_portfolio,
)
from presentation.container import Container, build_container
from presentation.pages import allocation, metrics, optimization, portfolio, trades

logger = logging.getLogger(__name__)

SESSION_CONTAINER = "container"


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


def _sign_out(client: Client) -> None:
    client.auth.sign_out()
    # Descarta cliente e use cases, para a próxima sessão começar sem token antigo.
    for key in (SESSION_USER, SESSION_CLIENT, SESSION_CONTAINER, SESSION_PORTFOLIO):
        st.session_state.pop(key, None)
    st.rerun()


def _page(render: Callable[[PageContext], None], ctx: PageContext) -> Callable[[], None]:
    """Adapta `render(ctx)` para a assinatura sem argumentos que o st.Page exige."""

    def page() -> None:
        render(ctx)

    # O Streamlit usa o nome da função como identificador da página.
    page.__name__ = f"page_{render.__module__.rsplit('.', 1)[-1]}"
    return page


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
        st.session_state[SESSION_CLIENT] = create_client(
            settings.supabase_url, settings.supabase_anon_key
        )
    client: Client = st.session_state[SESSION_CLIENT]

    if SESSION_USER not in st.session_state:
        _auth_page(client)
        return

    if SESSION_CONTAINER not in st.session_state:
        st.session_state[SESSION_CONTAINER] = build_container(client, settings)
    container: Container = st.session_state[SESSION_CONTAINER]
    user_id = str(st.session_state[SESSION_USER])

    selected = select_portfolio(container, user_id)
    with st.sidebar:
        if st.button("Sair"):
            _sign_out(client)

    if selected is None:
        st.title("Otimização de Portfólio")
        st.info("Crie sua primeira carteira na barra lateral.")
        return

    ctx = PageContext(container, user_id, portfolio_id=selected[0], portfolio_name=selected[1])
    navigation = st.navigation(
        [
            st.Page(_page(portfolio.render, ctx), title="Carteira", icon="💼", default=True),
            st.Page(_page(trades.render, ctx), title="Operações", icon="🔁"),
            st.Page(_page(allocation.render, ctx), title="Alocação Alvo", icon="🎯"),
            st.Page(_page(metrics.render, ctx), title="Métricas por Estratégia", icon="📈"),
            st.Page(_page(optimization.render, ctx), title="Otimização", icon="🧭"),
        ]
    )
    navigation.run()


main()
