"""Marcação a mercado de títulos do Tesouro: vender hoje ou levar até o vencimento?

Conceitos:
    - Valor de mercado: o que o Tesouro paga hoje no resgate antecipado (PU de venda,
      calculado com a taxa de venda de hoje).
    - Valor na curva: o que o título valeria hoje se fosse precificado pela taxa
      contratada na compra. É o caminho "garantido" de quem leva até o vencimento.
    - Marcação a favor: taxa de mercado abaixo da contratada -> valor de mercado acima
      do valor na curva. Vender realiza esse ganho antecipado.

Precificação (Tesouro Direto, base 252 dias úteis):
    fator(r) = 1 / (1 + r)^(du/252)                                  sem cupom
    fator(r) = Σ c / (1 + r)^(du_i/252) + 1 / (1 + r)^(du/252)       NTN-B (c = 1,06^0,5 − 1)
    PU = base x fator(r)

A base é R$ 1.000 no prefixado e o VNA (valor nominal atualizado pelo IPCA) nos
títulos de IPCA. Como base = PU_venda / fator(taxa_venda), o mesmo cálculo serve para
os dois sem precisar baixar o VNA:
    valor na curva = PU_venda x fator(taxa_contratada) / fator(taxa_venda)

Vender só rende mais que levar até o vencimento se o dinheiro for reinvestido, até o
mesmo vencimento, a uma taxa acima da taxa de venda de hoje (o "empate"): é a taxa que
o mercado está pagando para assumir o restante do seu título.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from scipy.optimize import brentq

from domain.exceptions import DomainError
from domain.services.business_calendar import add_business_days, business_days
from domain.value_objects.ticker import Ticker

DAYS_PER_YEAR = 252
# Cupom semestral da NTN-B: 6% a.a. equivalentes -> 1,06^(1/2) − 1 = 2,956301% ao semestre.
NTNB_SEMIANNUAL_COUPON = 1.06**0.5 - 1
_CENT = Decimal("0.01")


class BondKind(StrEnum):
    PREFIXADO = "PREFIXADO"  # Tesouro Prefixado (LTN): paga R$ 1.000 no vencimento
    IPCA = "IPCA"  # Tesouro IPCA+ (NTN-B Principal): paga o VNA no vencimento
    IPCA_COUPON = "IPCA_COUPON"  # Tesouro IPCA+ com Juros Semestrais (NTN-B)
    SELIC = "SELIC"  # Tesouro Selic (LFT): pós-fixado, marcação quase nula

    @property
    def label_pt(self) -> str:
        return {
            BondKind.PREFIXADO: "Tesouro Prefixado",
            BondKind.IPCA: "Tesouro IPCA+",
            BondKind.IPCA_COUPON: "Tesouro IPCA+ com Juros Semestrais",
            BondKind.SELIC: "Tesouro Selic",
        }[self]

    @property
    def rate_suffix(self) -> str:
        """Como a taxa é lida: prefixada ou acima do IPCA (ou da Selic)."""
        if self is BondKind.PREFIXADO:
            return "a.a."
        if self is BondKind.SELIC:
            return "a.a. + Selic"
        return "a.a. + IPCA"


_PREFIXES = {
    "PRE-": BondKind.PREFIXADO,
    "IPCA-": BondKind.IPCA,
    "NTNB-": BondKind.IPCA_COUPON,
    "SELIC-": BondKind.SELIC,
}


def bond_kind(ticker: Ticker) -> BondKind | None:
    """Tipo do título pelo ticker canônico (PRE-2031, IPCA-2035, NTNB-2060, SELIC-2029)."""
    for prefix, kind in _PREFIXES.items():
        if ticker.symbol.startswith(prefix):
            return kind
    return None


def coupon_dates(maturity: date, after: date) -> list[date]:
    """Datas de cupom da NTN-B depois de `after`, de 6 em 6 meses até o vencimento."""
    dates: list[date] = []
    year, month = maturity.year, maturity.month
    current = maturity
    while current > after:
        dates.append(current)
        month -= 6
        if month <= 0:
            month += 12
            year -= 1
        current = date(year, month, min(maturity.day, 28) if month == 2 else maturity.day)
    return sorted(dates)


def price_factor(kind: BondKind, rate: float, settlement: date, maturity: date) -> float:
    """Fator de desconto do título (PU por unidade de base) a uma taxa anual."""
    if rate <= -1:
        raise DomainError("Taxa inválida: precisa ser maior que −100%.")
    du = business_days(settlement, maturity)
    principal = (1 + rate) ** (-du / DAYS_PER_YEAR)
    if kind is not BondKind.IPCA_COUPON:
        return float(principal)
    coupons = sum(
        NTNB_SEMIANNUAL_COUPON * (1 + rate) ** (-business_days(settlement, d) / DAYS_PER_YEAR)
        for d in coupon_dates(maturity, settlement)
    )
    return float(coupons + principal)


def implied_rate(
    kind: BondKind, price: float, base: float, settlement: date, maturity: date
) -> float:
    """Taxa que faz base x fator(taxa) = preço (usada para estimar a taxa contratada).

    Raises:
        DomainError: preço fora do intervalo que alguma taxa entre −50% e 100% explica.
    """
    if price <= 0 or base <= 0:
        raise DomainError("Preço e base precisam ser positivos.")

    def gap(rate: float) -> float:
        return base * price_factor(kind, rate, settlement, maturity) - price

    try:
        return float(brentq(gap, -0.5, 1.0, xtol=1e-10))
    except ValueError as error:
        raise DomainError("Nenhuma taxa explica esse preço para o título.") from error


@dataclass(frozen=True, slots=True)
class MarkToMarket:
    """Comparação entre vender hoje e levar o título até o vencimento.

    Attributes:
        sale_value: Valor de mercado da posição (resgate hoje).
        curve_value: Valor da posição hoje pela taxa contratada.
        difference: sale_value − curve_value. Positivo = marcação a favor.
        break_even_rate: Taxa (no mesmo indexador) que o dinheiro da venda precisa
            render até o vencimento para empatar com levar até o fim: a taxa de venda.
        buy_rate: Taxa de compra de hoje do mesmo título (para comparar).
    """

    ticker: str
    kind: BondKind
    maturity: date
    business_days: int
    quantity: Decimal
    contracted_rate: float
    sell_rate: float
    buy_rate: float
    sale_value: Decimal
    curve_value: Decimal
    break_even_rate: float

    @property
    def difference(self) -> Decimal:
        return self.sale_value - self.curve_value

    @property
    def favorable(self) -> bool:
        """Vender hoje entrega mais do que o valor na curva."""
        return self.difference > 0

    @property
    def difference_pct(self) -> float | None:
        if self.curve_value <= 0:
            return None
        return float(self.difference / self.curve_value)


def mark_to_market(
    ticker: Ticker,
    maturity: date,
    today: date,
    quantity: Decimal,
    pu_sell: float,
    sell_rate: float,
    buy_rate: float,
    contracted_rate: float,
) -> MarkToMarket:
    """Valor de venda hoje x valor na curva da taxa contratada.

    Fórmulas:
        valor de venda = PU_venda x quantidade
        valor na curva = PU_venda x fator(taxa_contratada) / fator(taxa_venda) x quantidade
        diferença      = valor de venda − valor na curva

    Raises:
        DomainError: título desconhecido, Tesouro Selic, vencido ou sem quantidade.
    """
    kind = bond_kind(ticker)
    if kind is None:
        raise DomainError(f"{ticker} não é um título do Tesouro Direto.")
    if kind is BondKind.SELIC:
        raise DomainError(
            "Tesouro Selic é pós-fixado: o preço acompanha a Selic e a marcação a mercado "
            "é quase nula. A comparação vale para prefixados e IPCA+."
        )
    if maturity <= today:
        raise DomainError(f"{ticker} já venceu.")
    if quantity <= 0:
        raise DomainError("Quantidade precisa ser positiva.")
    market = price_factor(kind, sell_rate, today, maturity)
    curve = price_factor(kind, contracted_rate, today, maturity)
    sale_unit = Decimal(str(pu_sell))
    curve_unit = Decimal(str(pu_sell * curve / market))
    return MarkToMarket(
        ticker=ticker.symbol,
        kind=kind,
        maturity=maturity,
        business_days=business_days(today, maturity),
        quantity=quantity,
        contracted_rate=contracted_rate,
        sell_rate=sell_rate,
        buy_rate=buy_rate,
        sale_value=(sale_unit * quantity).quantize(_CENT),
        curve_value=(curve_unit * quantity).quantize(_CENT),
        break_even_rate=sell_rate,
    )


def estimate_contracted_rate(
    ticker: Ticker,
    maturity: date,
    purchase_date: date,
    average_price: float,
    pu_on_purchase: float,
    rate_on_purchase: float,
) -> float:
    """Estima a taxa contratada pelo preço médio pago e pela cotação do dia da compra.

    A compra no Tesouro Direto liquida em D+1, então PU e taxa de compra do dia são
    descontados a partir do dia útil seguinte. A base do dia (R$ 1.000 ou o VNA) sai da
    cotação: base = PU / fator(taxa). A taxa
    contratada é a que leva essa base ao preço médio pago. Com várias compras em datas
    diferentes, o resultado é uma aproximação: o preço médio mistura bases diferentes.
    """
    kind = bond_kind(ticker)
    if kind is None or kind is BondKind.SELIC:
        raise DomainError(f"{ticker}: estimativa disponível só para prefixados e IPCA+.")
    settlement = add_business_days(purchase_date, 1)
    base = pu_on_purchase / price_factor(kind, rate_on_purchase, settlement, maturity)
    return implied_rate(kind, average_price, base, settlement, maturity)
