"""Testes do use case SaveAllocationTargets com repositório em memória."""

import pytest

from application.dtos.allocation import SaveAllocationTargetsRequest
from application.use_cases.save_allocation_targets import SaveAllocationTargets
from domain.exceptions import InvalidAllocationError
from domain.value_objects.asset_class import AssetClass
from tests.fakes.in_memory_portfolio_repository import InMemoryPortfolioRepository


def _setup() -> tuple[InMemoryPortfolioRepository, str, SaveAllocationTargets]:
    repo = InMemoryPortfolioRepository()
    portfolio = repo.create_portfolio(user_id="user-1", name="Principal")
    return repo, portfolio.id, SaveAllocationTargets(repo)


def test_salva_e_devolve_o_perfil_persistido() -> None:
    _, portfolio_id, use_case = _setup()

    response = use_case.execute(
        SaveAllocationTargetsRequest(
            user_id="user-1",
            portfolio_id=portfolio_id,
            targets={AssetClass.BR_EQUITY: 60.0, AssetClass.BR_FIXED_INCOME: 40.0},
        )
    )

    assert response.portfolio_id == portfolio_id
    assert response.targets == {AssetClass.BR_EQUITY: 60.0, AssetClass.BR_FIXED_INCOME: 40.0}


def test_substitui_o_perfil_anterior() -> None:
    _, portfolio_id, use_case = _setup()
    use_case.execute(
        SaveAllocationTargetsRequest(
            user_id="user-1",
            portfolio_id=portfolio_id,
            targets={AssetClass.CRYPTO: 10.0, AssetClass.BR_EQUITY: 90.0},
        )
    )

    response = use_case.execute(
        SaveAllocationTargetsRequest(
            user_id="user-1", portfolio_id=portfolio_id, targets={AssetClass.INTL_EQUITY: 100.0}
        )
    )

    assert response.targets == {AssetClass.INTL_EQUITY: 100.0}


def test_classes_com_zero_nao_sao_gravadas() -> None:
    _, portfolio_id, use_case = _setup()

    response = use_case.execute(
        SaveAllocationTargetsRequest(
            user_id="user-1",
            portfolio_id=portfolio_id,
            targets={AssetClass.BR_EQUITY: 100.0, AssetClass.CRYPTO: 0.0},
        )
    )

    assert response.targets == {AssetClass.BR_EQUITY: 100.0}


def test_aceita_soma_dentro_da_tolerancia() -> None:
    _, portfolio_id, use_case = _setup()
    # 33.33 x 3 = 99.99: diferença de 0.01 p.p., exatamente no limite da tolerância.
    targets = {
        AssetClass.BR_EQUITY: 33.33,
        AssetClass.BR_FIXED_INCOME: 33.33,
        AssetClass.CRYPTO: 33.33,
    }
    response = use_case.execute(
        SaveAllocationTargetsRequest(user_id="user-1", portfolio_id=portfolio_id, targets=targets)
    )
    assert sum(response.targets.values()) == pytest.approx(99.99)


def test_rejeita_soma_diferente_de_100_e_nao_grava() -> None:
    repo, portfolio_id, use_case = _setup()

    with pytest.raises(InvalidAllocationError):
        use_case.execute(
            SaveAllocationTargetsRequest(
                user_id="user-1",
                portfolio_id=portfolio_id,
                targets={AssetClass.BR_EQUITY: 60.0, AssetClass.CRYPTO: 30.0},
            )
        )
    assert repo.get_allocation_targets(portfolio_id) == {}


def test_rejeita_gravacao_em_carteira_de_outro_usuario() -> None:
    _, portfolio_id, use_case = _setup()

    with pytest.raises(PermissionError):
        use_case.execute(
            SaveAllocationTargetsRequest(
                user_id="user-2", portfolio_id=portfolio_id, targets={AssetClass.CRYPTO: 100.0}
            )
        )
