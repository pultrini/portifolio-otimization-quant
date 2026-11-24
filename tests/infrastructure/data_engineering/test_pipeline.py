"""Testes da orquestração do pipeline com clients falsos (sem rede)."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from domain.value_objects.ticker import Ticker
from infrastructure.data_engineering.pipeline import MedallionPipeline, _tickers_from_file
from infrastructure.data_engineering.schemas import BCB_BRONZE, TESOURO_BRONZE, YAHOO_BRONZE
from infrastructure.market_data.clients import SourceError

TODAY = date(2026, 1, 8)
DAYS = [date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)]


class FakeYahoo:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.calls: list[tuple[str, date]] = []
        self._failing = failing or set()

    def fetch(self, symbol: str, start: date) -> pl.DataFrame:
        self.calls.append((symbol, start))
        if symbol in self._failing:
            raise SourceError(f"sem dados para {symbol}")
        values = [3.0, 3.0, 3.0] if symbol == "^IRX" else [10.0, 11.0, 12.0]
        return pl.DataFrame(
            {
                "date": DAYS,
                "symbol": [symbol] * 3,
                **{col: values for col in ("open", "high", "low", "close", "adj_close")},
                "volume": [1.0] * 3,
                "dividends": [0.0] * 3,
                "stock_splits": [0.0] * 3,
            },
            schema=YAHOO_BRONZE,
        )


class FakeBcb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date]] = []

    def fetch(self, code: str, start: date, end: date) -> pl.DataFrame:
        self.calls.append((code, start))
        values = {"1": "5.0", "11": "0.05", "12": "0.05"}[code]
        return pl.DataFrame(
            {
                "series_code": [code] * 3,
                "data": [d.strftime("%d/%m/%Y") for d in DAYS],
                "valor": [values] * 3,
            },
            schema=BCB_BRONZE,
        )


class FakeTesouro:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self) -> pl.DataFrame:
        self.calls += 1
        return pl.DataFrame(
            {
                "tipo_titulo": ["Tesouro IPCA+ com Juros Semestrais"],
                "data_vencimento": ["15/08/2060"],
                "data_base": ["07/01/2026"],
                "taxa_compra_manha": ["7,5"],
                "taxa_venda_manha": ["7,6"],
                "pu_compra_manha": ["4.000,00"],
                "pu_venda_manha": ["3.990,00"],
                "pu_base_manha": ["3.990,00"],
            },
            schema=TESOURO_BRONZE,
        )


def _pipeline(tmp_path: Path, yahoo: FakeYahoo, tesouro: FakeTesouro) -> MedallionPipeline:
    return MedallionPipeline(
        tmp_path,
        yahoo,
        FakeBcb(),
        tesouro,
        today=lambda: TODAY,
        now=lambda: datetime(2026, 1, 8, 21, 0, tzinfo=UTC),
    )


def test_baixa_referencias_e_tickers_pedidos(tmp_path: Path) -> None:
    yahoo, tesouro = FakeYahoo(), FakeTesouro()
    report = _pipeline(tmp_path, yahoo, tesouro).refresh(
        [Ticker("ABCD3"), Ticker("NTNB-2060")], years=2
    )

    symbols = {symbol for symbol, _ in yahoo.calls}
    # Benchmarks e T-Bill entram sempre, além do ticker pedido.
    assert {"ABCD3.SA", "^BVSP", "^GSPC", "AGG", "BTC-USD", "^IRX"} <= symbols
    # Taxas desde 2000 (base fixa do índice); preços no horizonte pedido.
    starts = dict(yahoo.calls)
    assert starts["^IRX"] == date(2000, 1, 1)
    assert starts["ABCD3.SA"] == date(2024, 1, 9)
    assert tesouro.calls == 1
    assert report.failed_tickers == {}
    assert report.rows_by_layer["gold"] > 0


def test_falha_de_uma_fonte_nao_derruba_as_outras(tmp_path: Path) -> None:
    yahoo = FakeYahoo(failing={"ZZZZ3.SA"})
    report = _pipeline(tmp_path, yahoo, FakeTesouro()).refresh(
        [Ticker("ZZZZ3"), Ticker("ABCD3")], years=1
    )
    assert "sem dados" in report.failed_tickers["ZZZZ3"]
    gold = pl.read_parquet(tmp_path / "gold" / "prices.parquet")
    assert "ABCD3" in gold["ticker"].to_list()


def test_titulo_inexistente_vira_falha(tmp_path: Path) -> None:
    report = _pipeline(tmp_path, FakeYahoo(), FakeTesouro()).refresh([Ticker("NTNB-2099")], years=1)
    assert report.failed_tickers["NTNB-2099"] == "sem cotação após o processamento"


def test_rodar_duas_vezes_no_mesmo_dia_nao_duplica(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path, FakeYahoo(), FakeTesouro())
    pipeline.refresh([Ticker("ABCD3")], years=1)
    files = sorted((tmp_path / "bronze").rglob("*.parquet"))
    silver = pl.read_parquet(tmp_path / "silver" / "prices.parquet")

    pipeline.refresh([Ticker("ABCD3")], years=1)
    assert sorted((tmp_path / "bronze").rglob("*.parquet")) == files
    assert pl.read_parquet(tmp_path / "silver" / "prices.parquet").height == silver.height


def test_tickers_do_arquivo_de_carteira(tmp_path: Path) -> None:
    path = tmp_path / "carteira.txt"
    path.write_text("# comentário\nEGIE3 2 29,30\n\nCDI R$ 10\n", encoding="utf-8")
    assert _tickers_from_file(path) == ["EGIE3", "CDI"]


@pytest.mark.parametrize("years", [1, 5])
def test_horizonte_de_ptax_acompanha_os_anos(tmp_path: Path, years: int) -> None:
    bcb = FakeBcb()
    MedallionPipeline(tmp_path, FakeYahoo(), bcb, FakeTesouro(), today=lambda: TODAY).refresh(
        [], years=years
    )
    starts = dict(bcb.calls)
    # CDI desde a base fixa; PTAX e Selic no horizonte de preços (365 dias por ano).
    assert starts["12"] == date(2000, 1, 1)
    assert starts["1"] == TODAY - timedelta(days=365 * years)
    assert starts["11"] == TODAY - timedelta(days=365 * years)


class BrokenJsonBcb(FakeBcb):
    """SGS instável: a série do CDI responde com algo que não é JSON."""

    def fetch(self, code: str, start: date, end: date) -> pl.DataFrame:
        if code == "12":
            import json

            json.loads("<html>indisponível</html>")
        return super().fetch(code, start, end)


class RateLimitedYahoo(FakeYahoo):
    def fetch(self, symbol: str, start: date) -> pl.DataFrame:
        if symbol == "AAPL":
            raise RuntimeError("Too Many Requests. Rate limited.")
        return super().fetch(symbol, start)


def test_erro_inesperado_de_uma_fonte_vira_falha_e_nao_derruba(tmp_path: Path) -> None:
    pipeline = MedallionPipeline(
        tmp_path,
        RateLimitedYahoo(),
        BrokenJsonBcb(),
        FakeTesouro(),
        today=lambda: TODAY,
        now=lambda: datetime(2026, 1, 8, 21, 0, tzinfo=UTC),
    )
    report = pipeline.refresh([Ticker("AAPL"), Ticker("MSFT"), Ticker("ABCD3")], years=1)
    assert "JSONDecodeError" in report.failed_tickers["CDI"]
    assert "RuntimeError" in report.failed_tickers["AAPL"]
    gold = pl.read_parquet(tmp_path / "gold" / "prices.parquet")
    assert {"MSFT", "ABCD3"} <= set(gold["ticker"].to_list())
