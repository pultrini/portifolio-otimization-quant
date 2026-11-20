"""Valor monetário com moeda, sempre em `Decimal` (CLAUDE.md 5.2)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from domain.exceptions import CurrencyMismatchError, DomainError

CENTS = Decimal("0.01")


class Currency(StrEnum):
    """Moedas suportadas. BRL é a moeda base de consolidação."""

    BRL = "BRL"
    USD = "USD"


@dataclass(frozen=True, slots=True, order=False)
class Money:
    """Quantia em uma moeda.

    Nunca usa `float`: preço médio, custo e saldo exigem aritmética decimal exata
    (0.1 + 0.2 em float não é 0.3). A precisão completa é mantida nos cálculos e só é
    arredondada para centavos na exibição (`rounded`).

    Attributes:
        amount: Quantia em `Decimal`.
        currency: Moeda da quantia.
    """

    amount: Decimal
    currency: Currency = Currency.BRL

    def __post_init__(self) -> None:
        # Recusa float/int para impedir que imprecisão binária entre no domínio.
        if not isinstance(self.amount, Decimal):
            raise TypeError("Money.amount deve ser Decimal.")
        if not self.amount.is_finite():
            raise DomainError("Valor monetário precisa ser finito.")

    @classmethod
    def zero(cls, currency: Currency = Currency.BRL) -> Money:
        return cls(Decimal("0"), currency)

    @classmethod
    def brl(cls, amount: Decimal | str | int) -> Money:
        """Atalho para reais. Aceita `str` para literais exatos, ex.: `Money.brl("29.30")`."""
        return cls(Decimal(amount), Currency.BRL)

    def _check_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"Moedas diferentes: {self.currency} e {other.currency}. Converta antes."
            )

    def __add__(self, other: Money) -> Money:
        self._check_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Decimal | int) -> Money:
        # Multiplicar por quantidade (Decimal) é o caso comum: preço x cotas.
        return Money(self.amount * Decimal(factor), self.currency)

    __rmul__ = __mul__

    def __truediv__(self, divisor: Decimal | int) -> Money:
        divisor = Decimal(divisor)
        if divisor == 0:
            raise DomainError("Divisão de valor monetário por zero.")
        return Money(self.amount / divisor, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._check_same_currency(other)
        return self.amount <= other.amount

    def is_negative(self) -> bool:
        return self.amount < 0

    def rounded(self) -> Money:
        """Arredonda para centavos (meio para cima, como o mercado brasileiro exibe)."""
        return Money(self.amount.quantize(CENTS, rounding=ROUND_HALF_UP), self.currency)
