"""DTOs do relatório de métricas."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class SeriesDTO(BaseModel):
    """Série temporal pronta para gráfico."""

    dates: list[date] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)


class RiskReturnMetrics(BaseModel):
    """Métricas de um escopo. Frações (0.12 = 12%); None quando não se aplica."""

    cumulative_return: float | None = None
    cagr: float | None = None
    volatility: float | None = None
    max_drawdown: float | None = None
    var_95: float | None = None
    var_99: float | None = None
    cvar_95: float | None = None
    cvar_99: float | None = None
    parametric_var_95: float | None = None
    parametric_var_99: float | None = None
    parametric_cvar_95: float | None = None
    parametric_cvar_99: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    calmar: float | None = None
    beta: float | None = None


class TradeStatsDTO(BaseModel):
    """Eficiência operacional das operações fechadas (líquidas de custos)."""

    closed_trades: int = 0
    day_trades: int = 0
    win_rate: float | None = None
    payoff_ratio: float | None = None
    profit_factor: float | None = None
    expectancy: Decimal | None = None
    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    mean_return_per_trade: float | None = None
    unmatched_quantity: Decimal = Decimal("0")


ScopeKind = Literal["portfolio", "asset_class", "strategy"]


class ScopeReport(BaseModel):
    """Métricas de um recorte: carteira inteira, uma classe ou uma estratégia."""

    key: str
    label: str
    kind: ScopeKind
    benchmark: str
    risk_free: str
    periods_per_year: int
    start: date | None = None
    end: date | None = None
    observations: int = 0
    metrics: RiskReturnMetrics = Field(default_factory=RiskReturnMetrics)
    benchmark_metrics: RiskReturnMetrics = Field(default_factory=RiskReturnMetrics)
    equity: SeriesDTO = Field(default_factory=SeriesDTO)
    benchmark_equity: SeriesDTO = Field(default_factory=SeriesDTO)
    drawdown: SeriesDTO = Field(default_factory=SeriesDTO)
    trade_stats: TradeStatsDTO | None = None
    error: str | None = None


class MetricsRequest(BaseModel):
    portfolio_id: str = Field(min_length=1)
    lookback_years: int = Field(default=3, ge=1, le=25)
    include_parametric: bool = False


class MetricsReport(BaseModel):
    portfolio_id: str
    lookback_start: date
    scopes: list[ScopeReport]
