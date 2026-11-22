"""Aba "Simulando melhor carteira quant" da página de Otimização."""

from decimal import Decimal

import streamlit as st

from application.dtos.optimization import (
    Objective,
    QuantSimulationRequest,
    QuantSimulationResult,
    SimulatedAssetRow,
)
from domain.exceptions import DomainError
from presentation.charts.optimization import simulation_growth, simulation_weights
from presentation.components import cache
from presentation.components.formatting import (
    PLACEHOLDER,
    format_brl,
    format_number,
    format_pct,
    format_quantity,
    format_ratio_as_pct,
)
from presentation.components.glossary import help_text
from presentation.components.questionnaire import pill
from presentation.components.session import PageContext
from presentation.pages import guide

_OBJECTIVES: dict[Objective, str] = {
    "max_sharpe": "Máximo Sharpe",
    "min_variance": "Mínima volatilidade",
}
_ROW_WIDTHS = [1.4, 1.1, 1.6, 1.5, 1.3, 1.8]
_LIST_HEIGHT = 420


def _controls(ctx: PageContext) -> QuantSimulationRequest | None:
    positions = ctx.container.list_positions.execute(ctx.portfolio_id)
    universe = [r.ticker for r in positions.rows] + positions.watchlist
    if len(universe) < 1:
        st.info("Importe posições ou adicione ativos à lista de desejos para simular.")
        return None
    with st.form("quant_simulation"):
        tickers = st.multiselect(
            "Ativos possíveis",
            universe,
            default=universe,
            help="Carteira atual e lista de desejos. Para incluir outro ativo, adicione-o à "
            "lista de desejos na página Carteira (os dados dele são baixados na hora).",
        )
        col1, col2, col3 = st.columns(3)
        objective = col1.radio(
            "Objetivo",
            list(_OBJECTIVES),
            format_func=_OBJECTIVES.__getitem__,
            help=help_text("sharpe"),
        )
        max_weight = col2.slider(
            "Peso máximo por ativo",
            min_value=5,
            max_value=100,
            value=25,
            step=5,
            format="%d%%",
            help="Teto de concentração. Se não couber (poucos ativos), é relaxado para o "
            "mínimo viável.",
        )
        lookback = col3.select_slider("Janela (anos)", options=[1, 2, 3, 5], value=3)
        col4, col5, col6 = st.columns(3)
        respect = col4.toggle(
            "Respeitar alocação alvo",
            value=True,
            help="Peso de cada classe = seu perfil alvo; a otimização escolhe os ativos "
            "dentro de cada classe.",
        )
        include_fixed = col5.toggle(
            "Incluir renda fixa",
            value=False,
            help="Só vale sem o perfil alvo: CDI e Tesouro, quase sem volatilidade, "
            "tenderiam a dominar a carteira.",
        )
        contribution = col6.number_input(
            "Aporte novo (R$)", min_value=0.0, step=100.0, format="%.2f"
        )
        submitted = st.form_submit_button("Simular", type="primary")
    if not tickers:
        st.info("Escolha ao menos um ativo.")
        return None
    # Sem clicar, a primeira execução já simula com os valores padrão do formulário.
    del submitted
    return QuantSimulationRequest(
        portfolio_id=ctx.portfolio_id,
        tickers=sorted(tickers),
        lookback_years=lookback,
        objective=objective,
        respect_targets=respect,
        include_fixed_income=include_fixed,
        max_weight=max_weight / 100,
        contribution=Decimal(str(contribution)),
    )


def _kpis(result: QuantSimulationResult) -> None:
    sim, cur = result.simulated, result.current

    def sharpe(value: float | None) -> str:
        return PLACEHOLDER if value is None else format_number(value)

    def delta(a: float | None, b: float | None, as_pct: bool) -> str | None:
        if a is None or b is None:
            return None
        diff = a - b
        sign = "+" if diff >= 0 else "−"
        # Só o número leva vírgula decimal; "p.p." fica com ponto.
        if as_pct:
            return f"{sign}{format_number(abs(diff) * 100)} p.p."
        return f"{sign}{format_number(abs(diff))}"

    cols = st.columns(3)
    cols[0].metric(
        "Sharpe simulado",
        sharpe(sim.sharpe),
        delta(sim.sharpe, cur.sharpe if cur else None, False),
        help="Diferença em relação à carteira atual com os mesmos ativos. " + help_text("sharpe"),
    )
    cols[1].metric(
        "Retorno esperado",
        format_ratio_as_pct(sim.expected_return),
        delta(sim.expected_return, cur.expected_return if cur else None, True),
        help="Média histórica anualizada na janela (não é previsão).",
    )
    cols[2].metric(
        "Volatilidade",
        format_ratio_as_pct(sim.volatility),
        delta(sim.volatility, cur.volatility if cur else None, True),
        delta_color="inverse",
        help=help_text("volatility"),
    )


def _classes(result: QuantSimulationResult) -> None:
    for row in result.classes:
        target = f" · alvo {format_pct(row.target_pct)}" if row.target_pct is not None else ""
        st.markdown(
            f"{pill(row.asset_class)} &nbsp; atual **{format_pct(row.current_weight * 100)}** → "
            f"simulada **{format_pct(row.weight * 100)}**{target}",
            unsafe_allow_html=True,
        )


def _action(row: SimulatedAssetRow) -> str:
    if row.price <= 0:
        return ":gray[sem cotação]"
    if not row.fractional and row.delta_quantity == 0:
        return ":gray[manter]"
    if row.fractional:
        diff = row.target_value - row.current_value
        if abs(diff) < Decimal("1"):
            return ":gray[manter]"
        sign = "+" if diff > 0 else "−"
        return f"**{sign}{format_brl(abs(diff))}**"
    verb = "comprar" if row.delta_quantity > 0 else "vender"
    return (
        f"**{verb} {format_quantity(abs(row.delta_quantity))}**  \n"
        f":gray[{format_brl(abs(row.delta_value))}]"
    )


def _asset_list(result: QuantSimulationResult) -> None:
    st.caption(
        "Risco = fração do risco total da carteira simulada que vem do ativo "
        "(contribuição ao risco); vol = volatilidade anual do ativo sozinho."
    )
    header = st.columns(_ROW_WIDTHS)
    for column, title in zip(
        header,
        ["Classe", "Ativo", "Peso atual → simulado", "Valor simulado", "Risco", "Diferença"],
        strict=True,
    ):
        column.caption(title)
    box = st.container(height=_LIST_HEIGHT if len(result.rows) > 7 else "content", border=False)
    with box:
        for row in result.rows:
            st.markdown("<hr style='margin:2px 0;opacity:0.25'>", unsafe_allow_html=True)
            cols = st.columns(_ROW_WIDTHS, vertical_alignment="center")
            cols[0].markdown(pill(row.asset_class, short=True), unsafe_allow_html=True)
            cols[1].markdown(
                f"**{row.ticker}**" + ("  \n:gray[desejado]" if row.in_watchlist else "")
            )
            cols[2].markdown(
                f"{format_pct(row.current_weight * 100)} → **{format_pct(row.weight * 100)}**"
            )
            cols[3].markdown(f":green[**{format_brl(row.target_value)}**]")
            risk = (
                PLACEHOLDER
                if row.risk_contribution is None
                # Contribuição de ±0,0x% (CDI) é ruído numérico: mostra 0.
                else format_pct(max(row.risk_contribution, 0.0) * 100)
                if abs(row.risk_contribution) < 5e-4
                else format_pct(row.risk_contribution * 100)
            )
            cols[4].markdown(f"{risk}  \n:gray[vol {format_ratio_as_pct(row.volatility)}]")
            cols[5].markdown(_action(row))


def render(ctx: PageContext) -> None:
    st.markdown("### Simulando melhor carteira quant", help=help_text("quant_simulation"))
    guide.links(ctx.guide_page, ["quant_simulation", "frontier", "sharpe", "volatility"])
    st.caption(
        "Combina os ativos da carteira e da lista de desejos na composição que teve a melhor "
        "relação risco-retorno no período. Simulação com dados históricos: não é previsão "
        "nem recomendação de investimento."
    )
    request = _controls(ctx)
    if request is None:
        return
    try:
        with st.spinner("Simulando..."):
            result = cache.quant_simulation(ctx.container, ctx.user_id, request)
    except DomainError as error:
        st.error(str(error))
        return

    st.caption(
        f"{result.start:%d/%m/%Y} a {result.end:%d/%m/%Y} · {result.observations} períodos · "
        f"CDI {format_ratio_as_pct(result.risk_free_rate)} a.a. · "
        f"{_OBJECTIVES[result.objective]} · teto {format_pct(result.max_weight * 100)} por ativo"
    )
    for warning in result.warnings:
        st.warning(warning)
    if result.excluded:
        with st.expander(f"Fora da simulação ({len(result.excluded)})"):
            for ticker, reason in sorted(result.excluded.items()):
                st.markdown(f"- **{ticker}**: {reason}")

    _kpis(result)
    st.markdown("**Por classe**")
    _classes(result)
    st.plotly_chart(simulation_weights(result), width="stretch")

    st.markdown("**Composição simulada**")
    st.caption(
        f"Valores para {format_brl(result.base_value)} (ativos simulados + aporte), em "
        "lotes negociáveis. Diferença = quanto mudaria em relação à posição atual."
    )
    _asset_list(result)

    st.markdown("**Como teria se saído**")
    st.caption(
        "R$ 1,00 aplicado no início da janela, com os pesos mantidos constantes. É a mesma "
        "amostra usada para escolher os pesos, então a simulada tende a parecer melhor do "
        "que seria fora dela."
    )
    st.plotly_chart(simulation_growth(result), width="stretch")
