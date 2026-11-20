"""Use case: métricas de performance e risco por carteira, classe e estratégia."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

from application.dtos.metrics import (
    MetricsReport,
    MetricsRequest,
    RiskReturnMetrics,
    ScopeKind,
    ScopeReport,
    SeriesDTO,
    TradeStatsDTO,
)
from domain.entities.position import Position
from domain.entities.trade import Trade
from domain.exceptions import MissingMarketDataError
from domain.repositories.market_data_repository import MarketDataRepository
from domain.repositories.position_repository import PositionRepository
from domain.repositories.trade_repository import TradeRepository
from domain.services import metrics as m
from domain.services.asset_classification import infer_asset_class
from domain.services.performance import (
    ReturnSeries,
    constant_holdings_returns,
    index_returns_on,
    strategy_returns,
)
from domain.services.trade_matching import close_trades, session_date
from domain.value_objects.asset_class import (
    CALENDAR_DAYS_PER_YEAR,
    CDI,
    IBOV,
    TRADING_DAYS_PER_YEAR,
    AssetClass,
)
from domain.value_objects.price_history import PriceHistory
from domain.value_objects.ticker import Ticker

FloatArray = NDArray[np.float64]

# Folga ao buscar a taxa livre de risco: o índice precisa ter valor na primeira data
# dos ativos (ou antes) para o forward-fill funcionar.
_RISK_FREE_MARGIN = timedelta(days=15)


def _risk_metrics(
    returns: FloatArray,
    risk_free: FloatArray,
    benchmark: FloatArray | None,
    periods_per_year: int,
    include_parametric: bool,
) -> RiskReturnMetrics:
    """Aplica todas as funções puras do domínio a uma série de retornos."""
    result = RiskReturnMetrics(
        cumulative_return=m.cumulative_return(returns),
        cagr=m.cagr(returns, periods_per_year),
        volatility=m.annualized_volatility(returns, periods_per_year),
        max_drawdown=m.max_drawdown(returns),
        var_95=m.historical_var(returns, 0.95),
        var_99=m.historical_var(returns, 0.99),
        cvar_95=m.historical_cvar(returns, 0.95),
        cvar_99=m.historical_cvar(returns, 0.99),
        sharpe=m.sharpe_ratio(returns, risk_free, periods_per_year),
        sortino=m.sortino_ratio(returns, risk_free, periods_per_year),
        calmar=m.calmar_ratio(returns, periods_per_year),
        beta=m.beta(returns, benchmark) if benchmark is not None else None,
    )
    if include_parametric:
        result.parametric_var_95 = m.parametric_var(returns, 0.95)
        result.parametric_var_99 = m.parametric_var(returns, 0.99)
        result.parametric_cvar_95 = m.parametric_cvar(returns, 0.95)
        result.parametric_cvar_99 = m.parametric_cvar(returns, 0.99)
    return result


def _curve(dates: Sequence[date], returns: FloatArray) -> tuple[SeriesDTO, SeriesDTO]:
    """Curva de patrimônio (base 1) e drawdown, com a data inicial incluída."""
    if not dates:
        return SeriesDTO(), SeriesDTO()
    return (
        SeriesDTO(dates=list(dates), values=m.equity_curve(returns).tolist()),
        SeriesDTO(dates=list(dates), values=m.drawdown_series(returns).tolist()),
    )


class CalculateMetrics:
    """Monta o relatório de métricas da carteira.

    Escopos:
        - Carteira atual: posições de hoje com quantidades fixas no período (funciona
          mesmo sem operações registradas). Benchmark IBOV, taxa livre de risco CDI.
        - Por classe de ativo: mesmo cálculo, só com as posições da classe, usando o
          benchmark e a taxa livre de risco da tabela 5.1.
        - Por estratégia: retorno ponderado pelo tempo das operações registradas, mais
          win rate, payoff, profit factor e expectativa das operações fechadas.
    """

    def __init__(
        self,
        positions: PositionRepository,
        trades: TradeRepository,
        market_data: MarketDataRepository,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._positions = positions
        self._trades = trades
        self._market_data = market_data
        self._today = today

    def execute(self, request: MetricsRequest) -> MetricsReport:
        start = self._today() - timedelta(days=365 * request.lookback_years)
        open_positions = [
            p for p in self._positions.list_positions(request.portfolio_id) if not p.is_closed
        ]
        scopes: list[ScopeReport] = []
        if open_positions:
            scopes.append(
                self._holdings_scope(
                    "portfolio",
                    "Carteira atual",
                    "portfolio",
                    open_positions,
                    IBOV,
                    CDI,
                    start,
                    request.include_parametric,
                )
            )
            for asset_class in sorted({p.asset_class for p in open_positions}):
                scopes.append(
                    self._holdings_scope(
                        asset_class.value,
                        asset_class.label_pt,
                        "asset_class",
                        [p for p in open_positions if p.asset_class is asset_class],
                        asset_class.benchmark,
                        asset_class.risk_free,
                        start,
                        request.include_parametric,
                    )
                )

        trades = self._trades.list_trades(request.portfolio_id)
        for strategy in sorted({t.strategy for t in trades}):
            strategy_trades = [t for t in trades if t.strategy is strategy]
            scopes.append(self._strategy_scope(strategy_trades, request.include_parametric))

        return MetricsReport(portfolio_id=request.portfolio_id, lookback_start=start, scopes=scopes)

    # ------------------------------------------------------------------ helpers

    def _history(
        self, tickers: Sequence[str], benchmark: str, start: date
    ) -> tuple[PriceHistory, str]:
        """Histórico alinhado dos ativos + benchmark (sem repetir ticker)."""
        symbols = list(dict.fromkeys([*tickers, benchmark]))
        history = self._market_data.price_history([Ticker(s) for s in symbols], start)
        if len(history) < 3:
            raise MissingMarketDataError(
                "Histórico em comum curto demais (menos de 3 datas). Atualize os dados."
            )
        return history, benchmark

    def _risk_free_returns(self, risk_free: str, dates: Sequence[date]) -> FloatArray:
        """Retorno da taxa livre de risco entre cada par de datas consecutivas."""
        rf_history = self._market_data.price_history(
            [Ticker(risk_free)], dates[0] - _RISK_FREE_MARGIN
        )
        return index_returns_on(dates, rf_history, risk_free)

    @staticmethod
    def _periods_per_year(tickers: Sequence[str]) -> int:
        """365 só se todos os ativos são cripto (calendário de 7 dias); senão 252."""
        classes = {infer_asset_class(Ticker(t)) for t in tickers}
        return CALENDAR_DAYS_PER_YEAR if classes == {AssetClass.CRYPTO} else TRADING_DAYS_PER_YEAR

    def _build_scope(
        self,
        scope: ScopeReport,
        series: ReturnSeries,
        all_dates: Sequence[date],
        history: PriceHistory,
        include_parametric: bool,
    ) -> ScopeReport:
        """Preenche métricas, benchmark e curvas a partir de uma série de retornos."""
        returns = series.returns
        if returns.size < 2:
            scope.error = "Poucas observações para calcular métricas."
            return scope
        # Cada retorno vai da data anterior do histórico até a sua data. Benchmark e
        # taxa livre de risco são medidos exatamente no mesmo intervalo, inclusive
        # quando a estratégia ficou dias sem posição (datas puladas na série).
        row_of = {d: i for i, d in enumerate(all_dates)}
        rows = np.array([row_of[d] for d in series.dates])
        benchmark_prices = history.column(scope.benchmark)
        benchmark_returns = benchmark_prices[rows] / benchmark_prices[rows - 1] - 1.0
        risk_free = self._risk_free_returns(scope.risk_free, all_dates)[rows - 1]
        window = [all_dates[rows[0] - 1], *series.dates]

        scope.start, scope.end = window[0], window[-1]
        scope.observations = int(returns.size)
        # Beta contra a própria taxa livre de risco (Renda Fixa Brasil vs. CDI) não tem
        # significado: a variância do CDI é quase zero e o quociente explode (ex.: 3,2).
        beta_benchmark = benchmark_returns if scope.benchmark != scope.risk_free else None
        scope.metrics = _risk_metrics(
            returns, risk_free, beta_benchmark, scope.periods_per_year, include_parametric
        )
        scope.benchmark_metrics = _risk_metrics(
            benchmark_returns, risk_free, None, scope.periods_per_year, False
        )
        scope.equity, scope.drawdown = _curve(window, returns)
        scope.benchmark_equity, _ = _curve(window, benchmark_returns)
        return scope

    def _holdings_scope(
        self,
        key: str,
        label: str,
        kind: ScopeKind,
        positions: Sequence[Position],
        benchmark: str,
        risk_free: str,
        start: date,
        include_parametric: bool,
    ) -> ScopeReport:
        tickers = [p.ticker.symbol for p in positions]
        scope = ScopeReport(
            key=key,
            label=label,
            kind=kind,
            benchmark=benchmark,
            risk_free=risk_free,
            periods_per_year=self._periods_per_year([*tickers, benchmark]),
        )
        try:
            history, _ = self._history(tickers, benchmark, start)
            quantities = {p.ticker.symbol: float(p.quantity) for p in positions}
            series = constant_holdings_returns(history, quantities)
            return self._build_scope(scope, series, history.dates, history, include_parametric)
        except MissingMarketDataError as error:
            scope.error = str(error)
            return scope

    def _strategy_scope(self, trades: Sequence[Trade], include_parametric: bool) -> ScopeReport:
        strategy = trades[0].strategy
        tickers = sorted({t.ticker.symbol for t in trades})
        # Benchmark e taxa livre de risco da classe predominante nas operações.
        main_class = Counter(infer_asset_class(t.ticker) for t in trades).most_common(1)[0][0]
        scope = ScopeReport(
            key=strategy.value,
            label=strategy.label_pt,
            kind="strategy",
            benchmark=main_class.benchmark,
            risk_free=main_class.risk_free,
            periods_per_year=self._periods_per_year([*tickers, main_class.benchmark]),
        )

        matching = close_trades(trades)
        pnls = [c.pnl.amount for c in matching.closed]
        stats = m.trade_statistics(pnls)
        trade_returns = [r for c in matching.closed if (r := c.return_pct) is not None]
        scope.trade_stats = TradeStatsDTO(
            closed_trades=stats.closed_trades,
            day_trades=sum(1 for c in matching.closed if c.is_day_trade),
            win_rate=stats.win_rate,
            payoff_ratio=stats.payoff_ratio,
            profit_factor=stats.profit_factor,
            expectancy=stats.expectancy,
            average_win=stats.average_win,
            average_loss=stats.average_loss,
            mean_return_per_trade=m.mean_return(trade_returns) if trade_returns else None,
            unmatched_quantity=sum(matching.unmatched_quantity.values(), Decimal("0")),
        )

        first_session = min(session_date(t.traded_at) for t in trades)
        try:
            # Começa uns dias antes da primeira operação para ter o preço de abertura.
            history, _ = self._history(
                tickers, main_class.benchmark, first_session - timedelta(days=7)
            )
            performance = strategy_returns(trades, history)
            return self._build_scope(
                scope, performance.series, history.dates, history, include_parametric
            )
        except MissingMarketDataError as error:
            scope.error = str(error)
            return scope
