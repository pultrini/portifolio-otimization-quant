"""Schemas explícitos de cada camada do medalhão, validados na escrita."""

import polars as pl

UTC_TIMESTAMP = pl.Datetime("us", "UTC")

# Metadados de ingestão: as únicas colunas que a Bronze acrescenta ao dado da fonte.
INGESTION_COLUMNS = pl.Schema({"ingested_at": UTC_TIMESTAMP, "source": pl.String()})

# ---------------------------------------------------------------- Bronze (dado bruto)
YAHOO_BRONZE = pl.Schema(
    {
        "date": pl.Date,
        "symbol": pl.String,
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
        "adj_close": pl.Float64,
        "volume": pl.Float64,
        "dividends": pl.Float64,
        "stock_splits": pl.Float64,
    }
)

# O SGS devolve data e valor como texto ("19/11/2026", "0.050788"); ficam assim.
BCB_BRONZE = pl.Schema({"series_code": pl.String, "data": pl.String, "valor": pl.String})

# CSV do Tesouro com números em formato brasileiro ("3917,97"); ficam como texto.
TESOURO_BRONZE = pl.Schema(
    {
        "tipo_titulo": pl.String,
        "data_vencimento": pl.String,
        "data_base": pl.String,
        "taxa_compra_manha": pl.String,
        "taxa_venda_manha": pl.String,
        "pu_compra_manha": pl.String,
        "pu_venda_manha": pl.String,
        "pu_base_manha": pl.String,
    }
)

# --------------------------------------------------------------- Silver (dado limpo)
SILVER_PRICES = pl.Schema(
    {
        "date": pl.Date,
        "ticker": pl.String,
        "currency": pl.String,
        "close": pl.Float64,
        # Fechamento ajustado por proventos e desdobramentos: base de todos os retornos.
        "adj_close": pl.Float64,
        "dividends": pl.Float64,
        "stock_splits": pl.Float64,
        "source": pl.String,
    }
)

SILVER_RATES = pl.Schema(
    {"date": pl.Date, "series": pl.String, "value": pl.Float64, "source": pl.String}
)

# ------------------------------------------------------------- Gold (dado analítico)
GOLD_FX = pl.Schema({"date": pl.Date, "usd_brl": pl.Float64})

GOLD_PRICES = pl.Schema(
    {
        "date": pl.Date,
        "ticker": pl.String,
        "currency": pl.String,
        "price_native": pl.Float64,
        "price_brl": pl.Float64,
    }
)

GOLD_RETURNS = pl.Schema(
    {
        "date": pl.Date,
        "ticker": pl.String,
        "simple_return": pl.Float64,
        "log_return": pl.Float64,
    }
)

GOLD_VOLATILITY = pl.Schema({"date": pl.Date, "ticker": pl.String, "volatility_21d": pl.Float64})

GOLD_DRAWDOWNS = pl.Schema({"date": pl.Date, "ticker": pl.String, "drawdown": pl.Float64})

GOLD_COVARIANCE = pl.Schema(
    {"ticker_i": pl.String, "ticker_j": pl.String, "covariance": pl.Float64}
)


class SchemaMismatchError(ValueError):
    """O DataFrame não bate com o schema declarado da camada."""


def with_ingestion(schema: pl.Schema) -> pl.Schema:
    """Schema da fonte + colunas de ingestão (formato gravado na Bronze)."""
    return pl.Schema([*schema.items(), *INGESTION_COLUMNS.items()])


def validate(frame: pl.DataFrame, schema: pl.Schema, name: str) -> pl.DataFrame:
    """Garante colunas, ordem e tipos exatamente iguais ao schema antes de gravar.

    Raises:
        SchemaMismatchError: com as diferenças encontradas.
    """
    if frame.schema != schema:
        expected = dict(schema)
        actual = dict(frame.schema)
        diffs = [
            f"{col}: esperado {expected.get(col)}, obtido {actual.get(col)}"
            for col in dict.fromkeys([*expected, *actual])
            if expected.get(col) != actual.get(col)
        ]
        order = "" if diffs else f" (ordem: {list(actual)})"
        raise SchemaMismatchError(f"{name}: schema inválido{order}. " + "; ".join(diffs))
    return frame
