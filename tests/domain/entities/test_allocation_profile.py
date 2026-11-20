"""Testes do perfil de alocação alvo."""

from decimal import Decimal

import pytest

from domain.entities.allocation_profile import AllocationProfile
from domain.exceptions import InvalidAllocationError
from domain.value_objects.asset_class import AssetClass

D = Decimal


def test_aceita_100_exato() -> None:
    profile = AllocationProfile({AssetClass.BR_EQUITY: D("70"), AssetClass.CRYPTO: D("30")})
    assert profile.total == D("100")
    assert profile.target_for(AssetClass.INTL_EQUITY) == D("0")


@pytest.mark.parametrize("last", ["29.99", "30.01"])
def test_aceita_dentro_da_tolerancia(last: str) -> None:
    AllocationProfile({AssetClass.BR_EQUITY: D("70"), AssetClass.CRYPTO: D(last)})


@pytest.mark.parametrize("last", ["29.98", "30.02"])
def test_rejeita_fora_da_tolerancia(last: str) -> None:
    with pytest.raises(InvalidAllocationError):
        AllocationProfile({AssetClass.BR_EQUITY: D("70"), AssetClass.CRYPTO: D(last)})


def test_rejeita_perfil_vazio() -> None:
    with pytest.raises(InvalidAllocationError):
        AllocationProfile({})


def test_rejeita_percentual_negativo_mesmo_somando_100() -> None:
    with pytest.raises(InvalidAllocationError):
        AllocationProfile({AssetClass.BR_EQUITY: D("110"), AssetClass.CRYPTO: D("-10")})


def test_nao_e_alterado_pelo_dict_original() -> None:
    targets = {AssetClass.BR_EQUITY: D("100")}
    profile = AllocationProfile(targets)
    targets[AssetClass.CRYPTO] = D("50")
    assert AssetClass.CRYPTO not in profile.targets
