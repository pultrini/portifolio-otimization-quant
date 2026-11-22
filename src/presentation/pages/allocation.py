"""Página: perfil de alocação alvo, alocação atual vs. alvo e sugestão de aporte."""

import logging
from decimal import Decimal

import streamlit as st

from application.dtos.allocation import SaveAllocationTargetsRequest
from application.dtos.contribution import AssetContributionRequest
from application.dtos.optimization import ContributionPlan
from domain.exceptions import DomainError
from domain.value_objects.asset_class import AssetClass
from presentation.charts.allocation import allocation_delta_bars, allocation_donuts
from presentation.components import cache
from presentation.components.contribution_panel import render_decision
from presentation.components.formatting import format_brl, format_pct
from presentation.components.questionnaire import weights_editor
from presentation.components.session import PageContext

logger = logging.getLogger(__name__)

# Mesma tolerância do domínio, usada só para o aviso antecipado na tela.
ALLOCATION_TOLERANCE_PP = 0.01


def _targets_form(ctx: PageContext) -> None:
    current = ctx.container.get_allocation_targets.execute(ctx.portfolio_id).targets
    with st.form("allocation_targets"):
        inputs: dict[AssetClass, float] = {}
        # Um campo por classe, pré-preenchido com o alvo salvo (ou 0 se ainda não existe).
        # Quatro por linha: com sete classes, uma linha só espremeria os rótulos.
        classes = list(AssetClass)
        cols = [c for _ in range(0, len(classes), 4) for c in st.columns(4)]
        for col, asset_class in zip(cols, classes, strict=False):
            inputs[asset_class] = col.number_input(
                f"{asset_class.label_pt} (%)",
                min_value=0.0,
                max_value=100.0,
                step=0.5,
                format="%.2f",
                value=float(current.get(asset_class, 0.0)),
            )
        submitted = st.form_submit_button("Salvar perfil")

    # Aviso antecipado na tela; quem barra de fato é o AllocationProfile no domínio.
    total = sum(inputs.values())
    if abs(total - 100.0) > ALLOCATION_TOLERANCE_PP:
        st.warning(f"A soma dos alvos é {format_pct(total)}. O perfil deve fechar em 100,00%.")

    if submitted:
        try:
            response = ctx.container.save_allocation_targets.execute(
                SaveAllocationTargetsRequest(
                    user_id=ctx.user_id, portfolio_id=ctx.portfolio_id, targets=inputs
                )
            )
        except DomainError as error:
            # Regra de negócio violada: a mensagem do domínio já está em português.
            st.error(str(error))
            return
        cache.invalidate()
        st.success("Perfil salvo.")
        logger.info("Perfil salvo para carteira %s: %s", ctx.portfolio_id, response.targets)


def _plan_table(plan: ContributionPlan) -> None:
    st.dataframe(
        [
            {
                "Classe": row.asset_class.label_pt,
                "Atual": format_brl(row.current_value),
                "Atual %": format_pct(row.current_pct),
                "Alvo %": format_pct(row.target_pct),
                "Falta (+) / sobra (−)": format_brl(row.delta_value),
                "Aportar": format_brl(row.contribution),
                "Vender": format_brl(row.sale),
                "Depois %": format_pct(row.final_pct),
            }
            for row in plan.rows
        ],
        hide_index=True,
        width="stretch",
    )


def _contribution_section(ctx: PageContext) -> None:
    st.subheader("Atual vs. alvo e sugestão de aporte")
    col1, col2, col3 = st.columns([2, 1, 1])
    amount = col1.number_input("Valor do aporte (R$)", min_value=0.0, step=100.0, format="%.2f")
    allow_sales = col2.toggle(
        "Permitir vendas",
        value=False,
        help="Sem vendas, o aporte vai para as classes mais abaixo do alvo.",
    )
    quant_weight = col3.slider(
        "Peso do critério quant",
        min_value=0,
        max_value=100,
        value=50,
        step=10,
        format="%d%%",
        help="O restante do peso vai para o checklist de perguntas.",
    )
    col_fund, col_weights = st.columns([1, 1])
    with col_weights.popover("⚖️ Peso das respostas do questionário", width="stretch"):
        weights_editor(ctx, "allocation")
    if col_fund.button("Atualizar fundamentos (dados abertos)", help="Yahoo Finance e CVM."):
        with st.spinner("Baixando balanços, cadastro da CVM e informes de FIIs..."):
            failures = ctx.container.refresh_fundamentals.execute(ctx.portfolio_id)
        cache.invalidate()
        st.success("Fundamentos atualizados.")
        for name, reason in failures.items():
            st.warning(f"{name}: {reason}")

    try:
        result = ctx.container.suggest_asset_contribution.execute(
            AssetContributionRequest(
                portfolio_id=ctx.portfolio_id,
                amount=Decimal(str(amount)),
                allow_sales=allow_sales,
                quant_weight=quant_weight / 100,
            )
        )
    except DomainError as error:
        st.info(str(error))
        return
    plan = result.plan
    if plan.missing_prices:
        st.warning(
            "Sem cotação para: "
            + ", ".join(plan.missing_prices)
            + ". Atualize os dados de mercado."
        )
    if plan.total_before == 0 and amount == 0:
        st.info("Carteira sem valor de mercado. Importe posições e atualize os dados.")
        return

    # Classe com posições e alvo 0% nunca recebe aporte: avisa (ex.: FIIs recém-movidos
    # para a classe própria, antes de o perfil ter um alvo para ela).
    without_target = [
        r.asset_class.label_pt for r in plan.rows if r.current_value > 0 and r.target_pct == 0
    ]
    if without_target:
        st.warning(
            "Classes com posições e alvo 0%: "
            + ", ".join(without_target)
            + ". Elas não recebem aporte; ajuste o perfil se quiser investir nelas."
        )

    cols = st.columns(2)
    cols[0].metric("Patrimônio atual", format_brl(plan.total_before))
    cols[1].metric("Após o aporte", format_brl(plan.total_after))
    st.plotly_chart(allocation_donuts(plan), width="stretch")
    st.plotly_chart(allocation_delta_bars(plan), width="stretch")
    _plan_table(plan)
    render_decision(ctx, result)


def render(ctx: PageContext) -> None:
    st.header("Alocação Alvo")
    st.caption(f"Carteira: {ctx.portfolio_name}")
    _targets_form(ctx)
    _contribution_section(ctx)
