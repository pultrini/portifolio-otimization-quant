"""Testes do use case de métricas com dados de mercado em memória."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from application.dtos.metrics import MetricsRequest
from application.dtos.portfolio import ImportPositionsRequest, RegisterTradeRequest
from application.use_cases.import_positions import ImportPositions
from application.use_cases.metrics import CalculateMetrics
from application.use_cases.trades import RegisterTrade
from domain.value_objects.strategy_type import StrategyType, TradeSide
from tests.fakes.in_memory_repositories import (
    FakeMarketDataRepository,
    InMemoryPositionRepository,
    InMemoryTradeRepository,
)

BRT = timezone(timedelta(hours=-3))
DATES = [date(2026, 1, d) for d in (5, 6, 7, 8, 9, 12)]
MARKET = FakeMarketDataRepository(
    dates=DATES,
    history={
        "ABCD3": [10.0, 11.0, 10.5, 11.5, 12.0, 11.0],
        "WXYZ11": [100.0, 100.0, 101.0, 101.0, 102.0, 102.0],
        "^BVSP": [1000.0, 1010.0, 1000.0, 1020.0, 1030.0, 1010.0],
        # CDI de 0,05% ao dia.
        "CDI": [1.0005**i for i in range(6)],
    },
)


def _setup() -> tuple[InMemoryPositionRepository, InMemoryTradeRepository, CalculateMetrics]:
    positions = InMemoryPositionRepository()
    trades = InMemoryTradeRepository(positions)
    use_case = CalculateMetrics(positions, trades, MARKET, today=lambda: date(2026, 1, 12))
    return positions, trades, use_case


def test_escopos_carteira_e_classe() -> None:
    positions, _, use_case = _setup()
    ImportPositions(positions, MARKET).execute(
        ImportPositionsRequest(user_id="u", portfolio_id="p", text="ABCD3 10 9\nWXYZ11 1 90")
    )

    report = use_case.execute(MetricsRequest(portfolio_id="p", lookback_years=1))
    keys = [s.key for s in report.scopes]
    assert keys == ["portfolio", "BR_EQUITY"]

    portfolio = report.scopes[0]
    assert portfolio.error is None
    assert portfolio.benchmark == "^BVSP"
    assert portfolio.periods_per_year == 252
    assert portfolio.observations == 5
    # V: 200, 210, 206, 216, 222, 212 -> acumulado 212 / 200 - 1 = 6%.
    assert portfolio.metrics.cumulative_return == pytest.approx(0.06)
    assert portfolio.benchmark_metrics.cumulative_return == pytest.approx(0.01)
    assert portfolio.equity.values[0] == 1.0
    assert portfolio.equity.values[-1] == pytest.approx(1.06)
    assert portfolio.drawdown.values[2] == pytest.approx(206 / 210 - 1)
    assert portfolio.metrics.beta is not None
    assert portfolio.start == DATES[0]


def test_sharpe_desconta_cdi() -> None:
    positions, _, use_case = _setup()
    ImportPositions(positions, MARKET).execute(
        ImportPositionsRequest(user_id="u", portfolio_id="p", text="ABCD3 1 9")
    )
    scope = use_case.execute(MetricsRequest(portfolio_id="p")).scopes[0]
    returns = [11 / 10 - 1, 10.5 / 11 - 1, 11.5 / 10.5 - 1, 12 / 11.5 - 1, 11 / 12 - 1]
    excess = [r - 0.0005 for r in returns]
    mean = sum(excess) / 5
    std = (sum((x - mean) ** 2 for x in excess) / 4) ** 0.5
    assert scope.metrics.sharpe == pytest.approx(mean / std * 252**0.5)


def test_ativo_sem_historico_vira_erro_no_escopo() -> None:
    positions, _, use_case = _setup()
    ImportPositions(positions, MARKET).execute(
        ImportPositionsRequest(user_id="u", portfolio_id="p", text="NOPE3 1 1")
    )
    scope = use_case.execute(MetricsRequest(portfolio_id="p")).scopes[0]
    assert scope.error is not None
    assert "NOPE3" in scope.error


def test_estrategia_com_operacoes() -> None:
    positions, trades, use_case = _setup()
    register = RegisterTrade(positions, trades)

    def trade(side: TradeSide, qty: str, price: str, day: int, hour: int = 10) -> None:
        register.execute(
            RegisterTradeRequest(
                user_id="u",
                portfolio_id="p",
                ticker="ABCD3",
                side=side,
                strategy=StrategyType.SWING_TRADE,
                traded_at=datetime(2026, 1, day, hour, tzinfo=BRT),
                quantity=Decimal(qty),
                price=Decimal(price),
                costs=Decimal("1"),
            )
        )

    trade(TradeSide.BUY, "10", "10", 5)
    trade(TradeSide.SELL, "5", "11", 6)  # ganho
    trade(TradeSide.BUY, "5", "11.5", 8, 10)
    # Venda no mesmo dia da 2ª compra, mas o FIFO fecha o lote mais antigo (05/01):
    # não é day trade.
    trade(TradeSide.SELL, "5", "11", 8, 16)

    report = use_case.execute(MetricsRequest(portfolio_id="p"))
    swing = next(s for s in report.scopes if s.key == "SWING_TRADE")
    stats = swing.trade_stats
    assert stats is not None
    assert stats.closed_trades == 2
    # FIFO: 1ª venda fecha 5 do lote de 05/01 (custo 5 x 10,10 = 50,50; recebe 54).
    # 2ª venda fecha os outros 5 do mesmo lote (recebe 54) -> os dois ganham 3,50.
    assert stats.win_rate == 1.0
    assert stats.expectancy == Decimal("3.5")
    assert stats.day_trades == 0
    assert swing.error is None
    assert swing.observations >= 2
    # Sobra o lote de 08/01 aberto: a estratégia ainda tem posição.
    assert swing.equity.values[-1] > 0


def test_beta_contra_a_taxa_livre_de_risco_nao_e_calculado() -> None:
    positions, _, use_case = _setup()
    ImportPositions(positions, MARKET).execute(
        ImportPositionsRequest(user_id="u", portfolio_id="p", text="CDI R$ 100\nABCD3 1 9")
    )
    report = use_case.execute(MetricsRequest(portfolio_id="p"))
    fixed_income = next(s for s in report.scopes if s.key == "BR_FIXED_INCOME")
    # Benchmark da classe é o CDI, que também é a taxa livre de risco.
    assert fixed_income.benchmark == fixed_income.risk_free == "CDI"
    assert fixed_income.metrics.beta is None
    equity = next(s for s in report.scopes if s.key == "BR_EQUITY")
    assert equity.metrics.beta is not None
