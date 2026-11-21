"""Contrato de persistência de objetivos de poupança."""

from typing import Protocol

from domain.entities.savings_goal import GoalDeposit, SavingsGoal


class SavingsGoalRepository(Protocol):
    def list_goals(self) -> list[SavingsGoal]:
        """Objetivos do usuário autenticado."""
        ...

    def create_goal(self, user_id: str, goal: SavingsGoal) -> SavingsGoal:
        """Cria e devolve o objetivo com o id gerado."""
        ...

    def delete_goal(self, goal_id: str) -> None: ...

    def list_deposits(self, goal_id: str) -> list[GoalDeposit]: ...

    def add_deposit(self, user_id: str, goal_id: str, deposit: GoalDeposit) -> None:
        """Marca um passo como depositado (falha se o passo já foi feito)."""
        ...

    def remove_deposit(self, goal_id: str, step: int) -> None:
        """Desfaz o depósito de um passo."""
        ...
