"""Contratos de dados de mercado (leitura da camada Gold e atualização do pipeline)."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from domain.value_objects.money import Money
from domain.value_objects.price_history import PriceHistory
from domain.value_objects.ticker import Ticker


class MarketDataRepository(Protocol):
    """Leitura de preços já tratados, sempre em BRL."""

    def latest_prices(self, tickers: Sequence[Ticker]) -> dict[Ticker, Money]:
        """Último preço disponível de cada ticker. Tickers sem dado ficam de fora."""
        ...

    def price_history(self, tickers: Sequence[Ticker], start: date | None = None) -> PriceHistory:
        """Preços alinhados nas datas em que todos os tickers têm cotação.

        Raises:
            MissingMarketDataError: algum ticker não tem histórico.
        """
        ...


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """Resultado de uma atualização de dados de mercado.

    Attributes:
        rows_by_layer: Linhas gravadas em cada camada (bronze, silver, gold).
        failed_tickers: Tickers que a fonte não retornou, com o motivo.
    """

    rows_by_layer: dict[str, int] = field(default_factory=dict)
    failed_tickers: dict[str, str] = field(default_factory=dict)


class MarketDataRefresher(Protocol):
    """Executa o pipeline medalhão para um conjunto de tickers."""

    def refresh(self, tickers: Sequence[Ticker], years: int) -> RefreshReport:
        """Baixa, limpa e consolida os dados dos tickers e das séries de referência."""
        ...
