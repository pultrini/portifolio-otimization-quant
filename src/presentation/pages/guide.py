"""Página: guia das métricas, com equações, explicações, exemplos e uso na decisão."""

from collections.abc import Sequence

import streamlit as st
from streamlit.navigation.page import StreamlitPage

from presentation.components.glossary import DOCS, DOCS_BY_KEY

GUIDE_URL_PATH = "guia-de-metricas"
QUERY_KEY = "m"


def links(page: StreamlitPage | None, keys: Sequence[str]) -> None:
    """Botão "Equações e exemplos" com um link por métrica (abre o guia já expandido).

    Navega dentro da mesma sessão, sem nova aba (que pediria login de novo).
    """
    if page is None:
        return
    with st.popover("📘 Equações e exemplos"):
        for key in keys:
            st.page_link(page, label=DOCS_BY_KEY[key].title, query_params={QUERY_KEY: key})


def render() -> None:
    st.header("Guia de Métricas")
    st.caption(
        "Cada métrica com o que mede, a fórmula, um exemplo numérico calculado pelo próprio "
        "app e como usá-la para decidir. Métricas por período usam 252 períodos por ano "
        "(365 para cripto)."
    )
    selected = st.query_params.get(QUERY_KEY)
    groups = list(dict.fromkeys(doc.group for doc in DOCS))
    for group in groups:
        st.markdown(f"### {group}")
        for doc in (d for d in DOCS if d.group == group):
            with st.expander(doc.title, expanded=doc.key == selected):
                st.markdown(f"**O que é.** {doc.short}")
                st.latex(doc.formula)
                st.markdown(doc.body)
                st.markdown("**Exemplo numérico**")
                st.markdown(doc.example())
                st.markdown(f"**Na decisão.** {doc.decision}")
