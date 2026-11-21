"""Testes dos use cases de objetivos de poupança."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from application.dtos.goals import GoalPlanRequest, RegisterDepositRequest
from application.use_cases.goals import (
    CreateGoal,
    DeleteGoal,
    GetGoalDashboard,
    ListGoals,
    PreviewGoal,
    RegisterDeposit,
    UndoDeposit,
)
from domain.entities.savings_goal import GoalFrequency, GoalMode
from domain.exceptions import DomainError
from tests.fakes.in_memory_repositories import InMemorySavingsGoalRepository

START = date(2026, 1, 1)
REQUEST = GoalPlanRequest(
    name="Reserva 40k",
    target=Decimal("40000"),
    mode=GoalMode.PROGRESSIVE,
    frequency=GoalFrequency.DAILY,
    start_date=START,
    end_date=START + timedelta(days=364),
)


def test_previa_do_desafio() -> None:
    preview = PreviewGoal().execute(REQUEST)
    assert preview.step_count == 282
    assert preview.total == Decimal("39903")
    assert (preview.first_step_amount, preview.last_step_amount) == (Decimal("1"), Decimal("282"))
    assert preview.id is None


def test_fluxo_completo() -> None:
    repo = InMemorySavingsGoalRepository()
    goal = CreateGoal(repo).execute("u", REQUEST)
    assert goal.id is not None
    assert [g.name for g in ListGoals(repo).execute()] == ["Reserva 40k"]

    register = RegisterDeposit(repo)
    for step, day in ((1, 0), (282, 1), (10, 2)):
        register.execute(
            RegisterDepositRequest(
                user_id="u", goal_id=goal.id, step=step, deposited_on=START + timedelta(days=day)
            )
        )
    with pytest.raises(DomainError, match="já foi depositado"):
        register.execute(
            RegisterDepositRequest(user_id="u", goal_id=goal.id, step=10, deposited_on=START)
        )

    dashboard = GetGoalDashboard(repo, today=lambda: START + timedelta(days=2)).execute(goal.id)
    assert dashboard.saved == Decimal("293")  # 1 + 282 + 10
    assert dashboard.completed_steps == 3
    assert dashboard.current_streak == 3
    assert dashboard.consistency_rate == pytest.approx(1.0)
    assert dashboard.next_step == 2
    assert 10 not in dashboard.pending_steps
    assert dashboard.deposits[0].step == 10  # mais recente primeiro
    assert dashboard.on_track

    UndoDeposit(repo).execute(goal.id, 282)
    after = GetGoalDashboard(repo, today=lambda: START + timedelta(days=2)).execute(goal.id)
    assert after.saved == Decimal("11")
    # Sobram depósitos nos dias 0 e 2: o dia 1 vazio quebra a sequência (fica só o dia 2).
    assert after.current_streak == 1
    assert after.consistency_rate == pytest.approx(2 / 3)

    DeleteGoal(repo).execute(goal.id)
    assert ListGoals(repo).execute() == []


def test_deposito_antes_do_inicio() -> None:
    repo = InMemorySavingsGoalRepository()
    goal = CreateGoal(repo).execute("u", REQUEST)
    assert goal.id is not None
    with pytest.raises(DomainError, match="anterior ao início"):
        RegisterDeposit(repo).execute(
            RegisterDepositRequest(
                user_id="u", goal_id=goal.id, step=1, deposited_on=START - timedelta(days=1)
            )
        )
