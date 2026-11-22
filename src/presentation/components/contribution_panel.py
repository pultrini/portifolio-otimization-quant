"""Painel de decisão de aporte por ativo: notas, checklist e botão "Aportar"."""

from decimal import Decimal

import streamlit as st

from application.dtos.contribution import (
    AssetContributionResult,
    AssetDecisionRow,
    ChecklistView,
    ExecuteContributionRequest,
    SaveChecklistRequest,
)
from domain.exceptions import DomainError
from domain.services.contribution_decision import Decision
from domain.value_objects.asset_class import AssetClass
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

# Opções do editor: "automática" deixa valer a regra dos dados abertos.
_AUTO, _NONE, _YES, _NO = "Automática", "Sem resposta", "Sim", "Não"


# Etiquetas de classe em tons claros com texto escuro (legíveis no tema escuro e claro);
# a cor segue a classe, nunca a posição na lista.
_PILL_COLORS: dict[AssetClass, str] = {
    AssetClass.BR_EQUITY: "#8ff5cf",
    AssetClass.INTL_EQUITY: "#7cc8f8",
    AssetClass.BR_FIXED_INCOME: "#f5d48f",
    AssetClass.INTL_FIXED_INCOME: "#f3b38a",
    AssetClass.CRYPTO: "#f6a9c9",
}
_PILL_STYLE = (
    "display:inline-block;padding:6px 14px;border-radius:999px;font-weight:600;"
    "font-size:0.85rem;color:#0b0b0b;white-space:nowrap;background:{color}"
)
_ROW_WIDTHS = [2.1, 1.0, 1.2, 1.4, 1.2, 2.2, 1.5]


def _score(value: float | None) -> str:
    return PLACEHOLDER if value is None else format_number(value, 0)


def _auto_label(view_answer: bool | None) -> str:
    return {True: "Sim", False: "Não", None: "sem dado"}[view_answer]


def _pill(asset_class: AssetClass) -> str:
    style = _PILL_STYLE.format(color=_PILL_COLORS[asset_class])
    return f'<span style="{style}">{asset_class.label_pt}</span>'


@st.dialog("Questionário de importância", width="large")
def _questionnaire(ctx: PageContext, view: ChecklistView) -> None:
    """Janela com as perguntas do ativo; respostas automáticas mostram a evidência."""
    st.markdown(f"### {view.ticker}")
    st.caption(
        f"{view.yes} de {view.total} respostas Sim ({view.answered} respondidas). "
        "Sem resposta conta como não ponto. Respostas manuais valem mais que as automáticas."
    )
    with st.form(f"checklist_{view.ticker}"):
        answers: dict[str, bool | None] = {}
        for q in view.questions:
            default = {None: 0, True: 1, False: 2}[q.manual_answer]
            # Sem regra automática, a primeira opção significa "sem resposta".
            first = _AUTO if q.evidence else _NONE
            choice = st.radio(
                f"**{q.title}**: {q.text}",
                [first, _YES, _NO],
                index=default,
                horizontal=True,
                key=f"chk_{view.ticker}_{q.key}",
            )
            if q.evidence:
                st.caption(f"Dado aberto → {_auto_label(q.auto_answer)}: {q.evidence}")
            answers[q.key] = {_AUTO: None, _NONE: None, _YES: True, _NO: False}[choice]
        if st.form_submit_button("Salvar respostas", type="primary"):
            try:
                ctx.container.save_checklist.execute(
                    SaveChecklistRequest(
                        user_id=ctx.user_id, ticker=view.ticker, kind=view.kind, answers=answers
                    )
                )
            except DomainError as error:
                st.error(str(error))
            else:
                cache.invalidate()
                st.rerun()


def _class_summary(result: AssetContributionResult) -> None:
    """Por classe: percentual atual x alvo e se recebe aporte (e por quê)."""
    for row in result.plan.rows:
        if row.current_value == 0 and row.target_pct == 0:
            continue
        head = (
            f"{_pill(row.asset_class)} &nbsp; atual **{format_pct(row.current_pct)}** → "
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
    # Classes que recebem aporte primeiro: as compras ficam no topo da lista.
    for cls in sorted(result.classes, key=lambda c: c.budget, reverse=True):
        class_total = sum((r.current_value for r in cls.rows), Decimal(0))
        for row in cls.rows:
            st.markdown("<hr style='margin:2px 0;opacity:0.25'>", unsafe_allow_html=True)
            cols = st.columns(_ROW_WIDTHS, vertical_alignment="center")
            cols[0].markdown(_pill(row.asset_class), unsafe_allow_html=True)
            cols[1].markdown(
                f"**{row.ticker}**" + ("  \n:gray[desejado]" if row.in_watchlist else "")
            )
            cols[2].markdown(f":green[**{format_brl(row.current_value)}**]")
            current_share = float(row.current_value / class_total * 100) if class_total else 0.0
            cols[3].markdown(
                f"{format_pct(current_share)} → **{format_pct(row.ideal_weight_pct)}**"
            )
            detail = (
                f"quant {_score(row.quant_score)} · Sim {row.checklist.yes}/{row.checklist.total}"
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
                _questionnaire(ctx, row.checklist)
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
