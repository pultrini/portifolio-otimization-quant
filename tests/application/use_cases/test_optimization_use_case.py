"""Testes dos use cases de otimização e sugestão de aporte."""

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from application.dtos.optimization import ContributionRequest, OptimizationRequest
from application.dtos.portfolio import ImportPositionsRequest
from application.use_cases.import_positions import ImportPositions
from application.use_cases.optimization import OptimizePortfolio, SuggestContribution
from domain.exceptions import DomainError
from domain.value_objects.asset_class import AssetClass
from tests.fakes.in_memory_portfolio_repository import InMemoryPortfolioRepository
from tests.fakes.in_memory_repositories import (
    FakeMarketDataRepository,
    InMemoryPositionRepository,
)

N = 120
DATES = [date(2026, 1, 1) + timedelta(days=i) for i in range(N)]
_rng = np.random.default_rng(42)


def _walk(drift: float, vol: float) -> list[float]:
    returns = _rng.normal(drift, vol, N - 1)
    return list(100 * np.concatenate(([1.0], np.cumprod(1 + returns))))


MARKET = FakeMarketDataRepository(
    dates=DATES,
    history={
        "AAAA3": _walk(0.001, 0.01),
        "BBBB3": _walk(0.0005, 0.02),
        "CCCC11": _walk(0.0003, 0.005),
        "CDI": [1.0005**i for i in range(N)],
    },
)


def _positions(text: str) -> InMemoryPositionRepository:
    positions = InMemoryPositionRepository()
    ImportPositions(positions, MARKET).execute(
        ImportPositionsRequest(user_id="u", portfolio_id="p", text=text)
    )
    return positions


def test_otimizacao_completa() -> None:
    positions = _positions("AAAA3 10 90\nBBBB3 5 90\nCCCC11 20 100\nCDI R$ 500")
    result = OptimizePortfolio(positions, MARKET, today=lambda: DATES[-1]).execute(
        OptimizationRequest(portfolio_id="p", lookback_years=1, frontier_points=8)
    )
    # Renda fixa (CDI) fica fora por padrão.
    assert result.excluded == ["CDI"]
    assert result.tickers == ["AAAA3", "BBBB3", "CCCC11"]
    # CDI de 0,05% ao dia anualizado em 252 dias.
    assert result.risk_free_rate == pytest.approx(1.0005**252 - 1)
    for point in [result.current, result.min_variance, result.max_sharpe, *result.frontier]:
        assert sum(point.weights.values()) == pytest.approx(1.0)
        assert min(point.weights.values()) >= -1e-9
    assert result.risk_parity is not None
    # Mínima variância tem a menor volatilidade de todas as carteiras.
    assert result.min_variance.volatility <= result.current.volatility + 1e-9
    assert result.min_variance.volatility <= result.risk_parity.volatility + 1e-9
    # Máximo Sharpe tem o maior Sharpe.
    sharpes = [p.sharpe for p in [result.current, *result.frontier] if p.sharpe is not None]
    assert result.max_sharpe.sharpe is not None
    assert result.max_sharpe.sharpe >= max(sharpes) - 1e-6
    assert len(result.correlation) == 3
    assert result.correlation[0][0] == pytest.approx(1.0)


def test_pesos_atuais_pelo_valor_de_mercado() -> None:
    positions = _positions("AAAA3 1 1\nBBBB3 1 1")
    result = OptimizePortfolio(positions, MARKET, today=lambda: DATES[-1]).execute(
        OptimizationRequest(portfolio_id="p", lookback_years=1)
    )
    a, b = MARKET._history["AAAA3"][-1], MARKET._history["BBBB3"][-1]
    assert result.current.weights["AAAA3"] == pytest.approx(a / (a + b))


def test_precisa_de_dois_ativos() -> None:
    with pytest.raises(DomainError):
        OptimizePortfolio(_positions("AAAA3 1 1\nCDI R$ 10"), MARKET).execute(
            OptimizationRequest(portfolio_id="p")
        )


def test_sugestao_de_aporte() -> None:
    # AAAA3: 2 cotas a R$ 50 = 100; CDI: R$ 300. Aporte de 100 -> patrimônio 500.
    # Alvo 50/50 = 250 cada: déficit só em renda variável (150) -> aporte todo nela.
    market = FakeMarketDataRepository(history={"AAAA3": [50.0], "CDI": [2.0]})
    portfolios = InMemoryPortfolioRepository()
    portfolio = portfolios.create_portfolio("u", "Principal")
    positions = InMemoryPositionRepository()
    ImportPositions(positions, market).execute(
        ImportPositionsRequest(
            user_id="u", portfolio_id=portfolio.id, text="AAAA3 2 40\nCDI R$ 300"
        )
    )
    portfolios.save_allocation_targets(
        "u", portfolio.id, {"BR_EQUITY": 50.0, "BR_FIXED_INCOME": 50.0}
    )
    plan = SuggestContribution(portfolios, positions, market).execute(
        ContributionRequest(portfolio_id=portfolio.id, amount=Decimal("100"))
    )
    rows = {r.asset_class: r for r in plan.rows}
    equity, fixed = rows[AssetClass.BR_EQUITY], rows[AssetClass.BR_FIXED_INCOME]
    assert plan.total_before == Decimal("400.00")
    assert plan.total_after == Decimal("500.00")
    assert equity.current_pct == pytest.approx(25.0)
    assert equity.delta_value == Decimal("150.00")
    assert equity.contribution == Decimal("100.00")
    assert fixed.contribution == Decimal("0")
    assert equity.final_pct == pytest.approx(40.0)
    assert plan.missing_prices == []


def test_sugestao_sem_perfil() -> None:
    portfolios = InMemoryPortfolioRepository()
    portfolio = portfolios.create_portfolio("u", "Principal")
    with pytest.raises(DomainError, match="perfil"):
        SuggestContribution(portfolios, InMemoryPositionRepository(), MARKET).execute(
            ContributionRequest(portfolio_id=portfolio.id, amount=Decimal("10"))
        )
