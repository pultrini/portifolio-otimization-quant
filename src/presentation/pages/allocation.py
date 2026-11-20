"""Página: perfil de alocação alvo, alocação atual vs. alvo e sugestão de aporte."""

import logging
from decimal import Decimal

import streamlit as st

from application.dtos.allocation import SaveAllocationTargetsRequest
from application.dtos.optimization import ContributionPlan, ContributionRequest
from domain.exceptions import DomainError
from domain.value_objects.asset_class import AssetClass
from presentation.charts.allocation import allocation_delta_bars, allocation_donuts
from presentation.components import cache
from presentation.components.formatting import format_brl, format_pct
from presentation.components.session import PageContext

logger = logging.getLogger(__name__)

# Mesma tolerância do domínio, usada só para o aviso antecipado na tela.
ALLOCATION_TOLERANCE_PP = 0.01


def _targets_form(ctx: PageContext) -> None:
    current = ctx.container.get_allocation_targets.execute(ctx.portfolio_id).targets
    with st.form("allocation_targets"):
        inputs: dict[AssetClass, float] = {}
        cols = st.columns(len(AssetClass))
        # Um campo por classe, pré-preenchido com o alvo salvo (ou 0 se ainda não existe).
        for col, asset_class in zip(cols, AssetClass, strict=True):
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
        use_container_width=True,
    )


def _contribution_section(ctx: PageContext) -> None:
    st.subheader("Atual vs. alvo e sugestão de aporte")
    col1, col2 = st.columns([2, 1])
    amount = col1.number_input("Valor do aporte (R$)", min_value=0.0, step=100.0, format="%.2f")
    allow_sales = col2.toggle(
        "Permitir vendas",
        value=False,
        help="Sem vendas, o aporte vai para as classes mais abaixo do alvo.",
    )
    try:
        plan = ctx.container.suggest_contribution.execute(
            ContributionRequest(
                portfolio_id=ctx.portfolio_id,
                amount=Decimal(str(amount)),
                allow_sales=allow_sales,
            )
        )
    except DomainError as error:
        st.info(str(error))
        return
    if plan.missing_prices:
        st.warning(
            "Sem cotação para: "
            + ", ".join(plan.missing_prices)
            + ". Atualize os dados de mercado."
        )
    if plan.total_before == 0 and amount == 0:
        st.info("Carteira sem valor de mercado. Importe posições e atualize os dados.")
        return

    cols = st.columns(2)
    cols[0].metric("Patrimônio atual", format_brl(plan.total_before))
    cols[1].metric("Após o aporte", format_brl(plan.total_after))
    st.plotly_chart(allocation_donuts(plan), use_container_width=True)
    st.plotly_chart(allocation_delta_bars(plan), use_container_width=True)
    _plan_table(plan)


def render(ctx: PageContext) -> None:
    st.header("Alocação Alvo")
    st.caption(f"Carteira: {ctx.portfolio_name}")
    _targets_form(ctx)
    _contribution_section(ctx)
