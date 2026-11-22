"""Monta um `PageContext` completo com repositórios em memória para testar as páginas.

Usado pelos scripts do `AppTest` do Streamlit: as páginas rodam de verdade (widgets,
gráficos, tabelas), mas sem Supabase nem rede.
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np

from application.dtos.portfolio import ImportPositionsRequest, RegisterTradeRequest
from domain.repositories.market_data_repository import RefreshReport
from domain.value_objects.strategy_type import StrategyType, TradeSide
from domain.value_objects.ticker import Ticker
from presentation.components.session import PageContext
from presentation.container import Container, assemble
from tests.fakes.in_memory_portfolio_repository import InMemoryPortfolioRepository
from tests.fakes.in_memory_repositories import (
    FakeFundamentalsRepository,
    FakeMarketDataRepository,
    InMemoryChecklistRepository,
    InMemoryPositionRepository,
    InMemorySavingsGoalRepository,
    InMemoryTradeRepository,
    NoopFundamentalsRefresher,
)

BRT = timezone(timedelta(hours=-3))
N = 400
END = date(2026, 11, 19)


class NoopRefresher:
    def refresh(self, tickers: Sequence[Ticker], years: int) -> RefreshReport:
        return RefreshReport({"bronze": 0, "silver": 0, "gold": 0}, {})


def _market() -> FakeMarketDataRepository:
    rng = np.random.default_rng(7)
    dates = [END - timedelta(days=N - 1 - i) for i in range(N)]

    def walk(start: float, drift: float, vol: float) -> list[float]:
        steps = rng.normal(drift, vol, N - 1)
        return list(start * np.concatenate(([1.0], np.cumprod(1 + steps))))

    return FakeMarketDataRepository(
        dates=dates,
        history={
            "AAAA3": walk(25.0, 0.0004, 0.015),
            "BBBB4": walk(40.0, 0.0002, 0.02),
            "DDDD3": walk(15.0, 0.0006, 0.018),
            "CCCC11": walk(100.0, 0.0001, 0.006),
            "BTC": walk(350000.0, 0.001, 0.03),
            "^BVSP": walk(130000.0, 0.0003, 0.011),
            "XFIX11": walk(10.0, 0.0002, 0.005),
            "CDI": [1.0005**i for i in range(N)],
            "TBILL3M": [1.00016**i for i in range(N)],
        },
    )


def build_container() -> tuple[Container, str]:
    portfolios = InMemoryPortfolioRepository()
    positions = InMemoryPositionRepository()
    trades = InMemoryTradeRepository(positions)
    market = _market()
    bbbb4 = market._history["BBBB4"]
    container = assemble(
        portfolios,
        positions,
        trades,
        market,
        NoopRefresher(),
        years=5,
        fundamentals=FakeFundamentalsRepository(),
        fundamentals_refresher=NoopFundamentalsRefresher(),
        checklist=InMemoryChecklistRepository(),
        goals=InMemorySavingsGoalRepository(),
    )

    portfolio = portfolios.create_portfolio("user-1", "Principal")
    container.import_positions.execute(
        ImportPositionsRequest(
            user_id="user-1",
            portfolio_id=portfolio.id,
            text="AAAA3 10 24,00\nBBBB4 5 38\nCCCC11 3 95\nCDI R$ 600\nBTC R$ 150 170\nDDDD3 0 0",
        )
    )
    portfolios.save_allocation_targets(
        "user-1",
        portfolio.id,
        {"BR_EQUITY": 50.0, "BR_REAL_ESTATE": 10.0, "BR_FIXED_INCOME": 30.0, "CRYPTO": 10.0},
    )
    # Operações ao preço de mercado do dia (índice `day` na série sintética).
    for side, qty, day in (
        (TradeSide.BUY, "10", 10),
        (TradeSide.SELL, "4", 40),
        (TradeSide.BUY, "2", 60),
    ):
        price = f"{bbbb4[day]:.2f}"
        container.register_trade.execute(
            RegisterTradeRequest(
                user_id="user-1",
                portfolio_id=portfolio.id,
                ticker="BBBB4",
                side=side,
                strategy=StrategyType.SWING_TRADE,
                traded_at=datetime.combine(
                    END - timedelta(days=N - 1 - day), datetime.min.time(), tzinfo=BRT
                ).replace(hour=11),
                quantity=Decimal(qty),
                price=Decimal(price),
                costs=Decimal("1"),
            )
        )
    return container, portfolio.id


def build_context() -> PageContext:
    """Contexto da página; guardado na sessão para que gravações sobrevivam ao rerun."""
    import streamlit as st

    if "_harness" not in st.session_state:
        st.session_state["_harness"] = build_container()
    container, portfolio_id = st.session_state["_harness"]
    return PageContext(container, "user-1", portfolio_id, "Principal")
