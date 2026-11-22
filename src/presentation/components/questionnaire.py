"""Questionário de importância (checklist) e pesos de Sim/Não, usados em duas páginas.

Na Carteira o questionário fica dentro de "Editar ou remover posição"; na Alocação
Alvo abre numa janela a partir da lista de ativos. As duas usam o mesmo formulário.
"""

import streamlit as st

from application.dtos.contribution import (
    ChecklistView,
    ChecklistWeightsDTO,
    SaveChecklistRequest,
    SaveChecklistWeightsRequest,
)
from domain.exceptions import DomainError
from domain.value_objects.asset_class import AssetClass
from presentation.components import cache
from presentation.components.formatting import format_number, format_pct
from presentation.components.session import PageContext

# Opções do formulário: "automática" deixa valer a regra dos dados abertos.
_AUTO, _NONE, _YES, _NO = "Automática", "Sem resposta", "Sim", "Não"

# Atalhos de postura: (peso do Sim, peso do Não). O usuário também pode ajustar à mão.
PRESETS: dict[str, tuple[float, float]] = {
    "Padrão: Não vale 0": (1.0, 0.0),
    "Equilibrado: um Não anula um Sim": (1.0, 1.0),
    "Conservador: um Não anula dois Sim": (1.0, 2.0),
    "Muito conservador: um Não anula três Sim": (1.0, 3.0),
}

# Etiquetas de classe em tons claros com texto escuro (legíveis no tema escuro e claro);
# a cor segue a classe, nunca a posição na lista.
PILL_COLORS: dict[AssetClass, str] = {
    AssetClass.BR_EQUITY: "#8ff5cf",
    AssetClass.INTL_EQUITY: "#7cc8f8",
    AssetClass.BR_FIXED_INCOME: "#f5d48f",
    AssetClass.INTL_FIXED_INCOME: "#f3b38a",
    AssetClass.CRYPTO: "#f6a9c9",
    AssetClass.BR_REAL_ESTATE: "#c9b6f7",
    AssetClass.INTL_REAL_ESTATE: "#b9e38f",
}
_PILL_STYLE = (
    "display:inline-block;padding:6px 14px;border-radius:999px;font-weight:600;"
    "font-size:0.85rem;color:#0b0b0b;white-space:nowrap;background:{color}"
)


# Rótulos curtos para as listas: a etiqueta não pode invadir a coluna do ativo.
SHORT_LABELS: dict[AssetClass, str] = {
    AssetClass.BR_EQUITY: "RV Brasil",
    AssetClass.INTL_EQUITY: "RV Exterior",
    AssetClass.BR_FIXED_INCOME: "RF Brasil",
    AssetClass.INTL_FIXED_INCOME: "RF Exterior",
    AssetClass.CRYPTO: "Cripto",
    AssetClass.BR_REAL_ESTATE: "FII",
    AssetClass.INTL_REAL_ESTATE: "REITs",
}


def pill(asset_class: AssetClass, short: bool = False) -> str:
    """Etiqueta colorida da classe (HTML; renderizar com unsafe_allow_html)."""
    style = _PILL_STYLE.format(color=PILL_COLORS[asset_class])
    label = SHORT_LABELS[asset_class] if short else asset_class.label_pt
    return f'<span style="{style}" title="{asset_class.label_pt}">{label}</span>'


def _auto_label(answer: bool | None) -> str:
    return {True: "Sim", False: "Não", None: "sem dado"}[answer]


def score_caption(view: ChecklistView) -> str:
    no_part = f", {view.no} Não" if view.no else ""
    return (
        f"Nota do checklist **{format_pct(view.score * 100)}** · {view.yes} Sim{no_part} "
        f"de {view.total} perguntas ({view.total - view.answered} sem resposta)."
    )


def render_form(ctx: PageContext, view: ChecklistView, key_prefix: str) -> None:
    """Formulário com as perguntas do ativo; respostas automáticas mostram a evidência."""
    st.markdown(score_caption(view))
    st.caption(
        "Sem resposta não soma nem desconta. A resposta manual vale mais que a automática; "
        "escolha Automática para voltar a usar o dado aberto."
    )
    with st.form(f"{key_prefix}_checklist_{view.ticker}"):
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
                key=f"{key_prefix}_chk_{view.ticker}_{q.key}",
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


@st.dialog("Questionário de importância", width="large")
def open_dialog(ctx: PageContext, view: ChecklistView) -> None:
    st.markdown(f"### {view.ticker}")
    render_form(ctx, view, "dialog")


def _preset_of(weights: ChecklistWeightsDTO) -> str | None:
    # Só a razão Não/Sim muda a nota, então (0,5; 1) também é "Conservador".
    for name, (yes, no) in PRESETS.items():
        if abs(no / yes - weights.no / weights.yes) < 1e-9:
            return name
    return None


def weights_editor(ctx: PageContext, key_prefix: str) -> None:
    """Escolha da postura: quanto vale cada Sim e quanto desconta cada Não.

    Vale para todos os ativos do usuário e fica salva no banco.
    """
    saved = ctx.container.get_checklist_weights.execute()
    st.markdown("**Peso das respostas**")
    st.caption(
        "nota = (Sim × peso do Sim − Não × peso do Não) ÷ (perguntas × peso do Sim), "
        "nunca abaixo de 0. Quanto maior o peso do Não em relação ao Sim, mais um ponto "
        "fraco derruba a nota: postura mais conservadora."
    )
    preset_names = list(PRESETS)
    current = _preset_of(saved)
    preset = st.radio(
        "Postura",
        [*preset_names, "Personalizado"],
        index=preset_names.index(current) if current in preset_names else len(preset_names),
        key=f"{key_prefix}_weights_preset",
    )
    with st.form(f"{key_prefix}_weights_form"):
        default_yes, default_no = PRESETS.get(preset, (saved.yes, saved.no))
        col1, col2 = st.columns(2)
        yes = col1.slider(
            "Peso do Sim", 0.25, 3.0, float(default_yes), 0.25, key=f"{key_prefix}_yes_{preset}"
        )
        no = col2.slider(
            "Peso do Não", 0.0, 5.0, float(default_no), 0.25, key=f"{key_prefix}_no_{preset}"
        )
        # Exemplo concreto para a escolha não ficar abstrata: 11 perguntas, 7 Sim e 3 Não.
        example = max(0.0, (7 * yes - 3 * no) / (11 * yes))
        st.caption(
            f"Exemplo: ação com 7 Sim, 3 Não e 1 sem resposta → nota "
            f"{format_pct(example * 100)}. Um Não anula {format_number(no / yes)} Sim."
        )
        if st.form_submit_button("Salvar pesos"):
            try:
                ctx.container.save_checklist_weights.execute(
                    SaveChecklistWeightsRequest(
                        user_id=ctx.user_id, weights=ChecklistWeightsDTO(yes=yes, no=no)
                    )
                )
            except (DomainError, ValueError) as error:
                st.error(str(error))
            else:
                cache.invalidate()
                st.rerun()
