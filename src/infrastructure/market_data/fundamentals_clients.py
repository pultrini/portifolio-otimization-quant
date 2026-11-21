"""Clients de fundamentos: Yahoo Finance (balanços) e dados abertos da CVM.

Como os demais clients, só baixam e convertem para polars (camada Bronze). Nenhuma
regra de negócio aqui.
"""

from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
import polars as pl
import yfinance as yf

from infrastructure.data_engineering.schemas import (
    CVM_REGISTRY_BRONZE,
    CVM_REIT_COMPLEMENT_BRONZE,
    CVM_REIT_GENERAL_BRONZE,
    CVM_SECURITIES_BRONZE,
    DIVIDENDS_BRONZE,
    PROFILE_BRONZE,
    STATEMENTS_BRONZE,
)
from infrastructure.market_data.clients import HTTP_TIMEOUT, SourceError, _with_retries

CVM_BASE = "https://dados.cvm.gov.br/dados"
CVM_REGISTRY_URL = f"{CVM_BASE}/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
CVM_FCA_URL = f"{CVM_BASE}/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{{year}}.zip"
CVM_REIT_URL = f"{CVM_BASE}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{{year}}.zip"


@dataclass(frozen=True, slots=True)
class YahooFundamentals:
    statements: pl.DataFrame
    profile: pl.DataFrame
    dividends: pl.DataFrame


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class YahooFundamentalsClient:
    """Demonstrações anuais, valor de mercado e histórico de proventos."""

    def fetch(self, symbol: str) -> YahooFundamentals:
        ticker = yf.Ticker(symbol)
        rows: list[dict[str, Any]] = []
        # Fronteira com pandas: as tabelas do yfinance têm itens nas linhas e datas de
        # encerramento nas colunas. Só lemos células; nenhuma operação do pandas.
        for statement, table in (("income", ticker.financials), ("balance", ticker.balance_sheet)):
            if table is None or len(table) == 0:
                continue
            for period in table.columns:
                for item in table.index:
                    value = _finite(table.at[item, period])
                    if value is not None:
                        rows.append(
                            {
                                "symbol": symbol,
                                "statement": statement,
                                "item": str(item),
                                "period_end": period.date(),
                                "value": value,
                            }
                        )
        try:
            info = ticker.fast_info
            market_cap = _finite(info.get("marketCap"))
            currency = info.get("currency")
        except Exception as error:  # yfinance levanta erros variados por ativo
            raise SourceError(f"Yahoo sem perfil para {symbol}: {error}") from error
        dividends = ticker.dividends
        dividend_rows = [
            {"symbol": symbol, "date": moment.date(), "amount": float(amount)}
            for moment, amount in zip(dividends.index, dividends.values, strict=True)
            if _finite(amount)
        ]
        if not rows and market_cap is None and not dividend_rows:
            raise SourceError(f"Yahoo sem fundamentos para {symbol}.")
        return YahooFundamentals(
            statements=pl.DataFrame(rows, schema=STATEMENTS_BRONZE),
            profile=pl.DataFrame(
                [{"symbol": symbol, "market_cap": market_cap, "currency": currency}],
                schema=PROFILE_BRONZE,
            ),
            dividends=pl.DataFrame(dividend_rows, schema=DIVIDENDS_BRONZE),
        )


def _download(url: str) -> bytes:
    def call() -> bytes:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            response = client.get(url)
            if response.status_code == 404:
                raise SourceError(f"CVM sem arquivo: {url}")
            response.raise_for_status()
            return response.content

    return _with_retries(f"CVM {url.rsplit('/', 1)[-1]}", call)


def _read_cvm_csv(content: bytes, schema: pl.Schema) -> pl.DataFrame:
    """CSV da CVM: separador ';' e codificação latin-1; colunas como texto."""
    text = content.decode("latin-1")
    frame = pl.read_csv(io.StringIO(text), separator=";", infer_schema=False, quote_char='"')
    return frame.select(schema.names())


def _zip_member(content: bytes, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return archive.read(name)


class CvmClient:
    """Dados abertos da CVM: cadastro de companhias, FCA e informes mensais de FII."""

    def registry(self) -> pl.DataFrame:
        return _read_cvm_csv(_download(CVM_REGISTRY_URL), CVM_REGISTRY_BRONZE)

    def securities(self, year: int) -> pl.DataFrame:
        """Valores mobiliários do FCA (liga código de negociação ao CNPJ)."""
        content = _download(CVM_FCA_URL.format(year=year))
        member = f"fca_cia_aberta_valor_mobiliario_{year}.csv"
        return _read_cvm_csv(_zip_member(content, member), CVM_SECURITIES_BRONZE)

    def reit_monthly(self, year: int) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Informes mensais de FII do ano: (geral, complemento)."""
        content = _download(CVM_REIT_URL.format(year=year))
        general = _read_cvm_csv(
            _zip_member(content, f"inf_mensal_fii_geral_{year}.csv"), CVM_REIT_GENERAL_BRONZE
        )
        complement = _read_cvm_csv(
            _zip_member(content, f"inf_mensal_fii_complemento_{year}.csv"),
            CVM_REIT_COMPLEMENT_BRONZE,
        )
        return general, complement


def recent_years(today: date, count: int) -> list[int]:
    """Anos dos arquivos anuais da CVM a baixar, do mais antigo ao atual."""
    return list(range(today.year - count + 1, today.year + 1))
