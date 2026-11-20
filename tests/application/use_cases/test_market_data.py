"""Testes do refresh de dados de mercado e da importação que dispara o pipeline."""

from collections.abc import Sequence
from decimal import Decimal

from application.dtos.portfolio import ImportPositionsRequest
from application.use_cases.import_positions import ImportPositions
from application.use_cases.market_data import RefreshMarketData
from domain.repositories.market_data_repository import RefreshReport
from domain.value_objects.ticker import Ticker
from tests.fakes.in_memory_repositories import (
    FakeMarketDataRepository,
    InMemoryPositionRepository,
)


class FakeRefresher:
    """Registra os pedidos e, ao rodar, "publica" preços no repositório de mercado."""

    def __init__(self, market: FakeMarketDataRepository, prices: dict[str, float]) -> None:
        self.calls: list[tuple[list[str], int]] = []
        self._market = market
        self._prices = prices

    def refresh(self, tickers: Sequence[Ticker], years: int) -> RefreshReport:
        self.calls.append(([t.symbol for t in tickers], years))
        self._market._history.update({k: [v] for k, v in self._prices.items()})
        return RefreshReport({"gold": 10}, {"NOPE3": "sem dados"})


def test_refresh_usa_tickers_da_carteira_e_extras() -> None:
    positions = InMemoryPositionRepository()
    market = FakeMarketDataRepository()
    ImportPositions(positions, market).execute(
        ImportPositionsRequest(user_id="u", portfolio_id="p", text="ABCD3 1 10")
    )
    refresher = FakeRefresher(market, {})
    response = RefreshMarketData(refresher, positions, years=3).execute("p", ["nope3"])

    assert refresher.calls == [(["ABCD3", "NOPE3"], 3)]
    assert response.failed_tickers == {"NOPE3": "sem dados"}
    assert response.rows_by_layer == {"gold": 10}


def test_importacao_por_valor_busca_cotacao_que_falta() -> None:
    positions = InMemoryPositionRepository()
    market = FakeMarketDataRepository()
    refresher = FakeRefresher(market, {"CDI": 20.0})
    response = ImportPositions(positions, market, refresher, years=5).execute(
        ImportPositionsRequest(user_id="u", portfolio_id="p", text="CDI R$ 100\nABCD3 1 10")
    )

    # Só o ticker por valor sem cotação é baixado.
    assert refresher.calls == [(["CDI"], 5)]
    assert response.errors == []
    cdi = positions.get_position("p", Ticker("CDI"))
    assert cdi is not None
    assert cdi.quantity == Decimal("5")
