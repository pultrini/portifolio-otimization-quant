"""DTOs de otimização e sugestão de aporte."""

from datetime import date
from decimal import Decimal
from typing import Literal

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


Objective = Literal["max_sharpe", "min_variance"]


class QuantSimulationRequest(BaseModel):
    """Simulação da melhor carteira quant com os ativos possíveis (carteira + desejos)."""

    portfolio_id: str = Field(min_length=1)
    tickers: list[str] | None = None  # None = todos os ativos da carteira e da lista de desejos
    lookback_years: int = Field(default=3, ge=1, le=25)
    objective: Objective = "max_sharpe"
    respect_targets: bool = True  # peso de cada classe = perfil alvo do usuário
    include_fixed_income: bool = False  # só vale quando respect_targets é False
    max_weight: float = Field(default=0.25, gt=0, le=1)
    contribution: Decimal = Field(default=Decimal(0), ge=0)


class SimulatedAssetRow(BaseModel):
    ticker: str
    asset_class: AssetClass
    in_watchlist: bool
    expected_return: float
    volatility: float
    current_weight: float
    weight: float
    risk_contribution: float | None
    price: Decimal
    current_quantity: Decimal
    current_value: Decimal
    target_value: Decimal
    target_quantity: Decimal  # em lotes negociáveis
    fractional: bool  # lote < 1 (CDI, Tesouro, cripto): a diferença é lida em R$
    delta_quantity: Decimal  # positivo = comprar, negativo = vender

    @property
    def delta_value(self) -> Decimal:
        return self.delta_quantity * self.price


class SimulatedClassRow(BaseModel):
    asset_class: AssetClass
    current_weight: float
    weight: float
    target_pct: float | None  # alvo do perfil (None quando a simulação ignora o perfil)


class QuantSimulationResult(BaseModel):
    start: date
    end: date
    observations: int
    risk_free_rate: float
    objective: Objective
    max_weight: float
    simulated: PortfolioPointDTO
    current: PortfolioPointDTO | None
    base_value: Decimal  # valor dos ativos simulados + aporte
    rows: list[SimulatedAssetRow]
    classes: list[SimulatedClassRow]
    dates: list[date]
    simulated_growth: list[float]
    current_growth: list[float] | None
    excluded: dict[str, str]
    warnings: list[str]
