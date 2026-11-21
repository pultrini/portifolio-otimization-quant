"""Página: métricas de performance e risco por carteira, classe e estratégia."""

import streamlit as st

from application.dtos.metrics import RiskReturnMetrics, ScopeReport
from domain.exceptions import DomainError
from presentation.charts.performance import equity_and_underwater
from presentation.components import cache
from presentation.components.formatting import (
    PLACEHOLDER,
    format_brl,
    format_number,
    format_ratio_as_pct,
)
from presentation.components.glossary import help_text
from presentation.components.session import PageContext
from presentation.pages import guide

_KIND_TITLES = {
    "portfolio": "Carteira",
    "asset_class": "Por classe de ativo",
    "strategy": "Por estratégia",
}


def _delta_pp(value: float | None, reference: float | None) -> str | None:
    """Delta vs. benchmark em pontos percentuais, no formato do st.metric."""
    if value is None or reference is None:
        return None
    return f"{(value - reference) * 100:+.2f} p.p.".replace(".", ",", 1)


def _ratio(value: float | None) -> str:
    return PLACEHOLDER if value is None else format_number(value, 2)


def _kpis(scope: ScopeReport) -> None:
    """Linha de KPIs com delta contra o benchmark da classe."""
    metrics, bench = scope.metrics, scope.benchmark_metrics
    cols = st.columns(5)
    cols[0].metric(
        "Retorno total",
        format_ratio_as_pct(metrics.cumulative_return),
        _delta_pp(metrics.cumulative_return, bench.cumulative_return),
        help=help_text("cumulative_return"),
    )
    cols[1].metric(
        "CAGR",
        format_ratio_as_pct(metrics.cagr),
        _delta_pp(metrics.cagr, bench.cagr),
        help=help_text("cagr"),
    )
    cols[2].metric(
        "Volatilidade",
        format_ratio_as_pct(metrics.volatility),
        _delta_pp(metrics.volatility, bench.volatility),
        delta_color="inverse",  # mais volatilidade que o benchmark é pior
        help=help_text("volatility"),
    )
    cols[3].metric(
        "Max drawdown",
        format_ratio_as_pct(metrics.max_drawdown),
        _delta_pp(metrics.max_drawdown, bench.max_drawdown),
        help=help_text("max_drawdown"),
    )
    cols[4].metric("Sharpe", _ratio(metrics.sharpe), None, help=help_text("sharpe"))


# (rótulo, campo do DTO, formato, verbete do guia).
# "pct" = fração exibida como %, "ratio" = número.
_TABLE_ROWS: list[tuple[str, str, str, str]] = [
    ("Retorno acumulado", "cumulative_return", "pct", "cumulative_return"),
    ("CAGR", "cagr", "pct", "cagr"),
    ("Volatilidade anualizada", "volatility", "pct", "volatility"),
    ("Maximum drawdown", "max_drawdown", "pct", "max_drawdown"),
    ("VaR 95% (histórico, diário)", "var_95", "pct", "var"),
    ("VaR 99% (histórico, diário)", "var_99", "pct", "var"),
    ("CVaR 95% (histórico, diário)", "cvar_95", "pct", "cvar"),
    ("CVaR 99% (histórico, diário)", "cvar_99", "pct", "cvar"),
    ("Sharpe", "sharpe", "ratio", "sharpe"),
    ("Sortino", "sortino", "ratio", "sortino"),
    ("Calmar", "calmar", "ratio", "calmar"),
    ("Beta vs. benchmark", "beta", "ratio", "beta"),
]
_PARAMETRIC_ROWS: list[tuple[str, str, str, str]] = [
    ("VaR 95% (paramétrico)", "parametric_var_95", "pct", "parametric"),
    ("VaR 99% (paramétrico)", "parametric_var_99", "pct", "parametric"),
    ("CVaR 95% (paramétrico)", "parametric_cvar_95", "pct", "parametric"),
    ("CVaR 99% (paramétrico)", "parametric_cvar_99", "pct", "parametric"),
]
_GUIDE_KEYS = [
    "cumulative_return",
    "cagr",
    "volatility",
    "max_drawdown",
    "var",
    "cvar",
    "parametric",
    "sharpe",
    "sortino",
    "calmar",
    "beta",
    "trade_stats",
]


def _format_field(metrics: RiskReturnMetrics, field: str, kind: str) -> str:
    value: float | None = getattr(metrics, field)
    return format_ratio_as_pct(value) if kind == "pct" else _ratio(value)


def _metrics_table(metrics: RiskReturnMetrics, bench: RiskReturnMetrics, parametric: bool) -> None:
    """Tabela completa: versão acessível de tudo que os KPIs e gráficos mostram."""
    rows = _TABLE_ROWS + (_PARAMETRIC_ROWS if parametric else [])
    st.dataframe(
        [
            {
                "Métrica": label,
                "Escopo": _format_field(metrics, field, kind),
                # Beta do benchmark contra ele mesmo é 1 por definição.
                "Benchmark": "1,00" if field == "beta" else _format_field(bench, field, kind),
                "O que mede": help_text(doc),
            }
            for label, field, kind, doc in rows
        ],
        hide_index=True,
        width="stretch",
        column_config={"O que mede": st.column_config.TextColumn(width="large")},
    )


def _trade_stats(scope: ScopeReport) -> None:
    stats = scope.trade_stats
    if stats is None:
        return
    st.markdown("**Eficiência operacional** (operações fechadas, líquidas de custos)")
    cols = st.columns(5)
    trade_help = help_text("trade_stats")
    cols[0].metric(
        "Operações fechadas",
        str(stats.closed_trades),
        help="Compras casadas com vendas (FIFO) dentro desta estratégia.",
    )
    cols[1].metric(
        "Win rate",
        format_ratio_as_pct(stats.win_rate),
        help="Fração das operações fechadas com lucro. " + trade_help,
    )
    cols[2].metric(
        "Payoff",
        _ratio(stats.payoff_ratio),
        help="Ganho médio dividido pela perda média: quanto um acerto paga por um erro.",
    )
    cols[3].metric(
        "Profit factor",
        _ratio(stats.profit_factor),
        help="Soma dos ganhos / soma das perdas. Abaixo de 1, a estratégia perde dinheiro.",
    )
    cols[4].metric(
        "Expectativa / operação",
        format_brl(stats.expectancy),
        help="Resultado médio esperado por operação, líquido de custos.",
    )
    notes = []
    if stats.day_trades:
        notes.append(f"{stats.day_trades} day trade(s) entre as operações fechadas.")
    if stats.mean_return_per_trade is not None:
        notes.append(
            f"Retorno médio por operação: {format_ratio_as_pct(stats.mean_return_per_trade)}."
        )
    if stats.unmatched_quantity:
        notes.append(
            "Parte das vendas não tem compra registrada nesta estratégia "
            "(ex.: posição importada) e ficou fora das estatísticas."
        )
    for note in notes:
        st.caption(note)


def _scope_section(scope: ScopeReport, parametric: bool) -> None:
    st.subheader(scope.label)
    if scope.error:
        st.warning(scope.error)
        if scope.trade_stats is not None:
            _trade_stats(scope)
        return
    period = (
        f"{scope.start:%d/%m/%Y} a {scope.end:%d/%m/%Y} · {scope.observations} períodos · "
        f"benchmark {scope.benchmark} · taxa livre de risco {scope.risk_free} · "
        f"anualização {scope.periods_per_year} · deltas em p.p. vs. benchmark"
    )
    st.caption(period)
    _kpis(scope)
    st.plotly_chart(equity_and_underwater(scope), width="stretch")
    _trade_stats(scope)
    with st.expander("Todas as métricas"):
        _metrics_table(scope.metrics, scope.benchmark_metrics, parametric)


def render(ctx: PageContext) -> None:
    st.header("Métricas por Estratégia")
    st.caption(f"Carteira: {ctx.portfolio_name}")
    guide.links(ctx.guide_page, _GUIDE_KEYS)
    col1, col2 = st.columns([1, 1])
    lookback = col1.select_slider("Janela (anos)", options=[1, 2, 3, 5], value=3)
    parametric = col2.toggle("Incluir VaR/CVaR paramétricos", value=False)

    try:
        with st.spinner("Calculando métricas..."):
            report = cache.metrics_report(
                ctx.container, ctx.user_id, ctx.portfolio_id, lookback, parametric
            )
    except DomainError as error:
        st.error(str(error))
        return

    if not report.scopes:
        st.info("Sem posições nem operações. Importe sua carteira na página Carteira.")
        return

    st.caption(
        "VaR e CVaR são perdas de um período (dia), reportadas como números positivos. "
        "A carteira atual é avaliada com as quantidades de hoje ao longo da janela."
    )
    for kind, title in _KIND_TITLES.items():
        scopes = [s for s in report.scopes if s.kind == kind]
        if not scopes:
            continue
        st.markdown(f"### {title}")
        if len(scopes) == 1:
            _scope_section(scopes[0], parametric)
            continue
        for tab, scope in zip(st.tabs([s.label for s in scopes]), scopes, strict=True):
            with tab:
                _scope_section(scope, parametric)
