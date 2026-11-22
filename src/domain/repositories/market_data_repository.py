"""Contratos de dados de mercado (leitura da camada Gold e atualização do pipeline)."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from domain.entities.treasury import BondTerms, TreasuryQuote
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


class TreasuryRepository(Protocol):
    """Cotações do Tesouro Direto com taxas (camada Gold)."""

    def latest_quotes(self, tickers: Sequence[Ticker]) -> dict[Ticker, TreasuryQuote]:
        """Última cotação com PU de venda de cada título. Títulos sem dado ficam de fora."""
        ...

    def quote_on(self, ticker: Ticker, day: date) -> TreasuryQuote | None:
        """Cotação com PU de compra do dia (ou do último dia útil antes dele)."""
        ...


class BondTermsRepository(Protocol):
    """Taxa contratada de cada título, por carteira (Supabase, com RLS)."""

    def terms(self, portfolio_id: str) -> dict[Ticker, BondTerms]: ...

    def save_terms(
        self, user_id: str, portfolio_id: str, ticker: Ticker, terms: BondTerms
    ) -> None: ...

    def delete_terms(self, portfolio_id: str, ticker: Ticker) -> None: ...
