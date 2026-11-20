"""Testes do use case SaveAllocationTargets com repositório em memória."""

import pytest

from application.dtos.allocation import SaveAllocationTargetsRequest
from application.use_cases.save_allocation_targets import SaveAllocationTargets
from domain.value_objects.asset_class import AssetClass
from tests.fakes.in_memory_portfolio_repository import InMemoryPortfolioRepository


def test_salva_e_devolve_o_perfil_persistido() -> None:
    repo = InMemoryPortfolioRepository()
    portfolio = repo.create_portfolio(user_id="user-1", name="Principal")
    use_case = SaveAllocationTargets(repo)

    response = use_case.execute(
        SaveAllocationTargetsRequest(
            user_id="user-1",
            portfolio_id=portfolio.id,
            targets={AssetClass.BR_EQUITY: 60.0, AssetClass.BR_FIXED_INCOME: 40.0},
        )
    )

    assert response.portfolio_id == portfolio.id
    assert response.targets == {AssetClass.BR_EQUITY: 60.0, AssetClass.BR_FIXED_INCOME: 40.0}


def test_substitui_o_perfil_anterior() -> None:
    repo = InMemoryPortfolioRepository()
    portfolio = repo.create_portfolio(user_id="user-1", name="Principal")
    use_case = SaveAllocationTargets(repo)
    use_case.execute(
        SaveAllocationTargetsRequest(
            user_id="user-1", portfolio_id=portfolio.id, targets={AssetClass.CRYPTO: 10.0}
        )
    )

    response = use_case.execute(
        SaveAllocationTargetsRequest(
            user_id="user-1", portfolio_id=portfolio.id, targets={AssetClass.INTL_EQUITY: 100.0}
        )
    )

    assert response.targets == {AssetClass.INTL_EQUITY: 100.0}


def test_rejeita_gravacao_em_carteira_de_outro_usuario() -> None:
    repo = InMemoryPortfolioRepository()
    portfolio = repo.create_portfolio(user_id="user-1", name="Principal")
    use_case = SaveAllocationTargets(repo)

    with pytest.raises(PermissionError):
        use_case.execute(
            SaveAllocationTargetsRequest(
                user_id="user-2", portfolio_id=portfolio.id, targets={AssetClass.CRYPTO: 5.0}
            )
        )
