"""Use cases dos objetivos de poupança (constância acima de valor)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from application.dtos.goals import (
    DepositRow,
    GoalDashboard,
    GoalDTO,
    GoalPlanRequest,
    RegisterDepositRequest,
)
from domain.entities.savings_goal import GoalDeposit, SavingsGoal
from domain.exceptions import DomainError
from domain.repositories.savings_goal_repository import SavingsGoalRepository
from domain.services.savings_plan import consistency, plan_goal
from domain.value_objects.money import Money


def _to_dto(goal: SavingsGoal) -> GoalDTO:
    return GoalDTO(
        id=goal.id,
        name=goal.name,
        mode=goal.mode,
        frequency=goal.frequency,
        unit_amount=goal.unit_amount.amount,
        step_count=goal.step_count,
        total=goal.total.amount,
        first_step_amount=goal.step_amount(1).amount,
        last_step_amount=goal.step_amount(goal.step_count).amount,
        start_date=goal.start_date,
        end_date=goal.end_date,
        period_count=goal.period_count,
    )


def _plan(request: GoalPlanRequest) -> SavingsGoal:
    return plan_goal(
        request.name,
        Money.brl(request.target),
        request.mode,
        request.frequency,
        request.start_date,
        request.end_date,
        Money.brl(request.unit),
    )


class PreviewGoal:
    """Mostra o plano (quantos depósitos, de quanto) antes de salvar."""

    def execute(self, request: GoalPlanRequest) -> GoalDTO:
        return _to_dto(_plan(request))


class CreateGoal:
    def __init__(self, goals: SavingsGoalRepository) -> None:
        self._goals = goals

    def execute(self, user_id: str, request: GoalPlanRequest) -> GoalDTO:
        return _to_dto(self._goals.create_goal(user_id, _plan(request)))


class ListGoals:
    def __init__(self, goals: SavingsGoalRepository) -> None:
        self._goals = goals

    def execute(self) -> list[GoalDTO]:
        return [_to_dto(goal) for goal in self._goals.list_goals()]


class DeleteGoal:
    def __init__(self, goals: SavingsGoalRepository) -> None:
        self._goals = goals

    def execute(self, goal_id: str) -> None:
        self._goals.delete_goal(goal_id)


def _find(goals: SavingsGoalRepository, goal_id: str) -> SavingsGoal:
    for goal in goals.list_goals():
        if goal.id == goal_id:
            return goal
    raise DomainError("Objetivo não encontrado.")


class GetGoalDashboard:
    """Progresso e constância de um objetivo."""

    def __init__(
        self, goals: SavingsGoalRepository, today: Callable[[], date] = date.today
    ) -> None:
        self._goals = goals
        self._today = today

    def execute(self, goal_id: str) -> GoalDashboard:
        goal = _find(self._goals, goal_id)
        deposits = self._goals.list_deposits(goal_id)
        report = consistency(goal, deposits, self._today())
        done = {d.step for d in deposits}
        return GoalDashboard(
            goal=_to_dto(goal),
            saved=report.saved.amount,
            progress=report.progress,
            completed_steps=report.completed_steps,
            remaining_steps=report.remaining_steps,
            elapsed_periods=report.elapsed_periods,
            active_periods=report.active_periods,
            consistency_rate=report.consistency_rate,
            current_streak=report.current_streak,
            longest_streak=report.longest_streak,
            remaining_periods=report.remaining_periods,
            required_per_period=report.required_per_period,
            on_track=report.on_track,
            next_step=report.next_step,
            pending_steps=[s for s in range(1, goal.step_count + 1) if s not in done],
            deposits=[
                DepositRow(step=d.step, amount=d.amount.amount, deposited_on=d.deposited_on)
                for d in sorted(deposits, key=lambda d: (d.deposited_on, d.step), reverse=True)
            ],
            active_dates=list(report.active_dates),
        )


class RegisterDeposit:
    """Marca um passo como depositado. O valor vem do passo, não é digitado."""

    def __init__(self, goals: SavingsGoalRepository) -> None:
        self._goals = goals

    def execute(self, request: RegisterDepositRequest) -> DepositRow:
        goal = _find(self._goals, request.goal_id)
        amount = goal.step_amount(request.step)
        if any(d.step == request.step for d in self._goals.list_deposits(request.goal_id)):
            raise DomainError(f"O passo {request.step} já foi depositado.")
        if request.deposited_on < goal.start_date:
            raise DomainError("A data do depósito é anterior ao início do objetivo.")
        deposit = GoalDeposit(request.step, amount, request.deposited_on)
        self._goals.add_deposit(request.user_id, request.goal_id, deposit)
        return DepositRow(
            step=deposit.step, amount=amount.amount, deposited_on=deposit.deposited_on
        )


class UndoDeposit:
    def __init__(self, goals: SavingsGoalRepository) -> None:
        self._goals = goals

    def execute(self, goal_id: str, step: int) -> None:
        self._goals.remove_deposit(goal_id, step)
