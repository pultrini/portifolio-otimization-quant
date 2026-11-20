"""Use cases: otimização da carteira e sugestão de aporte por classe."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

from application.dtos.optimization import (
    AssetPointDTO,
    ClassAllocationRow,
    ContributionPlan,
    ContributionRequest,
    OptimizationRequest,
    OptimizationResult,
    PortfolioPointDTO,
)
from domain.entities.allocation_profile import AllocationProfile
from domain.exceptions import DomainError, MissingMarketDataError
from domain.repositories.market_data_repository import MarketDataRepository
from domain.repositories.portfolio_repository import PortfolioRepository
from domain.repositories.position_repository import PositionRepository
from domain.services.optimization import (
    AssetUniverse,
    PortfolioPoint,
    efficient_frontier,
    evaluate,
    max_sharpe,
    min_variance,
    risk_parity,
)
from domain.services.performance import index_returns_on
from domain.services.rebalancing import suggest_contribution
from domain.value_objects.asset_class import CDI, TRADING_DAYS_PER_YEAR, AssetClass
from domain.value_objects.money import Money
from domain.value_objects.ticker import Ticker

_FIXED_INCOME = {AssetClass.BR_FIXED_INCOME, AssetClass.INTL_FIXED_INCOME}
_HUNDRED = Decimal("100")


def _point(label: str, point: PortfolioPoint, tickers: tuple[str, ...]) -> PortfolioPointDTO:
    return PortfolioPointDTO(
        label=label,
        expected_return=point.expected_return,
        volatility=point.volatility,
        sharpe=point.sharpe,
        weights={t: float(w) for t, w in zip(tickers, point.weights, strict=True)},
    )


class OptimizePortfolio:
    """Fronteira eficiente, mínima variância, máximo Sharpe e Risk Parity dos ativos da carteira.

    Por padrão a renda fixa fica de fora: CDI e Tesouro têm volatilidade quase nula e
    dominariam qualquer otimização por risco, escondendo a decisão entre os ativos de
    risco. O usuário pode incluí-la.
    """

    def __init__(
        self,
        positions: PositionRepository,
        market_data: MarketDataRepository,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._positions = positions
        self._market_data = market_data
        self._today = today

    def execute(self, request: OptimizationRequest) -> OptimizationResult:
        """Estima μ e Σ no período e resolve as carteiras ótimas.

        Raises:
            DomainError: menos de 2 ativos elegíveis, histórico insuficiente ou falha
                de convergência.
        """
        open_positions = [
            p for p in self._positions.list_positions(request.portfolio_id) if not p.is_closed
        ]
        eligible = [
            p
            for p in open_positions
            if request.include_fixed_income or p.asset_class not in _FIXED_INCOME
        ]
        excluded = sorted(p.ticker.symbol for p in open_positions if p not in eligible)
        if len(eligible) < 2:
            raise DomainError("A otimização precisa de ao menos 2 ativos elegíveis na carteira.")

        start = self._today() - timedelta(days=365 * request.lookback_years)
        tickers = [p.ticker for p in eligible]
        history = self._market_data.price_history(tickers, start)
        if len(history) < 30:
            raise MissingMarketDataError(
                "Menos de 30 datas em comum entre os ativos; atualize os dados de mercado."
            )
        # Datas alinhadas no calendário da B3 (interseção com os demais): base 252.
        universe = AssetUniverse.from_history(history, TRADING_DAYS_PER_YEAR)

        # Taxa livre de risco anual: CDI acumulado no mesmo período, anualizado.
        rf_history = self._market_data.price_history([Ticker(CDI)], start - timedelta(days=15))
        rf_returns = index_returns_on(history.dates, rf_history, CDI)
        risk_free = float(
            np.prod(1.0 + rf_returns) ** (TRADING_DAYS_PER_YEAR / rf_returns.size) - 1
        )

        # Pesos atuais pelo valor de mercado no último preço do período.
        last_prices = history.prices[-1]
        quantities = np.array([float(p.quantity) for p in eligible])
        values = last_prices * quantities
        current_weights = values / values.sum()

        warnings: list[str] = []
        try:
            parity: PortfolioPointDTO | None = _point(
                "Risk Parity", risk_parity(universe, risk_free), universe.tickers
            )
        except DomainError as error:
            parity = None
            warnings.append(str(error))

        frontier = efficient_frontier(
            universe, risk_free, request.frontier_points, request.allow_short
        )
        return OptimizationResult(
            tickers=list(universe.tickers),
            start=history.dates[0],
            end=history.dates[-1],
            observations=len(history) - 1,
            risk_free_rate=risk_free,
            current=_point(
                "Carteira atual", evaluate(universe, current_weights, risk_free), universe.tickers
            ),
            min_variance=_point(
                "Mínima variância",
                min_variance(universe, risk_free, request.allow_short),
                universe.tickers,
            ),
            max_sharpe=_point(
                "Máximo Sharpe",
                max_sharpe(universe, risk_free, request.allow_short),
                universe.tickers,
            ),
            risk_parity=parity,
            frontier=[_point("Fronteira", p, universe.tickers) for p in frontier],
            assets=[
                AssetPointDTO(ticker=t, expected_return=float(mu), volatility=float(vol))
                for t, mu, vol in zip(
                    universe.tickers,
                    universe.expected_returns,
                    universe.volatilities,
                    strict=True,
                )
            ],
            correlation=universe.correlation().tolist(),
            excluded=excluded,
            warnings=warnings,
        )


class SuggestContribution:
    """Delta da alocação atual vs. alvo por classe, com sugestão de aporte."""

    def __init__(
        self,
        portfolios: PortfolioRepository,
        positions: PositionRepository,
        market_data: MarketDataRepository,
    ) -> None:
        self._portfolios = portfolios
        self._positions = positions
        self._market_data = market_data

    def execute(self, request: ContributionRequest) -> ContributionPlan:
        """Valoriza as posições por classe e distribui o aporte.

        Raises:
            DomainError: perfil de alocação não definido ou inválido.
        """
        saved = self._portfolios.get_allocation_targets(request.portfolio_id)
        if not saved:
            raise DomainError("Defina o perfil de alocação alvo antes de pedir sugestões.")
        profile = AllocationProfile(
            {AssetClass(key): Decimal(str(value)) for key, value in saved.items()}
        )

        positions = [
            p for p in self._positions.list_positions(request.portfolio_id) if not p.is_closed
        ]
        prices = self._market_data.latest_prices([p.ticker for p in positions])
        missing = sorted(p.ticker.symbol for p in positions if p.ticker not in prices)
        current: dict[AssetClass, Money] = {}
        for position in positions:
            price = prices.get(position.ticker)
            if price is None:
                continue
            current[position.asset_class] = (
                current.get(position.asset_class, Money.zero()) + price * position.quantity
            )

        plan = suggest_contribution(
            current, profile, Money.brl(request.amount), request.allow_sales
        )
        before = plan.total_before.amount
        after = plan.total_after.amount

        def pct(value: Decimal, total: Decimal) -> float:
            return float(value / total * _HUNDRED) if total else 0.0

        rows = [
            ClassAllocationRow(
                asset_class=c.asset_class,
                current_value=c.current_value.rounded().amount,
                current_pct=pct(c.current_value.amount, before),
                target_pct=float(c.target_pct),
                target_value=c.target_value.amount,
                delta_value=(c.target_value - c.current_value).rounded().amount,
                contribution=c.contribution.amount,
                sale=c.sale.amount,
                final_value=c.final_value.rounded().amount,
                final_pct=pct(c.final_value.amount, after),
            )
            for c in plan.classes
        ]
        return ContributionPlan(
            rows=rows,
            total_before=plan.total_before.rounded().amount,
            total_after=plan.total_after.rounded().amount,
            missing_prices=missing,
        )
