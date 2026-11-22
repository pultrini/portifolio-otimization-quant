"""Cotação de um título do Tesouro e termos da compra informados pelo usuário."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from datetime import date

from domain.exceptions import DomainError

# Taxas fora disso são quase certamente erro de digitação (ex.: 650 em vez de 6,50).
_MIN_RATE, _MAX_RATE = -0.05, 0.50


@dataclass(frozen=True, slots=True)
class TreasuryQuote:
    """Cotação do dia no Tesouro Direto (taxas em fração: 0,0758 = 7,58% a.a.).

    Compra = o investidor compra (liquida em D+1); venda = resgate antecipado (D+0).
    Um lado pode faltar (título fechado para compra, por exemplo).
    """

    ticker: str
    date: dt.date
    maturity: dt.date
    buy_rate: float | None
    sell_rate: float | None
    pu_buy: float | None
    pu_sell: float | None


@dataclass(frozen=True, slots=True)
class BondTerms:
    """Taxa contratada de um título na carteira.

    Attributes:
        contracted_rate: Taxa da compra em fração (prefixada, ou acima do IPCA).
        purchase_date: Data da compra, quando a taxa foi estimada por ela.
        estimated: True quando a taxa foi calculada pelo preço médio e pela data,
            False quando o usuário digitou a taxa da nota de compra.
    """

    contracted_rate: float
    purchase_date: date | None = None
    estimated: bool = False

    def __post_init__(self) -> None:
        if not _MIN_RATE <= self.contracted_rate <= _MAX_RATE:
            raise DomainError(
                "Taxa contratada fora do intervalo de −5% a 50% a.a.; confira o valor."
            )
