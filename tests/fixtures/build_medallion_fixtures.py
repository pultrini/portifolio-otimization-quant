"""Gera os Parquets de fixture da Bronze usados nos testes do pipeline.

Rodar quando o formato da Bronze mudar:
    uv run python tests/fixtures/build_medallion_fixtures.py

Valores escolhidos para contas fáceis de conferir à mão (ver testes):
    - ABCD3.SA tem dois snapshots; a Silver deve usar só o mais recente (reajustado).
    - BTC-USD negocia no fim de semana; a PTAX de sexta é usada no sábado e domingo.
    - CDI de 0,05% ao dia -> índice 1, 1.0005, 1.0005^2.
    - Tesouro com números em formato brasileiro ("3.917,97") e um tipo não suportado.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from infrastructure.data_engineering.layers import write_bronze
from infrastructure.data_engineering.schemas import BCB_BRONZE, TESOURO_BRONZE, YAHOO_BRONZE
from infrastructure.market_data.instruments import Source

ROOT = Path(__file__).parent / "medallion"
FIRST_RUN = datetime(2026, 1, 7, 21, 0, tzinfo=UTC)
SECOND_RUN = datetime(2026, 1, 8, 21, 0, tzinfo=UTC)


def _yahoo(symbol: str, days: list[date], adj: list[float | None]) -> pl.DataFrame:
    n = len(days)
    return pl.DataFrame(
        {
            "date": days,
            "symbol": [symbol] * n,
            "open": adj,
            "high": adj,
            "low": adj,
            "close": adj,
            "adj_close": adj,
            "volume": [1000.0] * n,
            "dividends": [0.0] * n,
            "stock_splits": [0.0] * n,
        },
        schema=YAHOO_BRONZE,
    )


def _bcb(code: str, rows: list[tuple[str, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "series_code": [code] * len(rows),
            "data": [r[0] for r in rows],
            "valor": [r[1] for r in rows],
        },
        schema=BCB_BRONZE,
    )


def main() -> None:
    d = date
    # Snapshot antigo de ABCD3 (antes de um provento): deve ser ignorado pela Silver.
    write_bronze(
        _yahoo("ABCD3.SA", [d(2026, 1, 5), d(2026, 1, 6), d(2026, 1, 7)], [10.0, 11.0, 12.0]),
        ROOT,
        Source.YAHOO,
        YAHOO_BRONZE,
        FIRST_RUN,
        "symbol",
        "ABCD3.SA",
    )
    # Snapshot novo: histórico reajustado + um dia sem preço (deve sair na Silver).
    write_bronze(
        _yahoo(
            "ABCD3.SA",
            [d(2026, 1, 5), d(2026, 1, 6), d(2026, 1, 7), d(2026, 1, 8), d(2026, 1, 9)],
            [9.0, 10.0, 11.0, 12.5, None],
        ),
        ROOT,
        Source.YAHOO,
        YAHOO_BRONZE,
        SECOND_RUN,
        "symbol",
        "ABCD3.SA",
    )
    write_bronze(
        _yahoo(
            "BTC-USD",
            [
                d(2026, 1, 3),
                d(2026, 1, 4),
                d(2026, 1, 5),
                d(2026, 1, 6),
                d(2026, 1, 7),
                d(2026, 1, 8),
            ],
            [100.0, 110.0, 120.0, 130.0, 140.0, 150.0],
        ),
        ROOT,
        Source.YAHOO,
        YAHOO_BRONZE,
        SECOND_RUN,
        "symbol",
        "BTC-USD",
    )
    write_bronze(
        _yahoo("^IRX", [d(2026, 1, 5), d(2026, 1, 6), d(2026, 1, 8)], [3.65, 3.65, 3.65]),
        ROOT,
        Source.YAHOO,
        YAHOO_BRONZE,
        SECOND_RUN,
        "symbol",
        "^IRX",
    )
    write_bronze(
        _bcb(
            "1",
            [
                ("02/01/2026", "5.0000"),
                ("05/01/2026", "5.5000"),
                ("06/01/2026", "5.0000"),
                ("07/01/2026", "5.0000"),
                ("08/01/2026", "6.0000"),
            ],
        ),
        ROOT,
        Source.BCB,
        BCB_BRONZE,
        SECOND_RUN,
        "series_code",
        "1",
    )
    write_bronze(
        _bcb(
            "12",
            [("02/01/2026", "0.050000"), ("05/01/2026", "0.050000"), ("06/01/2026", "0.100000")],
        ),
        ROOT,
        Source.BCB,
        BCB_BRONZE,
        SECOND_RUN,
        "series_code",
        "12",
    )
    tesouro = pl.DataFrame(
        {
            "tipo_titulo": [
                "Tesouro IPCA+ com Juros Semestrais",
                "Tesouro IPCA+ com Juros Semestrais",
                "Tesouro Prefixado",
                "Tesouro Renda+ Aposentadoria Extra",
            ],
            "data_vencimento": ["15/08/2060", "15/08/2060", "01/01/2027", "15/12/2084"],
            "data_base": ["05/01/2026", "06/01/2026", "05/01/2026", "05/01/2026"],
            "taxa_compra_manha": ["7,58", "7,60", "14,10", "7,00"],
            "taxa_venda_manha": ["7,70", "7,72", "14,22", "7,12"],
            "pu_compra_manha": ["3.977,74", "4.010,00", "900,50", "1.000,00"],
            "pu_venda_manha": ["3.917,97", "3.950,00", "899,80", "990,00"],
            "pu_base_manha": ["3.917,97", "3.950,00", "899,80", "990,00"],
        },
        schema=TESOURO_BRONZE,
    )
    write_bronze(tesouro, ROOT, Source.TESOURO, TESOURO_BRONZE, SECOND_RUN, "file", "all")


if __name__ == "__main__":
    main()
