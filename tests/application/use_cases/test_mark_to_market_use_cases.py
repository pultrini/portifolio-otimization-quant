"""Use cases da marcação a mercado com repositórios em memória."""

from datetime import date
from decimal import Decimal

import pytest

from application.dtos.mark_to_market import SaveBondTermsRequest
from application.dtos.portfolio import ImportPositionsRequest
from application.use_cases.import_positions import ImportPositions
from application.use_cases.mark_to_market import GetMarkToMarket, SaveBondTerms
from domain.entities.treasury import TreasuryQuote
from domain.exceptions import DomainError
from domain.services.mark_to_market import BondKind
from tests.fakes.in_memory_repositories import (
    FakeMarketDataRepository,
    FakeTreasuryRepository,
    InMemoryBondTermsRepository,
    InMemoryPositionRepository,
)

TODAY = date(2026, 11, 19)
QUOTES = [
    TreasuryQuote("PRE-2031", TODAY, date(2031, 1, 1), 0.1535, 0.1547, 558.47, 555.79),
    TreasuryQuote("PRE-2031", date(2024, 6, 3), date(2031, 1, 1), 0.118, None, 480.0, None),
    TreasuryQuote("SELIC-2029", TODAY, date(2029, 3, 1), 0.0004, 0.0005, 17900, 17890),
]


def _setup() -> tuple[GetMarkToMarket, SaveBondTerms, InMemoryBondTermsRepository]:
    positions = InMemoryPositionRepository()
    ImportPositions(positions, FakeMarketDataRepository()).execute(
        ImportPositionsRequest(
            user_id="u",
            portfolio_id="p",
            # NTNB-2060 sem cotação no fake; PRE-2031 pago a R$ 480 por título.
            text="PRE-2031 2 480\nSELIC-2029 0,1 17000\nNTNB-2060 0,05 3500\nPETR4 1 30",
        )
    )
    treasury = FakeTreasuryRepository(QUOTES)
    terms = InMemoryBondTermsRepository()
    return (
        GetMarkToMarket(positions, treasury, terms),
        SaveBondTerms(positions, treasury, terms, today=lambda: TODAY),
        terms,
    )


def test_sem_taxa_pede_a_taxa_e_explica_os_demais() -> None:
    get, _, _ = _setup()
    rows = {r.ticker: r for r in get.execute("p").rows}
    assert set(rows) == {"PRE-2031", "SELIC-2029", "NTNB-2060"}  # ações ficam de fora
    assert rows["PRE-2031"].message == "Informe a taxa contratada para comparar."
    assert rows["PRE-2031"].sell_rate == 0.1547
    assert "Selic" in rows["SELIC-2029"].message
    assert "Sem cotação" in rows["NTNB-2060"].message
    assert rows["PRE-2031"].sale_value is None


def test_taxa_digitada_gera_a_comparacao() -> None:
    get, save, _ = _setup()
    stored = save.execute(
        SaveBondTermsRequest(
            user_id="u", portfolio_id="p", ticker="PRE-2031", contracted_rate_pct=13
        )
    )
    assert stored == pytest.approx(0.13)
    row = next(r for r in get.execute("p").rows if r.ticker == "PRE-2031")
    assert row.kind is BondKind.PREFIXADO
    assert row.sale_value == Decimal("1111.58")
    assert row.curve_value is not None and row.curve_value > row.sale_value
    assert row.favorable is False
    assert row.break_even_rate == 0.1547
    assert not row.estimated


def test_taxa_estimada_pela_data_da_compra() -> None:
    get, save, _ = _setup()
    stored = save.execute(
        SaveBondTermsRequest(
            user_id="u", portfolio_id="p", ticker="PRE-2031", purchase_date=date(2024, 6, 3)
        )
    )
    # Pagou R$ 480, exatamente o PU de compra do dia: a taxa estimada é a do dia (11,8%).
    assert stored == pytest.approx(0.118, abs=1e-6)
    row = next(r for r in get.execute("p").rows if r.ticker == "PRE-2031")
    assert row.estimated and row.purchase_date == date(2024, 6, 3)
    # Comprado a 11,8% e hoje o resgate paga 15,47%: marcação contra.
    assert row.favorable is False


def test_erros_ao_salvar() -> None:
    _, save, _ = _setup()
    base = {"user_id": "u", "portfolio_id": "p", "ticker": "PRE-2031"}
    with pytest.raises(DomainError, match="Informe"):
        save.execute(SaveBondTermsRequest(**base))
    with pytest.raises(DomainError, match="futuro"):
        save.execute(SaveBondTermsRequest(**base, purchase_date=date(2027, 1, 1)))
    with pytest.raises(DomainError, match="Sem cotação"):
        save.execute(SaveBondTermsRequest(**base, purchase_date=date(2020, 1, 2)))
