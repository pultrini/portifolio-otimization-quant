"""DTOs da decisão de aporte por ativo (quant + checklist) e do botão "Aportar"."""

from decimal import Decimal

from pydantic import BaseModel, Field

from application.dtos.optimization import ContributionPlan
from domain.services.contribution_decision import Decision
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.checklist import AnswerSource, ChecklistKind
from domain.value_objects.strategy_type import StrategyType


class ChecklistQuestionRow(BaseModel):
    key: str
    title: str
    text: str
    auto_answer: bool | None = None
    evidence: str = ""
    manual_answer: bool | None = None
    answer: bool | None = None  # vale a manual; sem manual, a automática
    source: AnswerSource | None = None


class ChecklistView(BaseModel):
    ticker: str
    kind: ChecklistKind
    questions: list[ChecklistQuestionRow]
    yes: int
    no: int
    answered: int
    total: int
    # Nota de 0 a 1 com os pesos de Sim/Não do usuário (ChecklistWeights.score).
    score: float


class ChecklistWeightsDTO(BaseModel):
    """Postura do usuário no checklist: peso de cada Sim e de cada Não."""

    yes: float = Field(default=1.0, gt=0, le=3)
    no: float = Field(default=0.0, ge=0, le=5)


class SaveChecklistWeightsRequest(BaseModel):
    user_id: str = Field(min_length=1)
    weights: ChecklistWeightsDTO


class SaveChecklistRequest(BaseModel):
    user_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    kind: ChecklistKind
    answers: dict[str, bool | None]


class AssetDecisionRow(BaseModel):
    ticker: str
    asset_class: AssetClass
    in_watchlist: bool
    price: Decimal | None
    current_value: Decimal
    quant_score: float | None
    checklist_score: float | None
    final_score: float | None
    ideal_weight_pct: float
    target_value: Decimal
    quantity: Decimal
    amount: Decimal
    decision: Decision
    reason: str
    checklist: ChecklistView | None = None


class ClassDecisionDTO(BaseModel):
    asset_class: AssetClass
    budget: Decimal
    leftover: Decimal
    uses_checklist: bool
    rows: list[AssetDecisionRow]


class BuyOrder(BaseModel):
    ticker: str
    asset_class: AssetClass
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)

    @property
    def amount(self) -> Decimal:
        return self.quantity * self.price


class AssetContributionRequest(BaseModel):
    portfolio_id: str = Field(min_length=1)
    amount: Decimal = Field(ge=0)
    allow_sales: bool = False
    quant_weight: float = Field(default=0.5, ge=0, le=1)
    lookback_years: int = Field(default=3, ge=1, le=10)


class AssetContributionResult(BaseModel):
    plan: ContributionPlan
    classes: list[ClassDecisionDTO]
    orders: list[BuyOrder]
    leftover: Decimal


class ExecuteContributionRequest(BaseModel):
    user_id: str = Field(min_length=1)
    portfolio_id: str = Field(min_length=1)
    orders: list[BuyOrder]
    strategy: StrategyType = StrategyType.BUY_AND_HOLD


class ExecuteContributionResult(BaseModel):
    registered: list[str]
    errors: list[str]
