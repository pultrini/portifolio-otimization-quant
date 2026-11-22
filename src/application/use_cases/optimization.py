"""Use cases: otimização da carteira e sugestão de aporte por classe."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

import numpy as np

from application.dtos.optimization import (
    AssetPointDTO,
    ClassAllocationRow,
    ContributionPlan,
    ContributionRequest,
    OptimizationRequest,
    OptimizationResult,
    PortfolioPointDTO,
    QuantSimulationRequest,
    QuantSimulationResult,
    SimulatedAssetRow,
    SimulatedClassRow,
)
from domain.entities.allocation_profile import AllocationProfile
from domain.entities.position import Position
from domain.exceptions import DomainError, MissingMarketDataError
from domain.repositories.market_data_repository import MarketDataRepository
from domain.repositories.portfolio_repository import PortfolioRepository
from domain.repositories.position_repository import PositionRepository
from domain.services.contribution_decision import lot_size
from domain.services.optimization import (
    AssetUniverse,
    PortfolioPoint,
    efficient_frontier,
    evaluate,
    growth_curve,
    max_sharpe,
    min_variance,
    optimize_constrained,
    risk_contributions,
    risk_parity,
)
from domain.services.performance import index_returns_on
from domain.services.rebalancing import suggest_contribution
from domain.value_objects.asset_class import CDI, TRADING_DAYS_PER_YEAR, AssetClass
from domain.value_objects.money import Money
from domain.value_objects.price_history import PriceHistory
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
        risk_free = _annual_risk_free(self._market_data, history, start)

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


# Um ativo entra na simulação se o histórico dele cobre ao menos esta fração do período
# do ativo mais antigo: um ativo recém-listado encurtaria a janela de todos os outros.
_MIN_HISTORY_COVERAGE = 0.7


class SimulateQuantPortfolio:
    """Simula a melhor composição quant com os ativos possíveis (carteira + lista de desejos).

    Diferente de `OptimizePortfolio`, que olha só a carteira atual, aqui entram também os
    ativos desejados (0 cotas), e o resultado vem pronto para comparação: pesos, valores
    e quantidades em lotes para o patrimônio atual mais um aporte opcional.

    Com `respect_targets`, o peso de cada classe é o do perfil alvo do usuário e a
    otimização decide a composição dentro das classes. Sem ele, a otimização decide
    tudo (e a renda fixa fica de fora por padrão, porque com volatilidade quase nula
    dominaria a carteira).

    É uma simulação com médias históricas, não previsão nem recomendação.
    """

    def __init__(
        self,
        portfolios: PortfolioRepository,
        positions: PositionRepository,
        market_data: MarketDataRepository,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._portfolios = portfolios
        self._positions = positions
        self._market_data = market_data
        self._today = today

    def execute(self, request: QuantSimulationRequest) -> QuantSimulationResult:
        """Raises:
        DomainError: perfil ausente (com respect_targets), nenhum ativo elegível ou
            falha de convergência.
        """
        positions = self._positions.list_positions(request.portfolio_id)
        if request.tickers is not None:
            wanted = {t.strip().upper() for t in request.tickers}
            positions = [p for p in positions if p.ticker.symbol in wanted]
        excluded: dict[str, str] = {}
        warnings: list[str] = []

        targets = self._class_targets(request, positions, excluded)
        start = self._today() - timedelta(days=365 * request.lookback_years)
        eligible = self._with_history(
            [p for p in positions if p.ticker.symbol not in excluded], start, excluded
        )
        if not eligible:
            raise DomainError("Nenhum ativo com histórico suficiente para simular.")

        groups: list[str] | None = None
        group_targets: dict[str, float] | None = None
        if targets is not None:
            present = {p.asset_class for p in eligible}
            lost = sorted(
                (c for c in targets if c not in present and targets[c] > 0), key=lambda c: c.value
            )
            for asset_class in lost:
                target_text = f"{targets[asset_class]:.2f}".replace(".", ",")
                warnings.append(
                    f"Sem ativos com histórico em {asset_class.label_pt} (alvo {target_text}%): "
                    "o alvo foi redistribuído entre as demais classes, na mesma proporção."
                )
            kept = {c: v for c, v in targets.items() if c in present}
            total = sum(kept.values())
            if total <= 0:
                raise DomainError("Nenhuma classe do perfil alvo tem ativos para simular.")
            group_targets = {c.value: v / total for c, v in kept.items()}
            groups = [p.asset_class.value for p in eligible]

        history = self._market_data.price_history([p.ticker for p in eligible], start)
        if len(history) < 30:
            raise MissingMarketDataError(
                "Menos de 30 datas em comum entre os ativos; atualize os dados de mercado."
            )
        universe = AssetUniverse.from_history(history, TRADING_DAYS_PER_YEAR)
        risk_free = _annual_risk_free(self._market_data, history, start)
        point = optimize_constrained(
            universe, risk_free, request.objective, request.max_weight, groups, group_targets
        )

        prices = self._market_data.latest_prices([p.ticker for p in eligible])
        current_values = [
            p.quantity * prices[p.ticker].amount if p.ticker in prices else Decimal(0)
            for p in eligible
        ]
        held = sum(current_values, Decimal(0))
        current_weights = np.array([float(v / held) for v in current_values]) if held > 0 else None
        current_point = (
            evaluate(universe, current_weights, risk_free) if current_weights is not None else None
        )
        base_value = held + request.contribution
        if base_value <= 0:
            warnings.append(
                "Carteira sem valor nos ativos simulados: informe um aporte "
                "para ver as quantidades."
            )

        try:
            contributions: list[float | None] = list(
                map(float, risk_contributions(universe, point.weights))
            )
        except DomainError:
            contributions = [None] * len(eligible)

        rows: list[SimulatedAssetRow] = []
        for i, position in enumerate(eligible):
            price = prices[position.ticker].amount if position.ticker in prices else Decimal(0)
            weight = float(point.weights[i])
            target_value = (base_value * Decimal(str(weight))).quantize(Decimal("0.01"))
            step = lot_size(position.ticker, position.asset_class)
            target_quantity = (
                (target_value / price / step).to_integral_value(rounding=ROUND_DOWN) * step
                if price > 0
                else Decimal(0)
            )
            rows.append(
                SimulatedAssetRow(
                    ticker=position.ticker.symbol,
                    asset_class=position.asset_class,
                    in_watchlist=position.is_closed,
                    expected_return=float(universe.expected_returns[i]),
                    volatility=float(universe.volatilities[i]),
                    current_weight=float(current_weights[i])
                    if current_weights is not None
                    else 0.0,
                    weight=weight,
                    risk_contribution=contributions[i],
                    price=price,
                    current_quantity=position.quantity,
                    current_value=current_values[i],
                    target_value=target_value,
                    target_quantity=target_quantity,
                    fractional=step < 1,
                    delta_quantity=target_quantity - position.quantity,
                )
            )
        rows.sort(key=lambda r: (r.weight, r.current_weight), reverse=True)

        classes = sorted({r.asset_class for r in rows}, key=lambda c: c.value)
        class_rows = [
            SimulatedClassRow(
                asset_class=c,
                current_weight=sum(r.current_weight for r in rows if r.asset_class is c),
                weight=sum(r.weight for r in rows if r.asset_class is c),
                target_pct=targets.get(c) if targets is not None else None,
            )
            for c in classes
        ]

        returns = history.simple_returns()
        label = "Máximo Sharpe" if request.objective == "max_sharpe" else "Mínima variância"
        return QuantSimulationResult(
            start=history.dates[0],
            end=history.dates[-1],
            observations=len(history) - 1,
            risk_free_rate=risk_free,
            objective=request.objective,
            max_weight=request.max_weight,
            simulated=_point(f"Simulada ({label})", point, universe.tickers),
            current=_point("Carteira atual", current_point, universe.tickers)
            if current_point is not None
            else None,
            base_value=base_value,
            rows=rows,
            classes=class_rows,
            dates=list(history.dates),
            simulated_growth=growth_curve(returns, point.weights).tolist(),
            current_growth=growth_curve(returns, current_weights).tolist()
            if current_weights is not None
            else None,
            excluded=excluded,
            warnings=warnings,
        )

    def _class_targets(
        self,
        request: QuantSimulationRequest,
        positions: list[Position],
        excluded: dict[str, str],
    ) -> dict[AssetClass, float] | None:
        """Alvos por classe (em %) quando a simulação respeita o perfil; marca exclusões."""
        if not request.respect_targets:
            if not request.include_fixed_income:
                for p in positions:
                    if p.asset_class in _FIXED_INCOME:
                        excluded[p.ticker.symbol] = "renda fixa fora da simulação (opção)"
            return None
        saved = self._portfolios.get_allocation_targets(request.portfolio_id)
        if not saved:
            raise DomainError(
                "Defina o perfil de alocação alvo (Alocação Alvo) ou desligue "
                '"Respeitar alocação alvo".'
            )
        targets = {AssetClass(k): float(v) for k, v in saved.items()}
        for p in positions:
            if targets.get(p.asset_class, 0.0) <= 0:
                excluded[p.ticker.symbol] = f"{p.asset_class.label_pt} tem alvo 0%"
        return targets

    def _with_history(
        self, positions: list[Position], start: date, excluded: dict[str, str]
    ) -> list[Position]:
        """Mantém os ativos com histórico que cobre a maior parte da janela."""
        first: dict[Ticker, date] = {}
        for p in positions:
            try:
                history = self._market_data.price_history([p.ticker], start)
            except MissingMarketDataError:
                excluded[p.ticker.symbol] = "sem cotações: atualize os dados de mercado"
                continue
            if len(history) < 30:
                excluded[p.ticker.symbol] = "histórico curto demais (menos de 30 datas)"
                continue
            first[p.ticker] = history.dates[0]
        if not first:
            return []
        end = self._today()
        longest = (end - min(first.values())).days
        kept: list[Position] = []
        for p in positions:
            if p.ticker not in first:
                continue
            span = (end - first[p.ticker]).days
            if longest > 0 and span / longest < _MIN_HISTORY_COVERAGE:
                excluded[p.ticker.symbol] = (
                    f"histórico começa em {first[p.ticker]:%d/%m/%Y} e encurtaria a janela"
                )
                continue
            kept.append(p)
        return kept


def _annual_risk_free(
    market_data: MarketDataRepository, history: PriceHistory, start: date
) -> float:
    """CDI acumulado nas datas do histórico, anualizado em 252 dias úteis."""
    rf_history = market_data.price_history([Ticker(CDI)], start - timedelta(days=15))
    rf_returns = index_returns_on(history.dates, rf_history, CDI)
    return float(np.prod(1.0 + rf_returns) ** (TRADING_DAYS_PER_YEAR / rf_returns.size) - 1)
