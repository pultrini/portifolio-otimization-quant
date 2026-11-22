"""Painel de decisão de aporte por ativo: notas, checklist e botão "Aportar"."""

from decimal import Decimal

import streamlit as st

from application.dtos.contribution import (
    AssetContributionResult,
    AssetDecisionRow,
    ExecuteContributionRequest,
)
from domain.services.contribution_decision import Decision
from domain.value_objects.strategy_type import StrategyType
from presentation.components import cache
from presentation.components.formatting import (
    PLACEHOLDER,
    format_brl,
    format_number,
    format_pct,
    format_quantity,
)
from presentation.components.glossary import help_text
from presentation.components.questionnaire import open_dialog, pill
from presentation.components.session import PageContext
from presentation.pages import guide

FLASH_KEY = "contribution_flash"

_DECISION_LABELS = {
    Decision.BUY: "✅ Aportar",
    Decision.WAIT: "⏸ Aguardar",
    Decision.DISCARDED: "⛔ Descartado",
    Decision.NO_PRICE: "❔ Sem cotação",
    Decision.TOO_EXPENSIVE: "💲 Lote acima do valor",
}

_ROW_WIDTHS = [2.1, 1.0, 1.2, 1.4, 1.2, 2.2, 1.5]
# Altura da lista com rolagem: a página não cresce com o número de ativos.
_LIST_HEIGHT = 460


def _score(value: float | None) -> str:
    return PLACEHOLDER if value is None else format_number(value, 0)


def _class_summary(result: AssetContributionResult) -> None:
    """Por classe: percentual atual x alvo e se recebe aporte (e por quê)."""
    for row in result.plan.rows:
        if row.current_value == 0 and row.target_pct == 0:
            continue
        head = (
            f"{pill(row.asset_class)} &nbsp; atual **{format_pct(row.current_pct)}** → "
            f"alvo **{format_pct(row.target_pct)}**"
        )
        if row.contribution > 0:
            tail = f"recebe **{format_brl(row.contribution)}**"
        elif row.current_pct > row.target_pct:
            tail = "não recebe: já está acima do alvo"
        else:
            tail = "não recebe: outras classes estão mais abaixo do alvo"
        st.markdown(f"{head} · {tail}", unsafe_allow_html=True)


def _buy_text(row: AssetDecisionRow) -> str:
    if row.decision is Decision.BUY:
        if row.ticker == "CDI":
            return f"**+{format_brl(row.amount)}**"
        return f"**+{format_quantity(row.quantity)}** · {format_brl(row.amount)}"
    return _DECISION_LABELS[row.decision]


def _asset_list(ctx: PageContext, result: AssetContributionResult) -> None:
    """Lista de ativos (uma linha por ativo) com o questionário no fim de cada linha."""
    header = st.columns(_ROW_WIDTHS)
    for column, title in zip(
        header,
        ["Classe", "Ativo", "Valor atual", "Peso na classe", "Nota", "Comprar", ""],
        strict=True,
    ):
        column.caption(title)
    rows_count = sum(len(c.rows) for c in result.classes)
    # Lista longa vai para uma caixa com rolagem própria; curta fica na página.
    box = st.container(height=_LIST_HEIGHT if rows_count > 6 else "content", border=False)
    with box:
        _asset_rows(ctx, result)


def _asset_rows(ctx: PageContext, result: AssetContributionResult) -> None:
    # Classes que recebem aporte primeiro: as compras ficam no topo da lista.
    for cls in sorted(result.classes, key=lambda c: c.budget, reverse=True):
        class_total = sum((r.current_value for r in cls.rows), Decimal(0))
        for row in cls.rows:
            st.markdown("<hr style='margin:2px 0;opacity:0.25'>", unsafe_allow_html=True)
            cols = st.columns(_ROW_WIDTHS, vertical_alignment="center")
            cols[0].markdown(pill(row.asset_class, short=True), unsafe_allow_html=True)
            cols[1].markdown(
                f"**{row.ticker}**" + ("  \n:gray[desejado]" if row.in_watchlist else "")
            )
            cols[2].markdown(f":green[**{format_brl(row.current_value)}**]")
            current_share = float(row.current_value / class_total * 100) if class_total else 0.0
            cols[3].markdown(
                f"{format_pct(current_share)} → **{format_pct(row.ideal_weight_pct)}**"
            )
            detail = (
                f"quant {_score(row.quant_score)} · checklist {_score(row.checklist.score * 100)}"
                if row.checklist
                else f"quant {_score(row.quant_score)}"
            )
            cols[4].markdown(f"**{_score(row.final_score)}**  \n:gray[{detail}]")
            cols[5].markdown(_buy_text(row) + (f"  \n:gray[{row.reason}]" if row.reason else ""))
            if row.checklist is not None and cols[6].button(
                "📝 Questionário",
                key=f"questionnaire_{row.ticker}",
                width="stretch",
                help="Responder o questionário de importância deste ativo.",
            ):
                open_dialog(ctx, row.checklist)
    st.markdown("<hr style='margin:2px 0;opacity:0.25'>", unsafe_allow_html=True)


def _execute_section(ctx: PageContext, result: AssetContributionResult) -> None:
    if not result.orders:
        return
    col1, col2 = st.columns([2, 1])
    strategy = col1.selectbox(
        "Estratégia das compras",
        list(StrategyType),
        format_func=lambda s: s.label_pt,
        key="contribution_strategy",
    )
    col2.write("")
    if col2.button("Aportar", type="primary", width="stretch") and strategy is not None:
        response = ctx.container.execute_contribution.execute(
            ExecuteContributionRequest(
                user_id=ctx.user_id,
                portfolio_id=ctx.portfolio_id,
                orders=result.orders,
                strategy=strategy,
            )
        )
        cache.invalidate()
        # Mensagem sobrevive ao rerun (o Streamlit redesenha a página do zero).
        st.session_state[FLASH_KEY] = (response.registered, response.errors)
        st.rerun()


def _flash() -> None:
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash is None:
        return
    registered, errors = flash
    if registered:
        st.success("Aporte registrado: " + ", ".join(registered) + ". Posições atualizadas.")
    for error in errors:
        st.error(error)


def render_decision(ctx: PageContext, result: AssetContributionResult) -> None:
    """Melhor aporte por ativo, notas por classe, checklist e botão Aportar."""
    _flash()
    st.subheader("Decisão por ativo", help=help_text("quant_score"))
    guide.links(ctx.guide_page, ["quant_score", "ideal_weight", "sharpe", "sortino", "calmar"])
    st.caption(
        "Nota final = peso quant x nota quant + (1 − peso quant) x checklist. "
        "Dentro de cada classe, o peso ideal de cada ativo é proporcional à nota final; "
        "o aporte vai para quem está mais abaixo do peso ideal, em lotes negociáveis."
    )

    if result.orders:
        st.markdown("**Melhor aporte**")
        for order in result.orders:
            if order.ticker == "CDI":
                # CDI é aplicação por valor: unidades do índice não dizem nada ao usuário.
                st.markdown(f"- Aplicar **{format_brl(order.amount)}** em CDI")
                continue
            st.markdown(
                f"- Comprar **{format_quantity(order.quantity)} × {order.ticker}** "
                f"a {format_brl(order.price)} = **{format_brl(order.amount)}**"
            )
        st.caption(f"Sobra sem alocar (lote mínimo): {format_brl(result.leftover)}")
        _execute_section(ctx, result)
    else:
        st.info("Informe um valor de aporte para ver as compras sugeridas.")

    st.markdown("**Por classe**")
    _class_summary(result)

    st.markdown("**Ativos**")
    st.caption(
        "Peso na classe: atual → ideal (proporcional à nota). Use o questionário para "
        "responder as perguntas de cada ativo; a nota muda na hora."
    )
    _asset_list(ctx, result)
