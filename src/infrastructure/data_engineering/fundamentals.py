"""Pipeline medalhão de fundamentos (respostas automáticas do checklist).

Bronze: CSVs da CVM e dados do Yahoo exatamente como vieram.
Silver: tabelas limpas, tipadas, um snapshot por código.
Gold:   stock_annual (números anuais), stock_profile (cadastro, valor de mercado,
        anos com proventos) e reit_profile (P/VP, constância, yield vs. segmento).

Mesmas regras de idempotência do pipeline de preços: Bronze por fonte/dia/código,
Silver e Gold reconstruídas por inteiro a cada execução.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from domain.repositories.fundamentals_repository import FundamentalsRefresher
from domain.value_objects.ticker import Ticker
from infrastructure.data_engineering.layers import (
    _latest_snapshot,
    _scan_bronze,
    _write,
    write_bronze,
)
from infrastructure.data_engineering.schemas import (
    CVM_REGISTRY_BRONZE,
    CVM_REIT_COMPLEMENT_BRONZE,
    CVM_REIT_GENERAL_BRONZE,
    CVM_SECURITIES_BRONZE,
    DIVIDENDS_BRONZE,
    GOLD_REIT_PROFILE,
    GOLD_STOCK_ANNUAL,
    GOLD_STOCK_PROFILE,
    PROFILE_BRONZE,
    STATEMENTS_BRONZE,
    validate,
    with_ingestion,
)
from infrastructure.market_data.clients import SourceError
from infrastructure.market_data.fundamentals_clients import (
    CvmClient,
    YahooFundamentalsClient,
    recent_years,
)
from infrastructure.market_data.instruments import PriceCurrency, Source, resolve

logger = logging.getLogger(__name__)

# Anos de informes mensais de FII: 4 anos completos + o ano corrente (janela de 48 meses).
REIT_YEARS = 5
REIT_WINDOW_MONTHS = 48

# Itens do Yahoo para cada número anual, em ordem de preferência (nomes variam por empresa).
_ITEMS: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "equity": ("Stockholders Equity", "Common Stock Equity"),
    "total_debt": ("Total Debt",),
    "cash": ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
}


def _silver(data_dir: Path) -> Path:
    return data_dir / "silver" / "fundamentals"


def _gold(data_dir: Path) -> Path:
    return data_dir / "gold" / "fundamentals"


# ========================================================================= Silver


def build_fundamentals_silver(data_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    out = _silver(data_dir)

    registry = _scan_bronze(data_dir, Source.CVM_REGISTRY)
    if registry is not None:
        frame = (
            _latest_snapshot(
                registry.select(with_ingestion(CVM_REGISTRY_BRONZE).names()).with_columns(
                    pl.lit("all").alias("_k")
                ),
                "_k",
            )
            .select(
                pl.col("CNPJ_CIA").alias("cnpj"),
                pl.col("DENOM_SOCIAL").alias("name"),
                pl.col("DT_CONST").str.to_date("%Y-%m-%d", strict=False).alias("constitution_date"),
                pl.col("SIT").alias("status"),
                pl.col("SETOR_ATIV").alias("sector"),
                pl.col("CONTROLE_ACIONARIO").alias("control"),
            )
            # Uma linha por CNPJ, preferindo o registro ativo.
            .sort("cnpj", pl.col("status") == "ATIVO", descending=[False, True])
            .unique(subset=["cnpj"], keep="first", maintain_order=True)
            .collect()
        )
        counts["cvm_registry"] = _write(frame, out / "cvm_registry.parquet")

    securities = _scan_bronze(data_dir, Source.CVM_SECURITIES)
    if securities is not None:
        frame = (
            _latest_snapshot(
                securities.select(with_ingestion(CVM_SECURITIES_BRONZE).names()).with_columns(
                    pl.lit("all").alias("_k")
                ),
                "_k",
            )
            .select(
                pl.col("CNPJ_Companhia").alias("cnpj"),
                pl.col("Codigo_Negociacao").str.strip_chars().alias("code"),
            )
            .filter(pl.col("code").is_not_null() & (pl.col("code") != ""))
            .unique()
            .collect()
        )
        counts["cvm_securities"] = _write(frame, out / "cvm_securities.parquet")

    general = _scan_bronze(data_dir, Source.CVM_REIT_GENERAL)
    complement = _scan_bronze(data_dir, Source.CVM_REIT_COMPLEMENT)
    if general is not None and complement is not None:
        # Cada ano é um arquivo; o mais recente de cada ano vale (key = ano no caminho).
        g = (
            general.select(with_ingestion(CVM_REIT_GENERAL_BRONZE).names())
            .select(
                pl.col("CNPJ_Fundo_Classe").alias("cnpj"),
                pl.col("Data_Referencia").str.to_date("%Y-%m-%d", strict=False).alias("month"),
                pl.col("Codigo_ISIN").alias("isin"),
                pl.col("Segmento_Atuacao").alias("segment"),
                (pl.col("Mercado_Negociacao_Bolsa") == "S").alias("listed"),
                "ingested_at",
            )
            .sort("ingested_at")
            .unique(subset=["cnpj", "month"], keep="last")
        )
        c = (
            complement.select(with_ingestion(CVM_REIT_COMPLEMENT_BRONZE).names())
            .select(
                pl.col("CNPJ_Fundo_Classe").alias("cnpj"),
                pl.col("Data_Referencia").str.to_date("%Y-%m-%d", strict=False).alias("month"),
                pl.col("Valor_Patrimonial_Cotas")
                .cast(pl.Float64, strict=False)
                .alias("book_value_per_share"),
                pl.col("Percentual_Dividend_Yield_Mes")
                .cast(pl.Float64, strict=False)
                .alias("dividend_yield"),
                "ingested_at",
            )
            # Reenvios do mesmo mês (versões) ficam com o último ingerido.
            .sort("ingested_at")
            .unique(subset=["cnpj", "month"], keep="last")
            .drop("ingested_at")
        )
        frame = (
            g.drop("ingested_at")
            .join(c, on=["cnpj", "month"], how="inner")
            .filter(pl.col("month").is_not_null())
            .sort("cnpj", "month")
            .collect()
        )
        counts["reit_monthly"] = _write(frame, out / "reit_monthly.parquet")

    statements = _scan_bronze(data_dir, Source.YAHOO_STATEMENTS)
    if statements is not None:
        frame = (
            _latest_snapshot(statements.select(with_ingestion(STATEMENTS_BRONZE).names()), "symbol")
            .select(
                pl.col("symbol"),
                "statement",
                "item",
                pl.col("period_end").dt.year().cast(pl.Int32).alias("year"),
                "value",
            )
            .unique(subset=["symbol", "statement", "item", "year"], keep="last")
            .collect()
        )
        counts["statements"] = _write(frame, out / "statements.parquet")

    profile = _scan_bronze(data_dir, Source.YAHOO_PROFILE)
    if profile is not None:
        frame = (
            _latest_snapshot(profile.select(with_ingestion(PROFILE_BRONZE).names()), "symbol")
            .select("symbol", "market_cap", "currency")
            .collect()
        )
        counts["profile"] = _write(frame, out / "profile.parquet")

    dividends = _scan_bronze(data_dir, Source.YAHOO_DIVIDENDS)
    if dividends is not None:
        frame = (
            _latest_snapshot(dividends.select(with_ingestion(DIVIDENDS_BRONZE).names()), "symbol")
            .filter(pl.col("amount") > 0)
            .select("symbol", "date", "amount")
            .unique()
            .collect()
        )
        counts["dividends"] = _write(frame, out / "dividends.parquet")
    return counts


# =========================================================================== Gold


def _read(path: Path) -> pl.DataFrame | None:
    return pl.read_parquet(path) if path.exists() else None


def _ticker_from_symbol(symbol: str) -> str:
    return symbol.removesuffix(".SA")


def build_fundamentals_gold(data_dir: Path) -> dict[str, int]:
    silver = _silver(data_dir)
    gold = _gold(data_dir)
    counts: dict[str, int] = {}

    statements = _read(silver / "statements.parquet")
    if statements is not None and statements.height:
        columns = []
        for field, items in _ITEMS.items():
            # Primeiro item disponível na ordem de preferência (coalesce).
            exprs = [pl.col("value").filter(pl.col("item") == item).first() for item in items]
            columns.append(pl.coalesce(exprs).alias(field))
        annual = (
            statements.group_by("symbol", "year")
            .agg(columns)
            .with_columns(pl.col("symbol").str.strip_suffix(".SA").alias("ticker"))
            .select(GOLD_STOCK_ANNUAL.names())
            .with_columns(pl.col("year").cast(pl.Int32))
            .sort("ticker", "year")
        )
        counts["stock_annual"] = _write(
            validate(annual, GOLD_STOCK_ANNUAL, "gold/stock_annual"), gold / "stock_annual.parquet"
        )

    profile = _read(silver / "profile.parquet")
    if profile is not None and profile.height:
        counts["stock_profile"] = _write(
            validate(_stock_profile(data_dir, profile), GOLD_STOCK_PROFILE, "gold/stock_profile"),
            gold / "stock_profile.parquet",
        )

    monthly = _read(silver / "reit_monthly.parquet")
    if monthly is not None and monthly.height:
        counts["reit_profile"] = _write(
            validate(_reit_profile(monthly), GOLD_REIT_PROFILE, "gold/reit_profile"),
            gold / "reit_profile.parquet",
        )
    return counts


def _stock_profile(data_dir: Path, profile: pl.DataFrame) -> pl.DataFrame:
    """Valor de mercado em BRL, cadastro da CVM e anos com proventos por ticker."""
    silver = _silver(data_dir)
    fx = _read(data_dir / "gold" / "fx.parquet")
    usd_brl = (
        float(fx.sort("date").get_column("usd_brl")[-1]) if fx is not None and fx.height else None
    )

    securities = _read(silver / "cvm_securities.parquet")
    registry = _read(silver / "cvm_registry.parquet")
    dividends = _read(silver / "dividends.parquet")

    # Ticker -> CNPJ pela raiz de 4 letras do código (KLBN4 aparece na CVM só dentro
    # da unit KLBN11; a raiz "KLBN" liga as duas à mesma companhia).
    root_to_cnpj: dict[str, str] = {}
    if securities is not None:
        for cnpj, code in securities.select("cnpj", "code").iter_rows():
            root_to_cnpj.setdefault(str(code)[:4], str(cnpj))
    registry_by_cnpj: dict[str, tuple[date | None, str | None, str | None]] = {}
    if registry is not None:
        for cnpj, constitution, control, sector in registry.select(
            "cnpj", "constitution_date", "control", "sector"
        ).iter_rows():
            registry_by_cnpj[str(cnpj)] = (constitution, control, sector)
    years_by_symbol: dict[str, list[int]] = {}
    if dividends is not None:
        for symbol, years in (
            dividends.with_columns(pl.col("date").dt.year().cast(pl.Int32).alias("year"))
            .group_by("symbol")
            .agg(pl.col("year").unique().sort())
            .iter_rows()
        ):
            years_by_symbol[str(symbol)] = list(years)

    rows = []
    for symbol, market_cap, currency in profile.select(
        "symbol", "market_cap", "currency"
    ).iter_rows():
        ticker = _ticker_from_symbol(str(symbol))
        is_b3 = str(symbol).endswith(".SA")
        cnpj = root_to_cnpj.get(ticker[:4]) if is_b3 else None
        constitution, control, sector = registry_by_cnpj.get(cnpj or "", (None, None, None))
        cap_brl: float | None = market_cap
        if market_cap is not None and currency == "USD":
            cap_brl = market_cap * usd_brl if usd_brl else None
        rows.append(
            {
                "ticker": ticker,
                "cnpj": cnpj,
                "constitution_date": constitution,
                "control": control,
                "sector": sector,
                "market_cap_brl": cap_brl,
                "dividend_years": years_by_symbol.get(str(symbol), []),
            }
        )
    return pl.DataFrame(rows, schema=GOLD_STOCK_PROFILE)


def _reit_profile(monthly: pl.DataFrame) -> pl.DataFrame:
    """P/VP (via VP por cota), constância de distribuição e yield vs. segmento.

    Janela: os 48 meses até o último mês informado por qualquer fundo. O yield de 12
    meses é a soma do dividend yield mensal informado à CVM; a comparação usa a mediana
    dos FIIs listados do mesmo segmento que distribuíram nos 12 meses.
    """
    last_month = monthly.get_column("month").max()
    window_start = pl.lit(last_month).dt.offset_by(f"-{REIT_WINDOW_MONTHS - 1}mo")
    year_start = pl.lit(last_month).dt.offset_by("-11mo")
    window = monthly.filter(pl.col("month") >= window_start)

    per_fund = (
        window.sort("month")
        .group_by("cnpj")
        .agg(
            pl.col("isin").drop_nulls().last(),
            pl.col("segment").drop_nulls().last(),
            pl.col("listed").drop_nulls().last(),
            pl.col("month").last().alias("reference_month"),
            pl.col("book_value_per_share").drop_nulls().last(),
            (pl.col("dividend_yield") > 0).sum().cast(pl.Int32).alias("months_with_dividends"),
            pl.len().cast(pl.Int32).alias("months_observed"),
            pl.col("dividend_yield").filter(pl.col("month") >= year_start).sum().alias("_dy12"),
            (pl.col("month") >= year_start).sum().alias("_n12"),
        )
        .with_columns(
            pl.when(pl.col("_n12") >= 12)
            .then(pl.col("_dy12"))
            .otherwise(None)
            .alias("dividend_yield_12m")
        )
    )
    # Mediana só entre FIIs listados em bolsa que distribuíram no período: fundos
    # fechados ou que não pagam (yield 0) puxariam a referência para baixo.
    medians = (
        per_fund.filter(pl.col("listed") & (pl.col("dividend_yield_12m") > 0))
        .group_by("segment")
        .agg(pl.col("dividend_yield_12m").median().alias("segment_median_yield_12m"))
    )
    # Ticker = raiz do ISIN (BRMXRFCTF008 -> MXRF) + "11", padrão das cotas de FII.
    return (
        per_fund.join(medians, on="segment", how="left")
        .filter(pl.col("isin").is_not_null() & (pl.col("isin").str.len_chars() >= 6))
        .with_columns((pl.col("isin").str.slice(2, 4) + "11").alias("ticker"))
        .sort("reference_month")
        .unique(subset=["ticker"], keep="last")
        .select(GOLD_REIT_PROFILE.names())
        .sort("ticker")
    )


# ======================================================================= Pipeline


class FundamentalsPipeline(FundamentalsRefresher):
    """Baixa CVM e Yahoo, e reconstrói Silver e Gold de fundamentos."""

    def __init__(
        self,
        data_dir: Path,
        yahoo: YahooFundamentalsClient,
        cvm: CvmClient,
        today: Callable[[], date] = date.today,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._data_dir = data_dir
        self._yahoo = yahoo
        self._cvm = cvm
        self._today = today
        self._now = now

    def refresh(self, tickers: Sequence[Ticker]) -> dict[str, str]:
        today, ingested_at = self._today(), self._now()
        failures: dict[str, str] = {}
        self._ingest_cvm(today, ingested_at, failures)
        build_fundamentals_silver(self._data_dir)

        # FIIs têm fundamentos na CVM; ações vão ao Yahoo. Separação pela raiz do ISIN.
        reit_roots = self._reit_roots()
        for ticker in tickers:
            spec = resolve(ticker.symbol)
            if spec.source is not Source.YAHOO or spec.currency is PriceCurrency.INDEX:
                continue  # renda fixa, cripto e índices não têm checklist
            if ticker.symbol in {"BTC", "ETH"} or spec.source_symbol.endswith("-USD"):
                continue
            if ticker.symbol[:4] in reit_roots and ticker.symbol.endswith("11"):
                continue
            try:
                data = self._yahoo.fetch(spec.source_symbol)
            except SourceError as error:
                failures[ticker.symbol] = str(error)
                continue
            for source, frame, schema in (
                (Source.YAHOO_STATEMENTS, data.statements, STATEMENTS_BRONZE),
                (Source.YAHOO_PROFILE, data.profile, PROFILE_BRONZE),
                (Source.YAHOO_DIVIDENDS, data.dividends, DIVIDENDS_BRONZE),
            ):
                write_bronze(
                    frame, self._data_dir, source, schema, ingested_at, "symbol", spec.source_symbol
                )

        build_fundamentals_silver(self._data_dir)
        counts = build_fundamentals_gold(self._data_dir)
        logger.info("Fundamentos: %s; falhas: %s", counts, failures or "nenhuma")
        return failures

    def _reit_roots(self) -> set[str]:
        monthly = _read(_silver(self._data_dir) / "reit_monthly.parquet")
        if monthly is None:
            return set()
        return set(monthly.get_column("isin").drop_nulls().str.slice(2, 4).unique().to_list())

    def _ingest_cvm(self, today: date, ingested_at: datetime, failures: dict[str, str]) -> None:
        def save(
            source: Source, frame: pl.DataFrame, schema: pl.Schema, key: str, value: str
        ) -> None:
            write_bronze(frame, self._data_dir, source, schema, ingested_at, key, value)

        try:
            save(Source.CVM_REGISTRY, self._cvm.registry(), CVM_REGISTRY_BRONZE, "file", "all")
        except SourceError as error:
            failures["CVM cadastro"] = str(error)
        # O FCA do ano corrente pode ainda não existir em janeiro: tenta o anterior.
        for year in (today.year, today.year - 1):
            try:
                save(
                    Source.CVM_SECURITIES,
                    self._cvm.securities(year),
                    CVM_SECURITIES_BRONZE,
                    "file",
                    "all",
                )
                break
            except SourceError as error:
                failures[f"CVM FCA {year}"] = str(error)
        else:
            return
        failures.pop(f"CVM FCA {today.year}", None)
        for year in recent_years(today, REIT_YEARS):
            try:
                general, complement = self._cvm.reit_monthly(year)
            except SourceError as error:
                failures[f"CVM FII {year}"] = str(error)
                continue
            save(Source.CVM_REIT_GENERAL, general, CVM_REIT_GENERAL_BRONZE, "year", str(year))
            save(
                Source.CVM_REIT_COMPLEMENT,
                complement,
                CVM_REIT_COMPLEMENT_BRONZE,
                "year",
                str(year),
            )
