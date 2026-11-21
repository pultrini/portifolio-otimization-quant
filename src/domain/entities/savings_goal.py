"""Objetivo de poupança com foco em constância (desafio progressivo ou valor fixo)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from domain.exceptions import DomainError
from domain.value_objects.money import Money

MAX_NAME_LENGTH = 80


class GoalMode(StrEnum):
    """PROGRESSIVE: depósitos 1, 2, 3, ..., N vezes o passo. FIXED: N depósitos iguais."""

    PROGRESSIVE = "PROGRESSIVE"
    FIXED = "FIXED"

    @property
    def label_pt(self) -> str:
        return "Progressivo (1, 2, 3...)" if self is GoalMode.PROGRESSIVE else "Valor fixo"


class GoalFrequency(StrEnum):
    """Unidade de constância: um depósito por dia ou por semana."""

    DAILY = "DAILY"
    WEEKLY = "WEEKLY"

    @property
    def days(self) -> int:
        return 1 if self is GoalFrequency.DAILY else 7

    @property
    def label_pt(self) -> str:
        return "Diária" if self is GoalFrequency.DAILY else "Semanal"


@dataclass(frozen=True, slots=True)
class SavingsGoal:
    """Meta dividida em N passos numerados.

    No modo progressivo o passo k vale k x unidade (o desafio "1, 2, 3... 282 reais");
    no modo fixo todo passo vale a unidade. Os passos podem ser feitos em qualquer
    ordem: o que se mede é a constância (um passo por período), não o valor.

    Attributes:
        unit_amount: Valor do passo 1 (progressivo) ou de todo passo (fixo).
        step_count: N, quantidade de depósitos.
    """

    name: str
    mode: GoalMode
    frequency: GoalFrequency
    unit_amount: Money
    step_count: int
    start_date: date
    end_date: date
    id: str | None = None

    def __post_init__(self) -> None:
        if not 1 <= len(self.name.strip()) <= MAX_NAME_LENGTH:
            raise DomainError(f"Nome do objetivo deve ter entre 1 e {MAX_NAME_LENGTH} caracteres.")
        if self.step_count < 1:
            raise DomainError("O objetivo precisa de ao menos um depósito.")
        if self.unit_amount.amount <= 0:
            raise DomainError("O valor do passo precisa ser positivo.")
        if self.end_date < self.start_date:
            raise DomainError("A data final precisa ser depois da inicial.")

    def step_amount(self, step: int) -> Money:
        if not 1 <= step <= self.step_count:
            raise DomainError(f"Passo {step} fora de 1 a {self.step_count}.")
        if self.mode is GoalMode.PROGRESSIVE:
            return self.unit_amount * step
        return self.unit_amount

    @property
    def total(self) -> Money:
        """Valor ao completar todos os passos.

        Progressivo: unidade x N(N+1)/2 (soma 1 + 2 + ... + N). Fixo: unidade x N.
        """
        n = self.step_count
        if self.mode is GoalMode.PROGRESSIVE:
            return self.unit_amount * Decimal(n * (n + 1) // 2)
        return self.unit_amount * n

    @property
    def period_count(self) -> int:
        """Quantos períodos (dias ou semanas) cabem entre o início e o fim, inclusive."""
        return (self.end_date - self.start_date).days // self.frequency.days + 1


@dataclass(frozen=True, slots=True)
class GoalDeposit:
    step: int
    amount: Money
    deposited_on: date
