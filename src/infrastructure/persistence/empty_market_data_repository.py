"""Repositório de mercado vazio, usado enquanto não há camada Gold gerada."""

from collections.abc import Sequence
from datetime import date

from domain.exceptions import MissingMarketDataError
from domain.repositories.market_data_repository import MarketDataRepository
from domain.value_objects.money import Money
from domain.value_objects.price_history import PriceHistory
from domain.value_objects.ticker import Ticker


class EmptyMarketDataRepository(MarketDataRepository):
    """Não tem cotações: posições aparecem sem valor de mercado."""

    def latest_prices(self, tickers: Sequence[Ticker]) -> dict[Ticker, Money]:
        return {}

    def price_history(self, tickers: Sequence[Ticker], start: date | None = None) -> PriceHistory:
        raise MissingMarketDataError("Dados de mercado ainda não foram gerados.")
