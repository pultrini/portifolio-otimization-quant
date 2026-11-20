"""Transformações Bronze -> Silver -> Gold em polars.

Layout em disco (`data_dir`):
    bronze/<fonte>/ingestion_date=AAAA-MM-DD/<chave>=<valor>/data.parquet
    silver/prices.parquet, silver/rates.parquet
    gold/fx.parquet, prices.parquet, returns.parquet, volatility.parquet,
         drawdowns.parquet, covariance.parquet

Idempotência:
    - Bronze: um arquivo por fonte, dia de ingestão e código. Rodar de novo no mesmo
      dia sobrescreve o mesmo arquivo; dias diferentes viram snapshots separados.
    - Silver e Gold: reconstruídas do zero a partir da Bronze a cada execução e gravadas
      por cima. Reprocessar nunca duplica linhas.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import cast

import numpy as np
import polars as pl

from domain.services.asset_classification import infer_asset_class
from domain.value_objects.ticker import Ticker
from infrastructure.data_engineering.schemas import (
    BCB_BRONZE,
    GOLD_COVARIANCE,
    GOLD_DRAWDOWNS,
    GOLD_FX,
    GOLD_PRICES,
    GOLD_RETURNS,
    GOLD_VOLATILITY,
    SILVER_PRICES,
    SILVER_RATES,
    TESOURO_BRONZE,
    YAHOO_BRONZE,
    validate,
    with_ingestion,
)
from infrastructure.market_data.instruments import (
    SGS_CDI,
    SGS_PTAX_SELL,
    SGS_SELIC,
    TESOURO_TYPES,
    PriceCurrency,
    Source,
    canonical_from_yahoo,
    yahoo_currency,
)

# Nomes das séries de taxa na Silver.
CDI_SERIES = "CDI"
SELIC_SERIES = "SELIC"
PTAX_SERIES = "PTAX_USD_BRL"
TBILL_SERIES = "TBILL3M"
_SGS_SERIES_NAMES = {SGS_CDI: CDI_SERIES, SGS_SELIC: SELIC_SERIES, SGS_PTAX_SELL: PTAX_SERIES}
_IRX_SYMBOL = "^IRX"

# Janela da volatilidade móvel (~1 mês de pregões) e do histórico da covariância (~3 anos).
VOLATILITY_WINDOW = 21
COVARIANCE_WINDOW = timedelta(days=3 * 365)
# Folga para considerar que um ativo cobre a janela (feriados, fins de semana).
COVERAGE_SLACK = timedelta(days=10)
PRICE_DECIMALS = 6


# ======================================================================== Bronze


def bronze_path(data_dir: Path, source: Source, ingested_on: date, key: str, value: str) -> Path:
    return (
        data_dir
        / "bronze"
        / source.value
        / f"ingestion_date={ingested_on.isoformat()}"
        / f"{key}={value}"
        / "data.parquet"
    )


def write_bronze(
    frame: pl.DataFrame,
    data_dir: Path,
    source: Source,
    schema: pl.Schema,
    ingested_at: datetime,
    key: str,
    value: str,
) -> int:
    """Grava o dado bruto com `ingested_at` e `source`, sem mexer nos valores.

    Returns:
        Quantidade de linhas gravadas.
    """
    stamped = frame.with_columns(
        pl.lit(ingested_at, dtype=pl.Datetime("us", "UTC")).alias("ingested_at"),
        pl.lit(source.value).alias("source"),
    )
    validate(stamped, with_ingestion(schema), f"bronze/{source.value}")
    path = bronze_path(data_dir, source, ingested_at.date(), key, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped.write_parquet(path)
    return stamped.height


def _scan_bronze(data_dir: Path, source: Source) -> pl.LazyFrame | None:
    root = data_dir / "bronze" / source.value
    if not any(root.rglob("*.parquet")):
        return None
    # hive_partitioning=False: a chave da partição já está dentro do arquivo; ler o
    # caminho só criaria colunas duplicadas com tipos inferidos.
    return pl.scan_parquet(root / "**" / "*.parquet", hive_partitioning=False)


def _latest_snapshot(frame: pl.LazyFrame, key: str) -> pl.LazyFrame:
    """Mantém, para cada `key`, só as linhas da ingestão mais recente.

    Para preços isso é obrigatório: o Yahoo reajusta todo o histórico a cada provento,
    então misturar snapshots de dias diferentes geraria saltos falsos na série.
    """
    return frame.filter(pl.col("ingested_at") == pl.col("ingested_at").max().over(key))


def _br_number(column: str) -> pl.Expr:
    """Texto no formato brasileiro ("3.917,97") para Float64."""
    return (
        pl.col(column)
        .str.replace_all(".", "", literal=True)
        .str.replace(",", ".", literal=True)
        .cast(pl.Float64, strict=False)
    )


# ======================================================================== Silver


def build_silver_prices(data_dir: Path) -> int:
    """Une Yahoo e Tesouro em uma tabela de preços diários limpa.

    Regras: só o snapshot mais recente de cada código; sem preço nulo ou não positivo
    (preços de ativos nunca recebem forward-fill); uma linha por ticker e data.
    """
    parts: list[pl.DataFrame] = []

    yahoo = _scan_bronze(data_dir, Source.YAHOO)
    if yahoo is not None:
        latest = (
            _latest_snapshot(yahoo.select(with_ingestion(YAHOO_BRONZE).names()), "symbol")
            # ^IRX é taxa de juros, não preço: vai para a tabela de taxas.
            .filter(pl.col("symbol") != _IRX_SYMBOL)
            .collect()
        )
        symbols = latest.get_column("symbol").unique().to_list()
        tickers = {s: canonical_from_yahoo(s) for s in symbols}
        currencies = {s: yahoo_currency(s).value for s in symbols}
        parts.append(
            latest.select(
                "date",
                pl.col("symbol").replace_strict(tickers, return_dtype=pl.String).alias("ticker"),
                pl.col("symbol")
                .replace_strict(currencies, return_dtype=pl.String)
                .alias("currency"),
                # O Yahoo entrega float32 (25.32 chega como 25.31999969); 6 casas
                # removem o resíduo binário sem afetar nenhum preço real.
                pl.col("close").round(PRICE_DECIMALS),
                pl.col("adj_close").round(PRICE_DECIMALS),
                pl.col("dividends").fill_null(0.0),
                pl.col("stock_splits").fill_null(0.0),
                "source",
            )
        )

    tesouro = _scan_bronze(data_dir, Source.TESOURO)
    if tesouro is not None:
        prefix_by_type = {name: prefix for prefix, name in TESOURO_TYPES.items()}
        latest_tesouro = _latest_snapshot(
            tesouro.select(with_ingestion(TESOURO_BRONZE).names()).with_columns(
                pl.lit("all").alias("_key")
            ),
            "_key",
        )
        pu = _br_number("pu_base_manha")
        parts.append(
            latest_tesouro.filter(pl.col("tipo_titulo").is_in(list(prefix_by_type)))
            .select(
                pl.col("data_base").str.to_date("%d/%m/%Y").alias("date"),
                (
                    pl.col("tipo_titulo").replace_strict(prefix_by_type, return_dtype=pl.String)
                    + "-"
                    + pl.col("data_vencimento").str.slice(6, 4)
                ).alias("ticker"),
                pl.lit(PriceCurrency.BRL.value).alias("currency"),
                pu.alias("close"),
                # PU de títulos com cupom cai no pagamento do juro semestral; sem o
                # valor do cupom no CSV, o PU entra como está (limitação documentada).
                pu.alias("adj_close"),
                pl.lit(0.0).alias("dividends"),
                pl.lit(0.0).alias("stock_splits"),
                "source",
                pl.col("data_vencimento").str.to_date("%d/%m/%Y").alias("_maturity"),
            )
            .sort("ticker", "date", "_maturity")
            # Dois vencimentos no mesmo ano viram o mesmo ticker: fica o primeiro.
            .unique(subset=["ticker", "date"], keep="first", maintain_order=True)
            .drop("_maturity")
            .collect()
        )

    if not parts:
        return _write(pl.DataFrame(schema=SILVER_PRICES), data_dir / "silver" / "prices.parquet")

    prices = (
        pl.concat(parts)
        .filter(pl.col("adj_close").is_not_null() & (pl.col("adj_close") > 0))
        .filter(pl.col("close").is_not_null() & (pl.col("close") > 0))
        .unique(subset=["ticker", "date"], keep="last", maintain_order=True)
        .sort("ticker", "date")
        .select(SILVER_PRICES.names())
    )
    validate(prices, SILVER_PRICES, "silver/prices")
    return _write(prices, data_dir / "silver" / "prices.parquet")


def build_silver_rates(data_dir: Path) -> int:
    """Taxas e câmbio: CDI, Selic e PTAX (SGS) e T-Bill 3M (^IRX), como Float64."""
    parts: list[pl.DataFrame] = []

    bcb = _scan_bronze(data_dir, Source.BCB)
    if bcb is not None:
        parts.append(
            _latest_snapshot(bcb.select(with_ingestion(BCB_BRONZE).names()), "series_code")
            .filter(pl.col("series_code").is_in(list(_SGS_SERIES_NAMES)))
            .select(
                pl.col("data").str.to_date("%d/%m/%Y").alias("date"),
                pl.col("series_code")
                .replace_strict(_SGS_SERIES_NAMES, return_dtype=pl.String)
                .alias("series"),
                pl.col("valor").cast(pl.Float64, strict=False).alias("value"),
                "source",
            )
            .collect()
        )

    yahoo = _scan_bronze(data_dir, Source.YAHOO)
    if yahoo is not None:
        parts.append(
            _latest_snapshot(
                yahoo.select(with_ingestion(YAHOO_BRONZE).names()).filter(
                    pl.col("symbol") == _IRX_SYMBOL
                ),
                "symbol",
            )
            .select(
                "date",
                pl.lit(TBILL_SERIES).alias("series"),
                pl.col("close").alias("value"),
                "source",
            )
            .collect()
        )

    rates = pl.concat(parts) if parts else pl.DataFrame(schema=SILVER_RATES)
    rates = (
        rates.filter(pl.col("value").is_not_null())
        .unique(subset=["series", "date"], keep="last", maintain_order=True)
        .sort("series", "date")
        .select(SILVER_RATES.names())
    )
    validate(rates, SILVER_RATES, "silver/rates")
    return _write(rates, data_dir / "silver" / "rates.parquet")


# ========================================================================== Gold


def _rate_index(rates: pl.DataFrame, series: str, ticker: str) -> pl.DataFrame:
    """Transforma uma série de taxa em índice acumulado (preço sintético).

    CDI (SGS 12, % ao dia útil): o valor publicado na data d remunera de d para d+1,
        então índice_d = Π_{s<d} (1 + r_s/100). O índice parte de 1 na primeira data.
    T-Bill (^IRX, % ao ano): rende de uma observação à seguinte pelos dias corridos,
        fator = (1 + y/100)^(dias/365).

    A base é sempre a primeira data baixada; por isso o pipeline busca as taxas desde
    uma data fixa (2000), para o nível do índice não mudar entre execuções.
    """
    frame = rates.filter(pl.col("series") == series).sort("date")
    if frame.is_empty():
        return pl.DataFrame(schema=GOLD_PRICES)
    if series == CDI_SERIES:
        growth = 1.0 + pl.col("value") / 100.0
    else:
        days = (pl.col("date").shift(-1) - pl.col("date")).dt.total_days()
        growth = (1.0 + pl.col("value") / 100.0).pow(days.cast(pl.Float64) / 365.0)
    index = growth.cum_prod().shift(1, fill_value=1.0)
    return frame.select(
        "date",
        pl.lit(ticker).alias("ticker"),
        pl.lit(PriceCurrency.INDEX.value).alias("currency"),
        index.alias("price_native"),
        index.alias("price_brl"),
    )


def build_gold(data_dir: Path) -> dict[str, int]:
    """Gera as tabelas analíticas a partir da Silver.

    Returns:
        Linhas gravadas por tabela.
    """
    silver_prices = pl.read_parquet(data_dir / "silver" / "prices.parquet")
    rates = pl.read_parquet(data_dir / "silver" / "rates.parquet")
    gold = data_dir / "gold"
    counts: dict[str, int] = {}

    # Câmbio: PTAX só existe em dias úteis no Brasil. Para converter ativos que negociam
    # em outros dias (cripto, bolsa americana em feriado brasileiro) usa a última PTAX
    # conhecida. Forward-fill é permitido aqui porque câmbio é série de taxa.
    ptax = rates.filter(pl.col("series") == PTAX_SERIES).select("date", "value").sort("date")
    if ptax.is_empty():
        fx = pl.DataFrame(schema=GOLD_FX)
    else:
        # O calendário vai da primeira PTAX até a última data com preço (ou PTAX),
        # para cobrir fins de semana recentes de cripto.
        first_day = cast(date, ptax.get_column("date").min())
        last_ptax = cast(date, ptax.get_column("date").max())
        last_price = cast(date | None, silver_prices.get_column("date").max())
        last_day = max(last_ptax, last_price or last_ptax)
        calendar = pl.DataFrame({"date": pl.date_range(first_day, last_day, "1d", eager=True)})
        fx = (
            calendar.join(ptax, on="date", how="left")
            .with_columns(pl.col("value").forward_fill().alias("usd_brl"))
            .select("date", "usd_brl")
        )
    counts["fx"] = _write(validate(fx, GOLD_FX, "gold/fx"), gold / "fx.parquet")

    # Preços em BRL: USD x PTAX da data; BRL como está. Ativos em USD sem PTAX naquela
    # data (antes do início da série) ficam de fora em vez de virar preço errado.
    converted = (
        silver_prices.join(fx, on="date", how="left")
        .with_columns(
            pl.when(pl.col("currency") == PriceCurrency.USD.value)
            .then(pl.col("adj_close") * pl.col("usd_brl"))
            .otherwise(pl.col("adj_close"))
            .alias("price_brl")
        )
        .filter(pl.col("price_brl").is_not_null())
        .select(
            "date", "ticker", "currency", pl.col("adj_close").alias("price_native"), "price_brl"
        )
    )
    prices = (
        pl.concat(
            [
                converted,
                _rate_index(rates, CDI_SERIES, CDI_SERIES),
                _rate_index(rates, TBILL_SERIES, TBILL_SERIES),
            ]
        )
        .sort("ticker", "date")
        .select(GOLD_PRICES.names())
    )
    counts["prices"] = _write(validate(prices, GOLD_PRICES, "gold/prices"), gold / "prices.parquet")

    # Retornos no calendário de cada ativo:
    #   simples = P_t / P_{t-1} - 1 ; log = ln(P_t / P_{t-1})
    ratio = pl.col("price_brl") / pl.col("price_brl").shift(1).over("ticker")
    returns = (
        prices.select(
            "date",
            "ticker",
            (ratio - 1.0).alias("simple_return"),
            ratio.log().alias("log_return"),
        )
        .drop_nulls()
        .select(GOLD_RETURNS.names())
    )
    counts["returns"] = _write(
        validate(returns, GOLD_RETURNS, "gold/returns"), gold / "returns.parquet"
    )

    # Volatilidade móvel anualizada: desvio-padrão de 21 retornos x sqrt(dias por ano),
    # com 365 para cripto e 252 para o resto (CLAUDE.md 5.2).
    tickers = returns.get_column("ticker").unique().to_list()
    periods = {t: float(_periods_per_year(t)) for t in tickers}
    volatility = (
        returns.with_columns(
            (
                pl.col("simple_return").rolling_std(VOLATILITY_WINDOW).over("ticker")
                * pl.col("ticker").replace_strict(periods, return_dtype=pl.Float64).sqrt()
            ).alias("volatility_21d")
        )
        .drop_nulls("volatility_21d")
        .select(GOLD_VOLATILITY.names())
    )
    counts["volatility"] = _write(
        validate(volatility, GOLD_VOLATILITY, "gold/volatility"), gold / "volatility.parquet"
    )

    # Drawdown: queda em relação ao pico anterior, P_t / max(P_0..P_t) - 1 (<= 0).
    drawdowns = prices.select(
        "date",
        "ticker",
        (pl.col("price_brl") / pl.col("price_brl").cum_max().over("ticker") - 1.0).alias(
            "drawdown"
        ),
    )
    counts["drawdowns"] = _write(
        validate(drawdowns, GOLD_DRAWDOWNS, "gold/drawdowns"), gold / "drawdowns.parquet"
    )

    covariance = _covariance(returns)
    counts["covariance"] = _write(
        validate(covariance, GOLD_COVARIANCE, "gold/covariance"), gold / "covariance.parquet"
    )
    return counts


def _periods_per_year(ticker: str) -> int:
    try:
        return infer_asset_class(Ticker(ticker)).periods_per_year
    except ValueError:
        return 252


def _covariance(returns: pl.DataFrame) -> pl.DataFrame:
    """Covariância anualizada (x252) dos retornos dos últimos ~3 anos.

    Entram só ativos com histórico cobrindo a janela inteira: um título já vencido ou
    um ativo listado há pouco tempo zeraria as datas em comum de todos os outros.
    Índices de taxa (CDI, T-Bill) ficam de fora: são a taxa livre de risco, não ativos.
    """
    assets = returns.filter(~pl.col("ticker").is_in([CDI_SERIES, TBILL_SERIES]))
    if assets.is_empty():
        return pl.DataFrame(schema=GOLD_COVARIANCE)
    last_date = cast(date, assets.get_column("date").max())
    window_start = last_date - COVARIANCE_WINDOW
    window = assets.filter(pl.col("date") >= window_start)
    covering = (
        window.group_by("ticker")
        .agg(pl.col("date").min().alias("first"), pl.col("date").max().alias("last"))
        .filter(
            (pl.col("first") <= window_start + COVERAGE_SLACK)
            & (pl.col("last") >= last_date - COVERAGE_SLACK)
        )
        .get_column("ticker")
        .sort()
        .to_list()
    )
    wide = (
        window.filter(pl.col("ticker").is_in(covering))
        .pivot(on="ticker", index="date", values="simple_return")
        .drop_nulls()
        .sort("date")
    )
    names = [c for c in wide.columns if c != "date"]
    if wide.height < 2 or not names:
        return pl.DataFrame(schema=GOLD_COVARIANCE)
    matrix = np.atleast_2d(np.cov(wide.select(names).to_numpy(), rowvar=False)) * 252
    return pl.DataFrame(
        {
            "ticker_i": [a for a in names for _ in names],
            "ticker_j": [b for _ in names for b in names],
            "covariance": [
                float(matrix[i, j]) for i in range(len(names)) for j in range(len(names))
            ],
        },
        schema=GOLD_COVARIANCE,
    )


def _write(frame: pl.DataFrame, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return frame.height
