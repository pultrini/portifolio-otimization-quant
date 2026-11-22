"""Testes dos use cases de otimização e sugestão de aporte."""

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from application.dtos.optimization import (
    ContributionRequest,
    OptimizationRequest,
    QuantSimulationRequest,
    QuantSimulationResult,
)
from application.dtos.portfolio import ImportPositionsRequest
from application.use_cases.import_positions import ImportPositions
from application.use_cases.optimization import (
    OptimizePortfolio,
    SimulateQuantPortfolio,
    SuggestContribution,
)
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


# --- Simulação da melhor carteira quant -----------------------------------------------


def _simulation_setup(
    targets: dict[str, float] | None,
) -> tuple[InMemoryPortfolioRepository, InMemoryPositionRepository, FakeMarketDataRepository]:
    late = _walk(0.002, 0.01)
    # NOVO3 só começa a negociar na segunda metade da janela: encurtaria a janela.
    market = FakeMarketDataRepository(
        dates=DATES,
        history={
            **{k: v for k, v in MARKET._history.items()},
            "DDDD3": _walk(0.0008, 0.012),
            "NOVO3": [float("nan")] * (N // 2) + late[N // 2 :],
        },
    )
    portfolios = InMemoryPortfolioRepository()
    portfolio = portfolios.create_portfolio("u", "Principal")
    positions = InMemoryPositionRepository()
    ImportPositions(positions, market).execute(
        ImportPositionsRequest(
            user_id="u",
            portfolio_id=portfolio.id,
            text="AAAA3 10 90\nBBBB3 5 90\nCCCC11 20 100\nCDI R$ 500\nDDDD3 0 0\nNOVO3 0 0",
        )
    )
    if targets is not None:
        portfolios.save_allocation_targets("u", portfolio.id, targets)
    return portfolios, positions, market


def _simulate(targets: dict[str, float] | None, **options: object) -> QuantSimulationResult:
    portfolios, positions, market = _simulation_setup(targets)
    pid = portfolios.list_portfolios()[0].id
    use_case = SimulateQuantPortfolio(portfolios, positions, market, today=lambda: DATES[-1])
    return use_case.execute(QuantSimulationRequest(portfolio_id=pid, lookback_years=1, **options))  # type: ignore[arg-type]


def test_simulacao_respeita_perfil_e_inclui_lista_de_desejos() -> None:
    # Perfil com 10% em cripto, classe sem nenhum ativo: o alvo é redistribuído.
    result = _simulate({"BR_EQUITY": 63.0, "BR_FIXED_INCOME": 27.0, "CRYPTO": 10.0})
    assert any("Criptoativos" in w and "redistribuído" in w for w in result.warnings)
    weights = {r.ticker: r.weight for r in result.rows}
    # 63 / 90 = 70% em renda variável e 27 / 90 = 30% em renda fixa (só CDI).
    assert sum(w for t, w in weights.items() if t != "CDI") == pytest.approx(0.7, abs=1e-6)
    assert weights["CDI"] == pytest.approx(0.3, abs=1e-6)
    # O ativo desejado entra; o listado no meio da janela fica de fora, com motivo.
    assert "DDDD3" in weights
    assert "NOVO3" in result.excluded and "encurtaria" in result.excluded["NOVO3"]
    # Teto padrão de 25% por ativo dentro da renda variável (4 ativos x 25% >= 70%).
    assert max(w for t, w in weights.items() if t != "CDI") <= 0.25 + 1e-6
    assert result.current is not None
    assert result.simulated.sharpe is not None and result.current.sharpe is not None
    assert len(result.simulated_growth) == len(result.dates)
    assert sum(c.weight for c in result.classes) == pytest.approx(1.0)


def test_simulacao_converte_em_lotes_e_soma_o_aporte() -> None:
    result = _simulate(None, respect_targets=False, contribution=Decimal("1000"))
    assert result.excluded["CDI"] == "renda fixa fora da simulação (opção)"
    held = sum((r.current_value for r in result.rows), Decimal(0))
    assert result.base_value == held + Decimal("1000")
    for row in result.rows:
        # Ações e FIIs em cotas inteiras, sem passar do valor alvo.
        assert row.target_quantity == row.target_quantity.to_integral_value()
        assert row.target_quantity * row.price <= row.target_value
        assert row.delta_quantity == row.target_quantity - row.current_quantity
    desired = next(r for r in result.rows if r.ticker == "DDDD3")
    assert desired.in_watchlist and desired.current_quantity == 0


def test_simulacao_exige_perfil_quando_pedido() -> None:
    with pytest.raises(DomainError, match="perfil de alocação"):
        _simulate(None)


def test_simulacao_filtra_ativos_escolhidos() -> None:
    result = _simulate(None, respect_targets=False, tickers=["AAAA3", "BBBB3"])
    assert sorted(r.ticker for r in result.rows) == ["AAAA3", "BBBB3"]
