"""Página: perfil de alocação alvo por classe de ativo."""

import logging

import streamlit as st

from application.dtos.allocation import SaveAllocationTargetsRequest
from domain.exceptions import DomainError
from domain.value_objects.asset_class import AssetClass
from presentation.components.formatting import format_pct
from presentation.components.session import PageContext

logger = logging.getLogger(__name__)

# Mesma tolerância do domínio, usada só para o aviso antecipado na tela.
ALLOCATION_TOLERANCE_PP = 0.01


def render(ctx: PageContext) -> None:
    st.header("Perfil de Alocação Alvo")
    st.caption(f"Carteira: {ctx.portfolio_name}")
    current = ctx.container.get_allocation_targets.execute(ctx.portfolio_id).targets

    with st.form("allocation_targets"):
        inputs: dict[AssetClass, float] = {}
        # Um campo por classe, pré-preenchido com o alvo salvo (ou 0 se ainda não existe).
        for asset_class in AssetClass:
            inputs[asset_class] = st.number_input(
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
        st.success("Perfil salvo.")
        logger.info("Perfil salvo para carteira %s: %s", ctx.portfolio_id, response.targets)
