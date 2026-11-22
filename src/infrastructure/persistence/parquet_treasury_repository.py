"""Leitura das cotações do Tesouro com taxas (data/gold/treasury.parquet)."""

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from domain.entities.treasury import TreasuryQuote
from domain.repositories.market_data_repository import TreasuryRepository
from domain.value_objects.ticker import Ticker


def _quote(row: dict[str, Any]) -> TreasuryQuote:
    return TreasuryQuote(
        ticker=row["ticker"],
        date=row["date"],
        maturity=row["maturity"],
        buy_rate=row["buy_rate"],
        sell_rate=row["sell_rate"],
        pu_buy=row["pu_buy"],
        pu_sell=row["pu_sell"],
    )


class ParquetTreasuryRepository(TreasuryRepository):
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "gold" / "treasury.parquet"

    def _scan(self) -> pl.LazyFrame | None:
        return pl.scan_parquet(self._path) if self._path.exists() else None

    def latest_quotes(self, tickers: Sequence[Ticker]) -> dict[Ticker, TreasuryQuote]:
        frame = self._scan()
        if frame is None or not tickers:
            return {}
        rows = (
            frame.filter(
                pl.col("ticker").is_in([t.symbol for t in tickers])
                & pl.col("pu_sell").is_not_null()
                & pl.col("sell_rate").is_not_null()
            )
            .sort("date")
            .group_by("ticker")
            .last()
            .collect()
        )
        return {Ticker(r["ticker"]): _quote(r) for r in rows.iter_rows(named=True)}

    def quote_on(self, ticker: Ticker, day: date) -> TreasuryQuote | None:
        frame = self._scan()
        if frame is None:
            return None
        rows = (
            frame.filter(
                (pl.col("ticker") == ticker.symbol)
                & (pl.col("date") <= day)
                & pl.col("pu_buy").is_not_null()
                & pl.col("buy_rate").is_not_null()
            )
            .sort("date")
            .tail(1)
            .collect()
        )
        return _quote(rows.row(0, named=True)) if rows.height else None
