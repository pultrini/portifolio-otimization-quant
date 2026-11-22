"""Leitura da Gold de fundamentos como `FundamentalsRepository`."""

from collections.abc import Sequence
from pathlib import Path

import polars as pl

from domain.entities.fundamentals import AnnualFigures, ReitFundamentals, StockFundamentals
from domain.repositories.fundamentals_repository import FundamentalsRepository
from domain.value_objects.ticker import Ticker


class ParquetFundamentalsRepository(FundamentalsRepository):
    """Converte as tabelas Gold em entidades do domínio (polars não sai daqui)."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir / "gold" / "fundamentals"

    def _frame(self, name: str, tickers: Sequence[Ticker]) -> pl.DataFrame | None:
        path = self._dir / f"{name}.parquet"
        if not path.exists():
            return None
        symbols = [t.symbol for t in tickers]
        return pl.scan_parquet(path).filter(pl.col("ticker").is_in(symbols)).collect()

    def stock_fundamentals(self, tickers: Sequence[Ticker]) -> dict[Ticker, StockFundamentals]:
        annual = self._frame("stock_annual", tickers)
        profile = self._frame("stock_profile", tickers)
        figures: dict[str, list[AnnualFigures]] = {}
        if annual is not None:
            for row in annual.iter_rows(named=True):
                figures.setdefault(row["ticker"], []).append(
                    AnnualFigures(
                        year=int(row["year"]),
                        revenue=row["revenue"],
                        net_income=row["net_income"],
                        ebitda=row["ebitda"],
                        equity=row["equity"],
                        total_debt=row["total_debt"],
                        cash=row["cash"],
                    )
                )
        result: dict[Ticker, StockFundamentals] = {}
        if profile is not None:
            for row in profile.iter_rows(named=True):
                ticker = Ticker(row["ticker"])
                result[ticker] = StockFundamentals(
                    ticker=ticker.symbol,
                    annual=tuple(figures.get(ticker.symbol, [])),
                    dividend_years=frozenset(int(y) for y in row["dividend_years"] or []),
                    constitution_date=row["constitution_date"],
                    control=row["control"],
                    market_cap_brl=row["market_cap_brl"],
                )
        return result

    def listed_reits(self) -> frozenset[str]:
        path = self._dir / "reit_profile.parquet"
        if not path.exists():
            return frozenset()
        tickers = pl.scan_parquet(path).select("ticker").collect().to_series()
        return frozenset(str(t) for t in tickers)

    def reit_fundamentals(self, tickers: Sequence[Ticker]) -> dict[Ticker, ReitFundamentals]:
        frame = self._frame("reit_profile", tickers)
        if frame is None:
            return {}
        return {
            Ticker(row["ticker"]): ReitFundamentals(
                ticker=row["ticker"],
                segment=row["segment"],
                book_value_per_share=row["book_value_per_share"],
                months_with_dividends=int(row["months_with_dividends"]),
                months_observed=int(row["months_observed"]),
                dividend_yield_12m=row["dividend_yield_12m"],
                segment_median_yield_12m=row["segment_median_yield_12m"],
                reference_month=row["reference_month"],
            )
            for row in frame.iter_rows(named=True)
        }
