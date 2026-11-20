"""Leitura da camada Gold (Parquet) como `MarketDataRepository`."""

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from domain.exceptions import MissingMarketDataError
from domain.repositories.market_data_repository import MarketDataRepository
from domain.value_objects.money import Money
from domain.value_objects.price_history import PriceHistory
from domain.value_objects.ticker import Ticker


class ParquetMarketDataRepository(MarketDataRepository):
    """Lê `gold/prices.parquet` com avaliação preguiçosa e devolve estruturas do domínio.

    Polars não sai daqui: o retorno é `Money` ou `PriceHistory` (numpy).
    """

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "gold" / "prices.parquet"

    def _scan(self, tickers: Sequence[Ticker]) -> pl.LazyFrame | None:
        if not self._path.exists():
            return None
        symbols = [t.symbol for t in tickers]
        return pl.scan_parquet(self._path).filter(pl.col("ticker").is_in(symbols))

    def latest_prices(self, tickers: Sequence[Ticker]) -> dict[Ticker, Money]:
        frame = self._scan(tickers)
        if frame is None or not tickers:
            return {}
        latest = frame.sort("date").group_by("ticker").agg(pl.col("price_brl").last()).collect()
        # float -> str com 8 casas -> Decimal: valor monetário entra no domínio já exato.
        prices = {
            str(row["ticker"]): Money.brl(f"{float(row['price_brl']):.8f}")
            for row in latest.iter_rows(named=True)
        }
        return {t: prices[t.symbol] for t in tickers if t.symbol in prices}

    def price_history(self, tickers: Sequence[Ticker], start: date | None = None) -> PriceHistory:
        """Matriz de preços nas datas comuns a todos os tickers.

        O pivot cria uma coluna por ticker; `drop_nulls` mantém só as datas em que todos
        negociaram, então o retorno entre linhas é o retorno real do intervalo.
        """
        symbols = list(dict.fromkeys(t.symbol for t in tickers))
        frame = self._scan(tickers)
        if frame is None:
            raise MissingMarketDataError("Dados de mercado ainda não foram gerados.")
        if start is not None:
            frame = frame.filter(pl.col("date") >= start)
        long = frame.select("date", "ticker", "price_brl").collect()
        missing = sorted(set(symbols) - set(long.get_column("ticker").unique().to_list()))
        if missing:
            raise MissingMarketDataError(f"Sem histórico para {', '.join(missing)}.")
        wide = (
            long.pivot(on="ticker", index="date", values="price_brl")
            .drop_nulls()
            .sort("date")
            .select("date", *symbols)
        )
        return PriceHistory(
            dates=tuple(wide.get_column("date").to_list()),
            tickers=tuple(symbols),
            prices=wide.select(symbols).to_numpy().astype("float64"),
        )
