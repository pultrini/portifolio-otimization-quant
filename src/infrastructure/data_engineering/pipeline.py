"""Orquestração do pipeline medalhão e ponto de entrada de linha de comando.

Uso:
    uv run python -m infrastructure.data_engineering.pipeline --tickers EGIE3 WEGE3 BTC
    uv run python -m infrastructure.data_engineering.pipeline --portfolio-file carteira.txt
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from domain.repositories.market_data_repository import MarketDataRefresher, RefreshReport
from domain.value_objects.ticker import Ticker
from infrastructure.config import Settings
from infrastructure.data_engineering.layers import (
    build_gold,
    build_silver_prices,
    build_silver_rates,
    build_silver_treasury,
    write_bronze,
)
from infrastructure.data_engineering.schemas import BCB_BRONZE, TESOURO_BRONZE, YAHOO_BRONZE
from infrastructure.market_data.clients import (
    BcbClientProtocol,
    BcbSgsClient,
    SourceError,
    TesouroClientProtocol,
    TesouroDiretoClient,
    YahooClientProtocol,
    YahooFinanceClient,
)
from infrastructure.market_data.instruments import (
    REFERENCE_TICKERS,
    SGS_PTAX_SELL,
    SGS_SELIC,
    InstrumentSpec,
    PriceCurrency,
    Source,
    resolve,
)

logger = logging.getLogger(__name__)

# Taxas viram índices acumulados; buscá-las sempre desde a mesma data mantém a base do
# índice fixa entre execuções (senão o "preço" do CDI mudaria a cada atualização).
RATE_HISTORY_START = date(2000, 1, 1)

# Nome da partição de cada fonte na Bronze (um arquivo por código e dia de ingestão).
_PARTITION_KEYS = {Source.YAHOO: "symbol", Source.BCB: "series_code", Source.TESOURO: "file"}


class MedallionPipeline(MarketDataRefresher):
    """Bronze (download) -> Silver (limpeza) -> Gold (séries analíticas)."""

    def __init__(
        self,
        data_dir: Path,
        yahoo: YahooClientProtocol,
        bcb: BcbClientProtocol,
        tesouro: TesouroClientProtocol,
        today: Callable[[], date] = date.today,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._data_dir = data_dir
        self._yahoo = yahoo
        self._bcb = bcb
        self._tesouro = tesouro
        self._today = today
        self._now = now

    def refresh(self, tickers: Sequence[Ticker], years: int) -> RefreshReport:
        """Baixa os tickers pedidos e as séries de referência e reconstrói Silver e Gold.

        Uma fonte que falha não interrompe as outras: o ticker entra em
        `failed_tickers` e o resto segue.
        """
        today = self._today()
        start = today - timedelta(days=365 * years)
        ingested_at = self._now()
        requested = {t.symbol for t in tickers}
        specs = {resolve(symbol) for symbol in requested | set(REFERENCE_TICKERS)}
        failures: dict[str, str] = {}
        bronze_rows = 0

        for spec in sorted((s for s in specs if s.source is Source.YAHOO), key=lambda s: s.ticker):
            spec_start = RATE_HISTORY_START if spec.currency is PriceCurrency.INDEX else start
            bronze_rows += self._ingest(
                failures,
                spec,
                lambda spec=spec, spec_start=spec_start: self._yahoo.fetch(  # type: ignore[misc]
                    spec.source_symbol, spec_start
                ),
                YAHOO_BRONZE,
                ingested_at,
            )

        # Séries do Banco Central: CDI sempre desde 2000 (índice com base fixa); PTAX e
        # Selic no mesmo horizonte dos preços.
        bcb_series = [(spec, RATE_HISTORY_START) for spec in specs if spec.source is Source.BCB] + [
            (InstrumentSpec("PTAX", Source.BCB, SGS_PTAX_SELL, PriceCurrency.INDEX), start),
            (InstrumentSpec("SELIC", Source.BCB, SGS_SELIC, PriceCurrency.INDEX), start),
        ]
        for spec, spec_start in bcb_series:
            bronze_rows += self._ingest(
                failures,
                spec,
                lambda spec=spec, spec_start=spec_start: self._bcb.fetch(  # type: ignore[misc]
                    spec.source_symbol, spec_start, today
                ),
                BCB_BRONZE,
                ingested_at,
            )

        tesouro_specs = [s for s in specs if s.source is Source.TESOURO]
        if tesouro_specs:
            # Um único CSV traz todos os títulos; a partição usa uma chave fixa.
            all_titles = InstrumentSpec("TESOURO", Source.TESOURO, "all", PriceCurrency.BRL)
            bronze_rows += self._ingest(
                failures, all_titles, self._tesouro.fetch, TESOURO_BRONZE, ingested_at
            )

        silver_rows = (
            build_silver_prices(self._data_dir)
            + build_silver_rates(self._data_dir)
            + build_silver_treasury(self._data_dir)
        )
        gold_counts = build_gold(self._data_dir)

        # Ticker pedido que não chegou à Gold (ex.: título do Tesouro inexistente).
        available = set(
            pl.scan_parquet(self._data_dir / "gold" / "prices.parquet")
            .select("ticker")
            .unique()
            .collect()
            .get_column("ticker")
            .to_list()
        )
        for symbol in sorted(requested - available):
            failures.setdefault(symbol, "sem cotação após o processamento")

        report = RefreshReport(
            rows_by_layer={
                "bronze": bronze_rows,
                "silver": silver_rows,
                "gold": sum(gold_counts.values()),
            },
            failed_tickers=failures,
        )
        logger.info(
            "Pipeline concluído: %s; falhas: %s", report.rows_by_layer, failures or "nenhuma"
        )
        return report

    def _ingest(
        self,
        failures: dict[str, str],
        spec: InstrumentSpec,
        fetch: Callable[[], pl.DataFrame],
        schema: pl.Schema,
        ingested_at: datetime,
    ) -> int:
        """Baixa uma série e grava na Bronze; qualquer falha da fonte vira `failures`.

        A captura é ampla de propósito: bibliotecas de terceiros (yfinance, httpx) lançam
        exceções próprias (limite de requisições, JSON inválido...). Uma fonte instável
        não pode derrubar o pipeline: a Silver usa o último snapshot bom da Bronze.
        """
        try:
            frame = fetch()
        except SourceError as error:
            logger.warning("Falha ao baixar %s: %s", spec.ticker, error)
            failures[spec.ticker] = str(error)
            return 0
        except Exception as error:
            logger.exception("Erro inesperado ao baixar %s", spec.ticker)
            failures[spec.ticker] = f"{type(error).__name__}: {error}"
            return 0
        key = _PARTITION_KEYS[spec.source]
        return write_bronze(
            frame, self._data_dir, spec.source, schema, ingested_at, key, spec.source_symbol
        )


def build_default_pipeline(settings: Settings) -> MedallionPipeline:
    """Pipeline com os clients reais (Yahoo, Banco Central, Tesouro Direto)."""
    return MedallionPipeline(
        settings.data_dir, YahooFinanceClient(), BcbSgsClient(), TesouroDiretoClient()
    )


def _tickers_from_file(path: Path) -> list[str]:
    """Primeiro token de cada linha não vazia e não comentada (formato da importação)."""
    tickers: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            tickers.append(stripped.split()[0])
    return tickers


def main(argv: Sequence[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description="Pipeline medalhão de dados de mercado.")
    parser.add_argument(
        "--tickers", nargs="*", default=[], help="Tickers canônicos (EGIE3 BTC CDI)."
    )
    parser.add_argument("--portfolio-file", type=Path, help="Arquivo no formato da importação.")
    parser.add_argument("--years", type=int, default=settings.market_history_years)
    args = parser.parse_args(argv)

    logging.basicConfig(level=settings.log_level.upper(), format="%(levelname)s %(message)s")
    symbols = list(args.tickers)
    if args.portfolio_file:
        symbols += _tickers_from_file(args.portfolio_file)
    tickers = [Ticker.parse(s) for s in dict.fromkeys(symbols)]

    report = build_default_pipeline(settings).refresh(tickers, args.years)
    for ticker, reason in report.failed_tickers.items():
        logger.warning("%s: %s", ticker, reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
