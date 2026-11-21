"""Objetivos de poupança no Supabase (`savings_goals` e `goal_deposits`, com RLS)."""

from datetime import date
from typing import Any, cast

from supabase import Client

from domain.entities.savings_goal import GoalDeposit, GoalFrequency, GoalMode, SavingsGoal
from domain.repositories.savings_goal_repository import SavingsGoalRepository
from domain.value_objects.money import Money

_GOAL_COLUMNS = "id, name, mode, frequency, unit_amount::text, step_count, start_date, end_date"


def _rows(data: Any) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], data)


def _to_goal(row: dict[str, Any]) -> SavingsGoal:
    return SavingsGoal(
        name=str(row["name"]),
        mode=GoalMode(str(row["mode"])),
        frequency=GoalFrequency(str(row["frequency"])),
        unit_amount=Money.brl(str(row["unit_amount"])),
        step_count=int(row["step_count"]),
        start_date=date.fromisoformat(str(row["start_date"])),
        end_date=date.fromisoformat(str(row["end_date"])),
        id=str(row["id"]),
    )


class SupabaseSavingsGoalRepository(SavingsGoalRepository):
    def __init__(self, client: Client) -> None:
        self._client = client

    def list_goals(self) -> list[SavingsGoal]:
        response = (
            self._client.table("savings_goals").select(_GOAL_COLUMNS).order("created_at").execute()
        )
        return [_to_goal(row) for row in _rows(response.data)]

    def create_goal(self, user_id: str, goal: SavingsGoal) -> SavingsGoal:
        response = (
            self._client.table("savings_goals")
            .insert(
                {
                    "user_id": user_id,
                    "name": goal.name,
                    "mode": goal.mode.value,
                    "frequency": goal.frequency.value,
                    "unit_amount": str(goal.unit_amount.amount),
                    "step_count": goal.step_count,
                    "start_date": goal.start_date.isoformat(),
                    "end_date": goal.end_date.isoformat(),
                }
            )
            .execute()
        )
        row = _rows(response.data)[0]
        row["unit_amount"] = str(goal.unit_amount.amount)
        return _to_goal(row)

    def delete_goal(self, goal_id: str) -> None:
        # Os depósitos saem junto (on delete cascade).
        self._client.table("savings_goals").delete().eq("id", goal_id).execute()

    def list_deposits(self, goal_id: str) -> list[GoalDeposit]:
        response = (
            self._client.table("goal_deposits")
            .select("step, amount::text, deposited_on")
            .eq("goal_id", goal_id)
            .order("deposited_on")
            .execute()
        )
        return [
            GoalDeposit(
                step=int(row["step"]),
                amount=Money.brl(str(row["amount"])),
                deposited_on=date.fromisoformat(str(row["deposited_on"])),
            )
            for row in _rows(response.data)
        ]

    def add_deposit(self, user_id: str, goal_id: str, deposit: GoalDeposit) -> None:
        self._client.table("goal_deposits").insert(
            {
                "user_id": user_id,
                "goal_id": goal_id,
                "step": deposit.step,
                "amount": str(deposit.amount.amount),
                "deposited_on": deposit.deposited_on.isoformat(),
            }
        ).execute()

    def remove_deposit(self, goal_id: str, step: int) -> None:
        self._client.table("goal_deposits").delete().eq("goal_id", goal_id).eq(
            "step", step
        ).execute()
