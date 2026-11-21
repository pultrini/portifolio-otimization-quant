"""Painel de decisão de aporte por ativo: notas, checklist e botão "Aportar"."""

import streamlit as st

from application.dtos.contribution import (
    AssetContributionResult,
    ChecklistView,
    ClassDecisionDTO,
    ExecuteContributionRequest,
    SaveChecklistRequest,
)
from domain.exceptions import DomainError
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
from presentation.components.session import PageContext

FLASH_KEY = "contribution_flash"

_DECISION_LABELS = {
    Decision.BUY: "✅ Aportar",
    Decision.WAIT: "⏸ Aguardar",
    Decision.DISCARDED: "⛔ Descartado",
    Decision.NO_PRICE: "❔ Sem cotação",
    Decision.TOO_EXPENSIVE: "💲 Lote acima do valor",
}

# Opções do editor: "automática" deixa valer a regra dos dados abertos.
_AUTO, _YES, _NO = "Automática", "Sim", "Não"


def _score(value: float | None) -> str:
    return PLACEHOLDER if value is None else format_number(value, 0)


def _auto_label(view_answer: bool | None) -> str:
    return {True: "Sim", False: "Não", None: "sem dado"}[view_answer]


def _class_table(cls: ClassDecisionDTO) -> None:
    st.dataframe(
        [
            {
                "Ativo": row.ticker + (" (desejado)" if row.in_watchlist else ""),
                "Nota quant": _score(row.quant_score),
                "Checklist": (
                    f"{row.checklist.yes}/{row.checklist.total}" if row.checklist else PLACEHOLDER
                ),
                "Nota final": _score(row.final_score),
                "Peso ideal": format_pct(row.ideal_weight_pct),
                "Atual": format_brl(row.current_value),
                "Comprar": format_quantity(row.quantity) if row.quantity else "",
                "Valor": format_brl(row.amount) if row.amount else "",
                "Decisão": _DECISION_LABELS[row.decision],
                "Motivo": row.reason,
            }
            for row in cls.rows
        ],
        hide_index=True,
        width="stretch",
    )


def _checklist_editor(ctx: PageContext, view: ChecklistView) -> None:
    title = f"Checklist {view.ticker}: {view.yes}/{view.total} Sim ({view.answered} respondidas)"
    with st.expander(title), st.form(f"checklist_{view.ticker}"):
        answers: dict[str, bool | None] = {}
        for q in view.questions:
            default = {None: 0, True: 1, False: 2}[q.manual_answer]
            choice = st.radio(
                f"**{q.title}**: {q.text}",
                [_AUTO, _YES, _NO],
                index=default,
                horizontal=True,
                key=f"chk_{view.ticker}_{q.key}",
                help=(
                    f"Automática: {_auto_label(q.auto_answer)}. {q.evidence}"
                    if q.evidence
                    else "Sem regra automática: responda Sim ou Não."
                ),
            )
            if q.evidence:
                st.caption(f"Dado aberto → {_auto_label(q.auto_answer)}: {q.evidence}")
            answers[q.key] = {_AUTO: None, _YES: True, _NO: False}[choice]
        if st.form_submit_button("Salvar respostas"):
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
    st.subheader("Decisão por ativo")
    st.caption(
        "Nota final = peso quant x nota quant + (1 − peso quant) x checklist. "
        "Dentro de cada classe, o peso ideal de cada ativo é proporcional à nota final; "
        "o aporte vai para quem está mais abaixo do peso ideal, em lotes negociáveis."
    )

    if result.orders:
        st.markdown("**Melhor aporte**")
        for order in result.orders:
            st.markdown(
                f"- Comprar **{format_quantity(order.quantity)} × {order.ticker}** "
                f"a {format_brl(order.price)} = **{format_brl(order.amount)}**"
            )
        st.caption(f"Sobra sem alocar (lote mínimo): {format_brl(result.leftover)}")
        _execute_section(ctx, result)
    else:
        st.info("Informe um valor de aporte para ver as compras sugeridas.")

    for cls in result.classes:
        st.markdown(f"#### {cls.asset_class.label_pt} · aporte {format_brl(cls.budget)}")
        if not cls.uses_checklist:
            st.caption("Classe sem checklist: o aporte mantém a proporção atual entre os ativos.")
        _class_table(cls)
        for row in cls.rows:
            if row.checklist is not None:
                _checklist_editor(ctx, row.checklist)
