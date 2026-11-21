"""Página: otimização (fronteira eficiente, Risk Parity) e correlação."""

from collections.abc import Callable

import streamlit as st

from application.dtos.optimization import OptimizationResult, PortfolioPointDTO
from domain.exceptions import DomainError
from presentation.charts.optimization import correlation_heatmap, frontier_scatter
from presentation.components import cache
from presentation.components.formatting import (
    PLACEHOLDER,
    format_number,
    format_ratio_as_pct,
)
from presentation.components.glossary import help_text
from presentation.components.session import PageContext
from presentation.pages import guide


def _weights_table(result: OptimizationResult) -> None:
    """Pesos de cada carteira lado a lado (versão em tabela do gráfico)."""
    portfolios: list[PortfolioPointDTO] = [result.current, result.max_sharpe, result.min_variance]
    if result.risk_parity is not None:
        portfolios.append(result.risk_parity)
    rows = []
    for ticker in result.tickers:
        row = {"Ativo": ticker}
        for point in portfolios:
            row[point.label] = format_ratio_as_pct(point.weights.get(ticker, 0.0))
        rows.append(row)
    summary: list[tuple[str, Callable[[PortfolioPointDTO], str]]] = [
        ("Retorno esperado", lambda p: format_ratio_as_pct(p.expected_return)),
        ("Volatilidade", lambda p: format_ratio_as_pct(p.volatility)),
        ("Sharpe", lambda p: PLACEHOLDER if p.sharpe is None else format_number(p.sharpe)),
    ]
    for name, fmt in summary:
        line = {"Ativo": name}
        for point in portfolios:
            line[point.label] = fmt(point)
        rows.append(line)
    st.dataframe(rows, hide_index=True, width="stretch")


def render(ctx: PageContext) -> None:
    st.header("Otimização")
    st.caption(f"Carteira: {ctx.portfolio_name}")
    guide.links(ctx.guide_page, ["frontier", "sharpe", "risk_parity", "correlation", "volatility"])
    col1, col2 = st.columns(2)
    lookback = col1.select_slider("Janela de estimação (anos)", options=[1, 2, 3, 5], value=3)
    include_fixed = col2.toggle(
        "Incluir renda fixa",
        value=False,
        help="CDI e Tesouro têm volatilidade quase nula e tendem a dominar a otimização.",
    )
    try:
        with st.spinner("Otimizando..."):
            result = cache.optimization_result(
                ctx.container, ctx.user_id, ctx.portfolio_id, lookback, include_fixed
            )
    except DomainError as error:
        st.error(str(error))
        return

    st.caption(
        f"{result.start:%d/%m/%Y} a {result.end:%d/%m/%Y} · {result.observations} períodos · "
        f"taxa livre de risco (CDI) {format_ratio_as_pct(result.risk_free_rate)} a.a. · "
        "sem venda a descoberto"
    )
    if result.excluded:
        st.caption("Fora da otimização: " + ", ".join(result.excluded))
    for warning in result.warnings:
        st.warning(warning)

    cols = st.columns(3)
    current, best = result.current, result.max_sharpe
    cols[0].metric(
        "Sharpe atual",
        PLACEHOLDER if current.sharpe is None else format_number(current.sharpe),
        help="Sharpe da carteira atual (só os ativos otimizados). " + help_text("sharpe"),
    )
    cols[1].metric(
        "Sharpe máximo",
        PLACEHOLDER if best.sharpe is None else format_number(best.sharpe),
        None
        if best.sharpe is None or current.sharpe is None
        else format_number(best.sharpe - current.sharpe),
        help="Maior Sharpe possível com os mesmos ativos no período (carteira tangente). "
        + help_text("frontier"),
    )
    cols[2].metric(
        "Volatilidade mínima",
        format_ratio_as_pct(result.min_variance.volatility),
        None,
        help="Menor volatilidade alcançável combinando os ativos (ponta esquerda da fronteira).",
    )

    st.plotly_chart(frontier_scatter(result), width="stretch")
    st.markdown(
        "**Pesos sugeridos**",
        help="Fração do valor em cada ativo para cada carteira ótima. " + help_text("risk_parity"),
    )
    _weights_table(result)
    st.caption(
        "Retornos esperados são médias históricas da janela: mostram o que teria sido "
        "ótimo no período, não uma previsão."
    )

    st.markdown("### Correlação entre os ativos", help=help_text("correlation"))
    st.plotly_chart(correlation_heatmap(result), width="stretch")
