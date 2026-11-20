"""Testes de validação do DTO de alocação alvo."""

import pytest
from pydantic import ValidationError

from application.dtos.allocation import SaveAllocationTargetsRequest
from domain.value_objects.asset_class import AssetClass


@pytest.mark.parametrize("pct", [-0.01, 100.01])
def test_rejeita_percentual_fora_de_0_a_100(pct: float) -> None:
    with pytest.raises(ValidationError):
        SaveAllocationTargetsRequest(
            user_id="user-1", portfolio_id="p-1", targets={AssetClass.CRYPTO: pct}
        )


@pytest.mark.parametrize("pct", [0.0, 100.0])
def test_aceita_limites_da_faixa(pct: float) -> None:
    request = SaveAllocationTargetsRequest(
        user_id="user-1", portfolio_id="p-1", targets={AssetClass.CRYPTO: pct}
    )
    assert request.targets[AssetClass.CRYPTO] == pct


def test_rejeita_classe_de_ativo_desconhecida() -> None:
    with pytest.raises(ValidationError):
        SaveAllocationTargetsRequest.model_validate(
            {"user_id": "user-1", "portfolio_id": "p-1", "targets": {"REAL_ESTATE": 10.0}}
        )
