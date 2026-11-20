"""Percentual em pontos percentuais (0 a 100)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from domain.exceptions import DomainError

HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True, order=True)
class Percentage:
    """Percentual entre 0 e 100, em `Decimal`.

    Guardado em pontos percentuais (60 = 60%) porque é assim que o usuário digita e
    como o banco persiste (`numeric(5,2)`). `as_fraction` devolve 0.60 para cálculos.
    """

    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise TypeError("Percentage.value deve ser Decimal.")
        if not Decimal("0") <= self.value <= HUNDRED:
            raise DomainError(f"Percentual fora de 0-100: {self.value}.")

    @classmethod
    def of(cls, value: Decimal | str | int) -> Percentage:
        return cls(Decimal(value))

    @property
    def as_fraction(self) -> Decimal:
        return self.value / HUNDRED
