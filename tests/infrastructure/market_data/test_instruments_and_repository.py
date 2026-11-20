"""Testes da tradução de tickers e da leitura da Gold."""

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from domain.exceptions import MissingMarketDataError
from domain.value_objects.ticker import Ticker
from infrastructure.data_engineering.layers import (
    build_gold,
    build_silver_prices,
    build_silver_rates,
)
from infrastructure.market_data.instruments import (
    PriceCurrency,
    Source,
    canonical_from_tesouro,
    canonical_from_yahoo,
    resolve,
)
from infrastructure.persistence.parquet_market_data_repository import ParquetMarketDataRepository

FIXTURES = Path(__file__).parents[2] / "fixtures" / "medallion"


@pytest.mark.parametrize(
    ("ticker", "source", "symbol", "currency"),
    [
        ("EGIE3", Source.YAHOO, "EGIE3.SA", PriceCurrency.BRL),
        ("PETR4F", Source.YAHOO, "PETR4.SA", PriceCurrency.BRL),
        ("BTC", Source.YAHOO, "BTC-USD", PriceCurrency.USD),
        ("CDI", Source.BCB, "12", PriceCurrency.INDEX),
        ("TBILL3M", Source.YAHOO, "^IRX", PriceCurrency.INDEX),
        ("NTNB-2060", Source.TESOURO, "NTNB-2060", PriceCurrency.BRL),
        ("^BVSP", Source.YAHOO, "^BVSP", PriceCurrency.BRL),
        ("AGG", Source.YAHOO, "AGG", PriceCurrency.USD),
    ],
)
def test_resolve(ticker: str, source: Source, symbol: str, currency: PriceCurrency) -> None:
    spec = resolve(ticker)
    assert (spec.source, spec.source_symbol, spec.currency) == (source, symbol, currency)


def test_inversos() -> None:
    assert canonical_from_yahoo("EGIE3.SA") == "EGIE3"
    assert canonical_from_yahoo("BTC-USD") == "BTC"
    assert canonical_from_yahoo("^IRX") == "TBILL3M"
    assert canonical_from_tesouro("Tesouro IPCA+ com Juros Semestrais", 2060) == "NTNB-2060"
    assert canonical_from_tesouro("Tesouro Renda+ Aposentadoria Extra", 2084) is None


@pytest.fixture
def repo(tmp_path: Path) -> ParquetMarketDataRepository:
    shutil.copytree(FIXTURES, tmp_path, dirs_exist_ok=True)
    build_silver_prices(tmp_path)
    build_silver_rates(tmp_path)
    build_gold(tmp_path)
    return ParquetMarketDataRepository(tmp_path)


def test_ultimos_precos_em_decimal(repo: ParquetMarketDataRepository) -> None:
    prices = repo.latest_prices([Ticker("ABCD3"), Ticker("BTC"), Ticker("NOPE3")])
    assert prices[Ticker("ABCD3")].amount == Decimal("12.50000000")
    assert prices[Ticker("BTC")].amount == Decimal("900.00000000")  # 150 x 6,0
    assert Ticker("NOPE3") not in prices


def test_historico_alinhado_so_nas_datas_comuns(repo: ParquetMarketDataRepository) -> None:
    history = repo.price_history([Ticker("ABCD3"), Ticker("BTC")])
    # BTC tem fim de semana; ABCD3 não. Ficam só os dias em que os dois negociaram.
    assert history.dates == (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    assert history.column("BTC")[0] == pytest.approx(120 * 5.5)
    assert history.simple_returns().shape == (3, 2)


def test_historico_com_inicio(repo: ParquetMarketDataRepository) -> None:
    history = repo.price_history([Ticker("ABCD3")], start=date(2026, 1, 7))
    assert history.dates == (date(2026, 1, 7), date(2026, 1, 8))


def test_ticker_sem_historico(repo: ParquetMarketDataRepository) -> None:
    with pytest.raises(MissingMarketDataError, match="NOPE3"):
        repo.price_history([Ticker("ABCD3"), Ticker("NOPE3")])


def test_sem_gold_gerada(tmp_path: Path) -> None:
    empty = ParquetMarketDataRepository(tmp_path)
    assert empty.latest_prices([Ticker("ABCD3")]) == {}
    with pytest.raises(MissingMarketDataError):
        empty.price_history([Ticker("ABCD3")])
