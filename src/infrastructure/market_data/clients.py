"""Clients das fontes externas. Devolvem dados brutos em polars (camada Bronze).

Cada client só busca e converte para DataFrame; não limpa nem interpreta valores.
Toda limpeza acontece na Silver, para que a Bronze guarde o que a fonte entregou.
"""

from __future__ import annotations

import io
import logging
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Protocol

import httpx
import polars as pl
import yfinance as yf

from infrastructure.data_engineering.schemas import BCB_BRONZE, TESOURO_BRONZE, YAHOO_BRONZE

logger = logging.getLogger(__name__)

BCB_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
TESOURO_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"
)

# O SGS limita consultas de séries diárias a 10 anos; usa janelas um pouco menores.
BCB_MAX_WINDOW = timedelta(days=365 * 9)
HTTP_TIMEOUT = httpx.Timeout(60.0)
RETRIES = 3


class SourceError(RuntimeError):
    """A fonte não respondeu ou não tem dados para o código pedido."""


class YahooClientProtocol(Protocol):
    def fetch(self, symbol: str, start: date) -> pl.DataFrame: ...


class BcbClientProtocol(Protocol):
    def fetch(self, code: str, start: date, end: date) -> pl.DataFrame: ...


class TesouroClientProtocol(Protocol):
    def fetch(self) -> pl.DataFrame: ...


def _with_retries[T](action: str, call: Callable[[], T]) -> T:
    """Executa `call()` com até 3 tentativas e espera crescente (1s, 2s)."""
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            result: T = call()
            return result
        except (httpx.HTTPError, SourceError) as error:
            last_error = error
            logger.warning("%s falhou (tentativa %d/%d): %s", action, attempt, RETRIES, error)
            if attempt < RETRIES:
                time.sleep(attempt)
    raise SourceError(f"{action}: {last_error}") from last_error


class YahooFinanceClient:
    """Cotações diárias, proventos e desdobramentos via yfinance."""

    def fetch(self, symbol: str, start: date) -> pl.DataFrame:
        """Baixa o histórico diário de um código desde `start`.

        `auto_adjust=False` mantém o fechamento original e o ajustado ("Adj Close",
        corrigido por proventos e desdobramentos) lado a lado; `actions=True` traz as
        colunas de dividendos e desdobramentos.
        """
        raw = yf.download(
            symbol,
            start=start.isoformat(),
            auto_adjust=False,
            actions=True,
            progress=False,
            multi_level_index=False,
            threads=False,
        )
        if raw is None or len(raw) == 0:
            raise SourceError(f"Yahoo sem dados para {symbol}.")
        # Fronteira com pandas: o yfinance só devolve pandas. Converte imediatamente e
        # não usa nenhuma operação do pandas além de expor o índice como coluna.
        frame = pl.from_pandas(raw.reset_index())
        renamed = frame.rename(
            {
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
                "Dividends": "dividends",
                "Stock Splits": "stock_splits",
            },
            strict=False,
        )
        # Colunas que o Yahoo omite em alguns ativos (ex.: índices sem proventos).
        for column in ("dividends", "stock_splits", "volume"):
            if column not in renamed.columns:
                renamed = renamed.with_columns(pl.lit(0.0).alias(column))
        return renamed.select(
            pl.col("date").cast(pl.Date),
            pl.lit(symbol).alias("symbol"),
            *[
                pl.col(c).cast(pl.Float64)
                for c in YAHOO_BRONZE.names()
                if c not in {"date", "symbol"}
            ],
        )


class BcbSgsClient:
    """Séries temporais do Sistema Gerenciador de Séries (SGS) do Banco Central."""

    def fetch(self, code: str, start: date, end: date) -> pl.DataFrame:
        """Baixa a série `code` em janelas de até 9 anos.

        Mantém `data` e `valor` como texto, exatamente como a API devolve.
        """
        frames: list[pl.DataFrame] = []
        window_start = start
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            while window_start <= end:
                window_end = min(window_start + BCB_MAX_WINDOW, end)
                params = {
                    "formato": "json",
                    "dataInicial": window_start.strftime("%d/%m/%Y"),
                    "dataFinal": window_end.strftime("%d/%m/%Y"),
                }

                def call(params: dict[str, str] = params) -> list[dict[str, str]]:
                    response = client.get(BCB_URL.format(code=code), params=params)
                    # 404 no SGS significa "sem valores no período" (ex.: feriados).
                    if response.status_code == 404:
                        return []
                    response.raise_for_status()
                    payload: list[dict[str, str]] = response.json()
                    return payload

                rows = _with_retries(f"SGS {code} {params['dataInicial']}", call)
                if rows:
                    frames.append(
                        pl.DataFrame(
                            {
                                "series_code": [code] * len(rows),
                                "data": [r["data"] for r in rows],
                                "valor": [r["valor"] for r in rows],
                            },
                            schema=BCB_BRONZE,
                        )
                    )
                window_start = window_end + timedelta(days=1)
        if not frames:
            raise SourceError(f"SGS sem dados para a série {code}.")
        return pl.concat(frames)


class TesouroDiretoClient:
    """Preços e taxas históricos de todos os títulos do Tesouro Direto (CSV oficial)."""

    def fetch(self) -> pl.DataFrame:
        """Baixa o CSV completo (~15 MB). Todas as colunas ficam como texto."""

        def call() -> bytes:
            with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
                response = client.get(TESOURO_URL)
                response.raise_for_status()
                return response.content

        content: bytes = _with_retries("Tesouro Direto CSV", call)
        frame = pl.read_csv(
            io.BytesIO(content), separator=";", infer_schema=False, encoding="utf8-lossy"
        )
        renamed = frame.rename(
            {
                "Tipo Titulo": "tipo_titulo",
                "Data Vencimento": "data_vencimento",
                "Data Base": "data_base",
                "Taxa Compra Manha": "taxa_compra_manha",
                "Taxa Venda Manha": "taxa_venda_manha",
                "PU Compra Manha": "pu_compra_manha",
                "PU Venda Manha": "pu_venda_manha",
                "PU Base Manha": "pu_base_manha",
            }
        )
        return renamed.select(TESOURO_BRONZE.names())
