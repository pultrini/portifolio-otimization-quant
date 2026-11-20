"""Estado compartilhado entre páginas e seletor de carteira na barra lateral."""

from dataclasses import dataclass

import streamlit as st

from application.dtos.portfolio import CreatePortfolioRequest
from presentation.container import Container

# Chaves do `st.session_state`. O Streamlit reexecuta o script a cada interação, então
# o que precisa sobreviver entre execuções e entre páginas fica aqui.
SESSION_USER = "user_id"
SESSION_CLIENT = "supabase_client"
SESSION_PORTFOLIO = "portfolio_id"


@dataclass(frozen=True, slots=True)
class PageContext:
    """O que toda página precisa: use cases, usuário e carteira selecionada."""

    container: Container
    user_id: str
    portfolio_id: str
    portfolio_name: str


def select_portfolio(container: Container, user_id: str) -> tuple[str, str] | None:
    """Seletor de carteira na barra lateral, com criação de nova carteira.

    A escolha fica em `st.session_state`, então trocar de página mantém a carteira.

    Returns:
        (id, nome) da carteira escolhida, ou None se o usuário ainda não tem carteira.
    """
    portfolios = container.list_portfolios.execute()
    with st.sidebar:
        if portfolios:
            ids = [p.id for p in portfolios]
            names = {p.id: p.name for p in portfolios}
            current = st.session_state.get(SESSION_PORTFOLIO)
            index = ids.index(current) if current in ids else 0
            chosen = st.selectbox("Carteira", ids, index=index, format_func=lambda pid: names[pid])
            st.session_state[SESSION_PORTFOLIO] = chosen

        with st.expander("Nova carteira", expanded=not portfolios):
            with st.form("new_portfolio", clear_on_submit=True):
                name = st.text_input("Nome", max_chars=80)
                submitted = st.form_submit_button("Criar carteira")
            if submitted and name.strip():
                created = container.create_portfolio.execute(
                    CreatePortfolioRequest(user_id=user_id, name=name)
                )
                st.session_state[SESSION_PORTFOLIO] = created.id
                st.rerun()

    if not portfolios:
        return None
    chosen_id = str(st.session_state[SESSION_PORTFOLIO])
    return chosen_id, names[chosen_id]
