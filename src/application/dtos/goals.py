"""DTOs dos objetivos de poupança."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from domain.entities.savings_goal import GoalFrequency, GoalMode


class GoalPlanRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    target: Decimal = Field(gt=0)
    mode: GoalMode = GoalMode.PROGRESSIVE
    frequency: GoalFrequency = GoalFrequency.DAILY
    start_date: date
    end_date: date
    # Valor do passo no modo progressivo (R$ 1 -> depósitos de 1, 2, 3... reais).
    unit: Decimal = Field(default=Decimal("1"), gt=0)


class GoalDTO(BaseModel):
    id: str | None
    name: str
    mode: GoalMode
    frequency: GoalFrequency
    unit_amount: Decimal
    step_count: int
    total: Decimal
    first_step_amount: Decimal
    last_step_amount: Decimal
    start_date: date
    end_date: date
    period_count: int


class DepositRow(BaseModel):
    step: int
    amount: Decimal
    deposited_on: date


class GoalDashboard(BaseModel):
    goal: GoalDTO
    saved: Decimal
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
    pending_steps: list[int]
    deposits: list[DepositRow]
    active_dates: list[date]


class RegisterDepositRequest(BaseModel):
    user_id: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    step: int = Field(ge=1)
    deposited_on: date
