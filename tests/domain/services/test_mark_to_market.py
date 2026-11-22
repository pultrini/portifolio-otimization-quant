"""Marcação a mercado conferida com cotações reais do Tesouro Direto (19/11/2026)."""

from datetime import date
from decimal import Decimal

import pytest

from domain.exceptions import DomainError
from domain.services.business_calendar import (
    add_business_days,
    business_days,
    easter,
    holidays,
)
from domain.services.mark_to_market import (
    BondKind,
    bond_kind,
    coupon_dates,
    estimate_contracted_rate,
    implied_rate,
    mark_to_market,
    price_factor,
)
from domain.value_objects.ticker import Ticker

D = date(2026, 11, 19)


def test_calendario_anbima() -> None:
    assert easter(2026) == date(2026, 4, 5)
    assert easter(2024) == date(2024, 3, 31)
    feriados = holidays(2026)
    assert date(2026, 2, 16) in feriados and date(2026, 2, 17) in feriados  # Carnaval
    assert date(2026, 4, 3) in feriados  # Sexta-feira Santa
    assert date(2026, 6, 4) in feriados  # Corpus Christi
    assert date(2026, 11, 20) in feriados  # Consciência Negra (desde 2024)
    assert date(2023, 11, 20) not in holidays(2023)
    # Quinta 19/11 -> sexta é feriado, fim de semana: só a quinta conta até segunda.
    assert business_days(D, date(2026, 11, 23)) == 1
    assert add_business_days(D, 1) == date(2026, 11, 23)
    assert business_days(D, D) == 0


@pytest.mark.parametrize(
    ("ticker", "kind", "maturity", "rate", "pu", "base"),
    [
        # Prefixado: a base tem de voltar a R$ 1.000.
        ("PRE-2031", BondKind.PREFIXADO, date(2031, 1, 1), 0.1547, 555.79, 1000.0),
        ("PRE-2027", BondKind.PREFIXADO, date(2027, 1, 1), 0.1368, 985.35, 1000.0),
        # IPCA+ e IPCA+ com juros: todos chegam ao mesmo VNA do dia (R$ 4.775,40).
        ("IPCA-2035", BondKind.IPCA, date(2035, 5, 15), 0.0798, 2500.95, 4775.40),
        ("IPCA-2050", BondKind.IPCA, date(2050, 8, 15), 0.0768, 833.74, 4775.40),
        ("NTNB-2035", BondKind.IPCA_COUPON, date(2035, 5, 15), 0.0793, 4248.81, 4775.40),
        ("NTNB-2060", BondKind.IPCA_COUPON, date(2060, 8, 15), 0.0770, 3917.97, 4775.40),
    ],
)
def test_precificacao_reproduz_o_tesouro(
    ticker: str, kind: BondKind, maturity: date, rate: float, pu: float, base: float
) -> None:
    assert bond_kind(Ticker(ticker)) is kind
    assert pu / price_factor(kind, rate, D, maturity) == pytest.approx(base, abs=0.05)


def test_cupons_semestrais_da_ntnb() -> None:
    dates = coupon_dates(date(2060, 8, 15), D)
    assert dates[0] == date(2027, 2, 15) and dates[-1] == date(2060, 8, 15)
    assert all(d.day == 15 and d.month in (2, 8) for d in dates)
    assert len(dates) == 68  # 34 anos x 2


def test_marcacao_contra_e_a_favor() -> None:
    args = (Ticker("PRE-2031"), date(2031, 1, 1), D, Decimal("2"), 555.79, 0.1547, 0.1535)
    # Comprado a 13%: a taxa subiu, o valor na curva é maior que o de venda.
    against = mark_to_market(*args, contracted_rate=0.13)
    assert against.sale_value == Decimal("1111.58")
    assert against.curve_value > against.sale_value
    assert not against.favorable
    assert against.break_even_rate == 0.1547
    # Comprado a 17%: a taxa caiu, vender entrega mais que a curva.
    favour = mark_to_market(*args, contracted_rate=0.17)
    assert favour.favorable and favour.difference > 0
    # Contratada = taxa de venda: diferença zero.
    even = mark_to_market(*args, contracted_rate=0.1547)
    assert even.difference == Decimal("0")
    # Curva pela fórmula fechada: PU x (1,1547 / 1,13)^(du/252).
    du = business_days(D, date(2031, 1, 1))
    expected = 555.79 * (1.1547 / 1.13) ** (du / 252) * 2
    assert float(against.curve_value) == pytest.approx(expected, abs=0.01)


def test_taxa_implicita_e_estimativa_pela_data() -> None:
    maturity = date(2031, 1, 1)
    price = 1000 * price_factor(BondKind.PREFIXADO, 0.12, D, maturity)
    assert implied_rate(BondKind.PREFIXADO, price, 1000, D, maturity) == pytest.approx(0.12)
    # Compra em 03/06/2024 a 11,8% (liquida em 04/06): o preço pago reproduz a taxa.
    purchase = date(2024, 6, 3)
    settlement = add_business_days(purchase, 1)
    pu = 1000 * price_factor(BondKind.PREFIXADO, 0.118, settlement, maturity)
    rate = estimate_contracted_rate(Ticker("PRE-2031"), maturity, purchase, pu, pu, 0.118)
    assert rate == pytest.approx(0.118, abs=1e-8)
    # Pagou mais caro que a cotação do dia -> taxa contratada menor.
    lower = estimate_contracted_rate(Ticker("PRE-2031"), maturity, purchase, pu * 1.02, pu, 0.118)
    assert lower < 0.118


def test_casos_sem_comparacao() -> None:
    args = (date(2029, 3, 1), D, Decimal("1"), 17000.0, 0.0005, 0.0004, 0.001)
    with pytest.raises(DomainError, match="Selic"):
        mark_to_market(Ticker("SELIC-2029"), *args)
    with pytest.raises(DomainError):
        mark_to_market(Ticker("PETR4"), *args)
    with pytest.raises(DomainError, match="venceu"):
        mark_to_market(Ticker("PRE-2026"), date(2026, 1, 1), D, Decimal("1"), 1000, 0.1, 0.1, 0.1)
    with pytest.raises(DomainError):
        implied_rate(BondKind.PREFIXADO, 1e6, 1000, D, date(2031, 1, 1))  # sem taxa possível
