"""DTOs de otimização e sugestão de aporte."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from domain.value_objects.asset_class import AssetClass


class OptimizationRequest(BaseModel):
    portfolio_id: str = Field(min_length=1)
    lookback_years: int = Field(default=3, ge=1, le=25)
    include_fixed_income: bool = False
    frontier_points: int = Field(default=25, ge=2, le=100)
    allow_short: bool = False


class PortfolioPointDTO(BaseModel):
    """Uma carteira no plano risco x retorno (frações anuais)."""

    label: str
    expected_return: float
    volatility: float
    sharpe: float | None
    weights: dict[str, float]


class AssetPointDTO(BaseModel):
    ticker: str
    expected_return: float
    volatility: float


class OptimizationResult(BaseModel):
    tickers: list[str]
    start: date
    end: date
    observations: int
    risk_free_rate: float
    current: PortfolioPointDTO
    min_variance: PortfolioPointDTO
    max_sharpe: PortfolioPointDTO
    risk_parity: PortfolioPointDTO | None
    frontier: list[PortfolioPointDTO]
    assets: list[AssetPointDTO]
    correlation: list[list[float]]
    excluded: list[str]
    warnings: list[str]


class ContributionRequest(BaseModel):
    portfolio_id: str = Field(min_length=1)
    amount: Decimal = Field(ge=0)
    allow_sales: bool = False


class ClassAllocationRow(BaseModel):
    """Delta da classe: atual vs. alvo, e o que fazer."""

    asset_class: AssetClass
    current_value: Decimal
    current_pct: float
    target_pct: float
    target_value: Decimal
    delta_value: Decimal  # alvo - atual (positivo = falta)
    contribution: Decimal
    sale: Decimal
    final_value: Decimal
    final_pct: float


class ContributionPlan(BaseModel):
    rows: list[ClassAllocationRow]
    total_before: Decimal
    total_after: Decimal
    missing_prices: list[str]
