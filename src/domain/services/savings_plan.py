"""Planejamento e acompanhamento de objetivos de poupança (constância)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_UP, Decimal

from domain.entities.savings_goal import GoalDeposit, GoalFrequency, GoalMode, SavingsGoal
from domain.exceptions import DomainError
from domain.value_objects.money import CENTS, Money


def progressive_steps_for(target: Decimal, unit: Decimal = Decimal("1")) -> int:
    """N do desafio progressivo cuja soma unidade x N(N+1)/2 fica mais perto da meta.

    Resolve N(N+1)/2 = meta/unidade pela fórmula de Bhaskara e compara os dois
    inteiros vizinhos; no empate, fica o menor (menos depósitos).
    Ex.: meta R$ 40.000, passo R$ 1 -> N = 282 (soma R$ 39.903).
    """
    if target <= 0 or unit <= 0:
        raise DomainError("Meta e passo precisam ser positivos.")
    units = float(target / unit)
    root = (math.sqrt(8 * units + 1) - 1) / 2
    candidates = {max(1, math.floor(root)), max(1, math.ceil(root))}
    return min(candidates, key=lambda n: (abs(n * (n + 1) / 2 - units), n))


def plan_goal(
    name: str,
    target: Money,
    mode: GoalMode,
    frequency: GoalFrequency,
    start: date,
    end: date,
    unit: Money | None = None,
) -> SavingsGoal:
    """Monta o objetivo a partir da meta.

    Progressivo: N = `progressive_steps_for(meta, passo)` (passo padrão R$ 1).
    Fixo: N = quantidade de períodos até a data final; cada depósito = meta / N
    (arredondado para cima em centavos, para não terminar abaixo da meta).

    Raises:
        DomainError: prazo menor que a quantidade de depósitos necessária.
    """
    if end < start:
        raise DomainError("A data final precisa ser depois da inicial.")
    periods = (end - start).days // frequency.days + 1
    if mode is GoalMode.PROGRESSIVE:
        step_unit = unit or Money.brl("1")
        steps = progressive_steps_for(target.amount, step_unit.amount)
    else:
        steps = periods
        step_unit = Money.brl((target.amount / steps).quantize(CENTS, rounding=ROUND_UP))
    if steps > periods:
        unit_label = "dias" if frequency is GoalFrequency.DAILY else "semanas"
        raise DomainError(
            f"São {steps} depósitos para {periods} {unit_label} de prazo. "
            "Aumente o prazo ou o valor do passo."
        )
    return SavingsGoal(name.strip(), mode, frequency, step_unit, steps, start, end)


@dataclass(frozen=True, slots=True)
class ConsistencyReport:
    """Situação do objetivo com foco em constância.

    Attributes:
        consistency_rate: períodos com depósito / períodos decorridos (0 a 1).
        current_streak: períodos seguidos com depósito até agora (o período atual ainda
            sem depósito não quebra a sequência).
        required_per_period: passos que faltam / períodos que faltam.
    """

    saved: Money
    progress: float
    completed_steps: int
    remaining_steps: int
    elapsed_periods: int
    active_periods: int
    consistency_rate: float | None
    current_streak: int
    longest_streak: int
    remaining_periods: int
    required_per_period: float | None
    on_track: bool
    next_step: int | None
    active_dates: tuple[date, ...]


def period_index(goal: SavingsGoal, day: date) -> int:
    return (day - goal.start_date).days // goal.frequency.days


def consistency(
    goal: SavingsGoal, deposits: Sequence[GoalDeposit], today: date
) -> ConsistencyReport:
    """Calcula progresso, constância e sequência de um objetivo.

    Fórmulas:
        constância = períodos com ao menos um depósito / períodos decorridos
        sequência atual = períodos consecutivos com depósito terminando no período atual
            (ou no anterior, se o atual ainda não teve depósito)
        ritmo necessário = passos restantes / períodos restantes (inclui o atual)
        no ritmo = passos restantes <= períodos restantes
    """
    saved = sum((d.amount for d in deposits), Money.zero())
    done = {d.step for d in deposits}
    remaining = goal.step_count - len(done)
    reference = min(max(today, goal.start_date), goal.end_date)
    current = period_index(goal, reference)
    elapsed = current + 1 if today >= goal.start_date else 0
    active = {
        period_index(goal, d.deposited_on) for d in deposits if d.deposited_on >= goal.start_date
    }

    streak = 0
    cursor = current if current in active else current - 1
    while cursor in active:
        streak += 1
        cursor -= 1

    longest = run = 0
    for index in range(0, max(active, default=-1) + 1):
        run = run + 1 if index in active else 0
        longest = max(longest, run)

    # Períodos ainda disponíveis para depositar, contando o atual só se ele ainda não
    # teve depósito (a constância é de um passo por período).
    if today > goal.end_date:
        remaining_periods = 0
    else:
        remaining_periods = goal.period_count - current - (1 if current in active else 0)
    total = goal.total.amount
    return ConsistencyReport(
        saved=saved,
        progress=float(saved.amount / total) if total else 0.0,
        completed_steps=len(done),
        remaining_steps=remaining,
        elapsed_periods=elapsed,
        active_periods=len({p for p in active if p <= current}),
        consistency_rate=(len({p for p in active if p <= current}) / elapsed) if elapsed else None,
        current_streak=streak,
        longest_streak=longest,
        remaining_periods=remaining_periods,
        required_per_period=(remaining / remaining_periods) if remaining_periods else None,
        on_track=remaining <= remaining_periods,
        next_step=min((s for s in range(1, goal.step_count + 1) if s not in done), default=None),
        active_dates=tuple(sorted({d.deposited_on for d in deposits})),
    )


def default_end(start: date) -> date:
    """Prazo padrão de um ano (meta anual)."""
    return start + timedelta(days=364)
