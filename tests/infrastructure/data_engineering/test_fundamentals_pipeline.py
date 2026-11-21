"""Pipeline de fundamentos com clients falsos (sem rede): Bronze -> Silver -> Gold."""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from domain.value_objects.ticker import Ticker
from infrastructure.data_engineering.fundamentals import FundamentalsPipeline
from infrastructure.data_engineering.schemas import (
    CVM_REGISTRY_BRONZE,
    CVM_REIT_COMPLEMENT_BRONZE,
    CVM_REIT_GENERAL_BRONZE,
    CVM_SECURITIES_BRONZE,
    DIVIDENDS_BRONZE,
    PROFILE_BRONZE,
    STATEMENTS_BRONZE,
)
from infrastructure.market_data.clients import SourceError
from infrastructure.market_data.fundamentals_clients import YahooFundamentals
from infrastructure.persistence.parquet_fundamentals_repository import (
    ParquetFundamentalsRepository,
)

TODAY = date(2026, 11, 21)


def _months(year: int) -> list[str]:
    return [f"{year}-{m:02d}-01" for m in range(1, 13)]


class FakeCvm:
    """Três FIIs de Logística: AAAA11 paga todo mês (1%), BBBB11 paga 0,5% e um
    fundo fechado (sem bolsa) que paga 3% e não pode entrar na mediana."""

    def registry(self) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "CNPJ_CIA": ["11", "22"],
                "DENOM_SOCIAL": ["KLABIN", "ESTATAL SA"],
                "DT_CONST": ["1978-11-08", "2000-01-01"],
                "SIT": ["ATIVO", "ATIVO"],
                "SETOR_ATIV": ["Papel", "Energia"],
                "CONTROLE_ACIONARIO": ["PRIVADO", "ESTATAL"],
            },
            schema=CVM_REGISTRY_BRONZE,
        )

    def securities(self, year: int) -> pl.DataFrame:
        if year == TODAY.year:
            raise SourceError("FCA do ano ainda não publicado")
        # KLBN4 só aparece dentro da unit KLBN11: liga pela raiz "KLBN".
        return pl.DataFrame(
            {
                "CNPJ_Companhia": ["11", "22"],
                "Codigo_Negociacao": ["KLBN11", "ESTT3"],
                "Data_Referencia": ["2025-01-01", "2025-01-01"],
            },
            schema=CVM_SECURITIES_BRONZE,
        )

    def reit_monthly(self, year: int) -> tuple[pl.DataFrame, pl.DataFrame]:
        months = _months(year) if year < TODAY.year else _months(year)[:10]
        funds = [
            ("A1", "BRAAAACTF001", "S", "0.01"),
            ("B1", "BRBBBBCTF001", "S", "0.005"),
            ("C1", "BRCCCCCTF001", "N", "0.03"),
        ]
        general = pl.DataFrame(
            {
                "CNPJ_Fundo_Classe": [f[0] for f in funds for _ in months],
                "Data_Referencia": [m for _ in funds for m in months],
                "Codigo_ISIN": [f[1] for f in funds for _ in months],
                "Segmento_Atuacao": ["Logística"] * (len(funds) * len(months)),
                "Mercado_Negociacao_Bolsa": [f[2] for f in funds for _ in months],
            },
            schema=CVM_REIT_GENERAL_BRONZE,
        )
        complement = pl.DataFrame(
            {
                "CNPJ_Fundo_Classe": [f[0] for f in funds for _ in months],
                "Data_Referencia": [m for _ in funds for m in months],
                "Valor_Patrimonial_Cotas": ["100.0"] * (len(funds) * len(months)),
                "Percentual_Dividend_Yield_Mes": [f[3] for f in funds for _ in months],
            },
            schema=CVM_REIT_COMPLEMENT_BRONZE,
        )
        return general, complement


class FakeYahoo:
    def __init__(self) -> None:
        self.symbols: list[str] = []

    def fetch(self, symbol: str) -> YahooFundamentals:
        self.symbols.append(symbol)
        rows = [
            ("income", "Total Revenue", date(2022, 12, 31), 100.0),
            ("income", "Total Revenue", date(2025, 12, 31), 110.0),
            ("income", "Net Income Common Stockholders", date(2025, 12, 31), 12.0),
            ("balance", "Common Stock Equity", date(2025, 12, 31), 100.0),
        ]
        return YahooFundamentals(
            statements=pl.DataFrame(
                [
                    {"symbol": symbol, "statement": s, "item": i, "period_end": d, "value": v}
                    for s, i, d, v in rows
                ],
                schema=STATEMENTS_BRONZE,
            ),
            profile=pl.DataFrame(
                [{"symbol": symbol, "market_cap": 2.0e10, "currency": "BRL"}], schema=PROFILE_BRONZE
            ),
            dividends=pl.DataFrame(
                [{"symbol": symbol, "date": date(y, 6, 1), "amount": 1.0} for y in (2023, 2025)],
                schema=DIVIDENDS_BRONZE,
            ),
        )


@pytest.fixture
def repo(tmp_path: Path) -> tuple[ParquetFundamentalsRepository, FakeYahoo, dict[str, str]]:
    yahoo = FakeYahoo()
    pipeline = FundamentalsPipeline(
        tmp_path,
        yahoo,  # type: ignore[arg-type]
        FakeCvm(),  # type: ignore[arg-type]
        today=lambda: TODAY,
        now=lambda: datetime(2026, 11, 21, 12, tzinfo=UTC),
    )
    failures = pipeline.refresh([Ticker(t) for t in ("KLBN4", "AAAA11", "CDI", "BTC")])
    return ParquetFundamentalsRepository(tmp_path), yahoo, failures


def test_fii_nao_vai_ao_yahoo_e_renda_fixa_e_cripto_ficam_fora(
    repo: tuple[ParquetFundamentalsRepository, FakeYahoo, dict[str, str]],
) -> None:
    _, yahoo, failures = repo
    assert yahoo.symbols == ["KLBN4.SA"]
    # O FCA de 2026 falhou, mas o de 2025 foi usado: não sobra falha.
    assert failures == {}


def test_acao_liga_cnpj_pela_raiz_e_coalesce_itens(
    repo: tuple[ParquetFundamentalsRepository, FakeYahoo, dict[str, str]],
) -> None:
    funds = repo[0].stock_fundamentals([Ticker("KLBN4")])[Ticker("KLBN4")]
    assert funds.constitution_date == date(1978, 11, 8)
    assert funds.control == "PRIVADO"
    assert funds.market_cap_brl == 2.0e10
    assert funds.dividend_years == frozenset({2023, 2025})
    latest = next(a for a in funds.annual if a.year == 2025)
    # "Net Income Common Stockholders" e "Common Stock Equity" são alternativas aceitas.
    assert latest.net_income == 12.0
    assert latest.roe == pytest.approx(0.12)


def test_fii_constancia_e_mediana_do_segmento(
    repo: tuple[ParquetFundamentalsRepository, FakeYahoo, dict[str, str]],
) -> None:
    reits = repo[0].reit_fundamentals([Ticker("AAAA11"), Ticker("BBBB11"), Ticker("CCCC11")])
    a = reits[Ticker("AAAA11")]
    assert a.segment == "Logística"
    assert a.book_value_per_share == 100.0
    # Janela: 48 meses até out/2026 = nov/2022 a out/2026.
    assert a.months_observed == 48
    assert a.months_with_dividends == 48
    assert a.dividend_yield_12m == pytest.approx(0.12)
    # Mediana só entre listados que pagam: (12% + 6%) / 2 = 9%; o fechado (36%) fica fora.
    assert a.segment_median_yield_12m == pytest.approx(0.09)
    assert reits[Ticker("BBBB11")].dividend_yield_12m == pytest.approx(0.06)
