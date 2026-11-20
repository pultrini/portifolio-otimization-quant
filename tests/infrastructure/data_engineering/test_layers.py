"""Testes das camadas Silver e Gold sobre a Bronze de fixture (sem rede)."""

import math
import shutil
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from infrastructure.data_engineering.layers import (
    build_gold,
    build_silver_prices,
    build_silver_rates,
)
from infrastructure.data_engineering.schemas import (
    SILVER_PRICES,
    YAHOO_BRONZE,
    SchemaMismatchError,
    validate,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "medallion"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Cópia da Bronze de fixture em uma pasta temporária, já processada até a Gold."""
    shutil.copytree(FIXTURES, tmp_path, dirs_exist_ok=True)
    build_silver_prices(tmp_path)
    build_silver_rates(tmp_path)
    build_gold(tmp_path)
    return tmp_path


def _series(data_dir: Path, table: str, ticker: str, column: str) -> dict[date, float]:
    frame = pl.read_parquet(data_dir / table).filter(pl.col("ticker") == ticker).sort("date")
    return dict(zip(frame["date"].to_list(), frame[column].to_list(), strict=True))


def test_silver_usa_so_o_snapshot_mais_recente_e_descarta_nulos(data_dir: Path) -> None:
    prices = _series(data_dir, "silver/prices.parquet", "ABCD3", "adj_close")
    # Snapshot de 08/01 (reajustado); 09/01 sem preço não entra (sem forward-fill).
    assert prices == {
        date(2026, 1, 5): 9.0,
        date(2026, 1, 6): 10.0,
        date(2026, 1, 7): 11.0,
        date(2026, 1, 8): 12.5,
    }


def test_silver_tesouro_le_numeros_brasileiros_e_ignora_tipo_nao_suportado(
    data_dir: Path,
) -> None:
    silver = pl.read_parquet(data_dir / "silver/prices.parquet")
    assert _series(data_dir, "silver/prices.parquet", "NTNB-2060", "close") == {
        date(2026, 1, 5): 3917.97,
        date(2026, 1, 6): 3950.0,
    }
    assert "PRE-2027" in silver["ticker"].to_list()
    assert not silver.filter(pl.col("ticker").str.contains("RENDA")).height
    assert silver.schema == SILVER_PRICES


def test_gold_converte_usd_com_ptax_e_repete_a_de_sexta_no_fim_de_semana(
    data_dir: Path,
) -> None:
    btc = _series(data_dir, "gold/prices.parquet", "BTC", "price_brl")
    # Sáb/dom usam a PTAX de sexta (5,0); segunda usa 5,5; quinta usa 6,0.
    assert btc[date(2026, 1, 3)] == pytest.approx(100 * 5.0)
    assert btc[date(2026, 1, 4)] == pytest.approx(110 * 5.0)
    assert btc[date(2026, 1, 5)] == pytest.approx(120 * 5.5)
    assert btc[date(2026, 1, 8)] == pytest.approx(150 * 6.0)


def test_gold_indice_do_cdi(data_dir: Path) -> None:
    cdi = _series(data_dir, "gold/prices.parquet", "CDI", "price_brl")
    # A taxa da data d rende de d para d+1: o índice só sobe no dia seguinte.
    assert cdi[date(2026, 1, 2)] == pytest.approx(1.0)
    assert cdi[date(2026, 1, 5)] == pytest.approx(1.0005)
    assert cdi[date(2026, 1, 6)] == pytest.approx(1.0005**2)


def test_gold_indice_do_tbill_usa_dias_corridos(data_dir: Path) -> None:
    tbill = _series(data_dir, "gold/prices.parquet", "TBILL3M", "price_brl")
    one_day = 1.0365 ** (1 / 365)
    assert tbill[date(2026, 1, 6)] == pytest.approx(one_day)
    # De 06/01 a 08/01 são 2 dias corridos.
    assert tbill[date(2026, 1, 8)] == pytest.approx(one_day * 1.0365 ** (2 / 365))


def test_gold_retornos_e_drawdown(data_dir: Path) -> None:
    simple = _series(data_dir, "gold/returns.parquet", "ABCD3", "simple_return")
    assert simple[date(2026, 1, 6)] == pytest.approx(10 / 9 - 1)
    log = _series(data_dir, "gold/returns.parquet", "ABCD3", "log_return")
    assert log[date(2026, 1, 8)] == pytest.approx(math.log(12.5 / 11))
    drawdown = _series(data_dir, "gold/drawdowns.parquet", "NTNB-2060", "drawdown")
    assert drawdown[date(2026, 1, 6)] == pytest.approx(0.0)


def test_reprocessar_e_idempotente(data_dir: Path) -> None:
    before = {
        name: pl.read_parquet(data_dir / "gold" / f"{name}.parquet")
        for name in ("prices", "returns", "fx", "drawdowns")
    }
    build_silver_prices(data_dir)
    build_silver_rates(data_dir)
    build_gold(data_dir)
    for name, frame in before.items():
        assert_frame_equal(frame, pl.read_parquet(data_dir / "gold" / f"{name}.parquet"))


def test_validacao_de_schema_aponta_a_coluna_errada() -> None:
    wrong = pl.DataFrame({"date": ["2026-01-01"]})
    with pytest.raises(SchemaMismatchError, match="date"):
        validate(wrong, YAHOO_BRONZE, "teste")
