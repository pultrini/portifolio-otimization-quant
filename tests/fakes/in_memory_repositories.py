"""Repositórios em memória de posições, operações e dados de mercado (sem I/O)."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import numpy as np

from domain.entities.fundamentals import ReitFundamentals, StockFundamentals
from domain.entities.position import Position
from domain.entities.savings_goal import GoalDeposit, SavingsGoal
from domain.entities.trade import Trade
from domain.entities.treasury import BondTerms, TreasuryQuote
from domain.exceptions import MissingMarketDataError
from domain.repositories.market_data_repository import MarketDataRepository
from domain.repositories.position_repository import PositionRepository
from domain.repositories.trade_repository import TradeRepository
from domain.value_objects.checklist import ChecklistWeights
from domain.value_objects.money import Money
from domain.value_objects.price_history import PriceHistory
from domain.value_objects.ticker import Ticker


class InMemoryPositionRepository(PositionRepository):
    def __init__(self) -> None:
        self.positions: dict[tuple[str, Ticker], Position] = {}

    def list_positions(self, portfolio_id: str) -> list[Position]:
        return [p for (pid, _), p in sorted(self.positions.items()) if pid == portfolio_id]

    def get_position(self, portfolio_id: str, ticker: Ticker) -> Position | None:
        return self.positions.get((portfolio_id, ticker))

    def save_positions(
        self, user_id: str, portfolio_id: str, positions: Sequence[Position]
    ) -> None:
        for position in positions:
            self.positions[(portfolio_id, position.ticker)] = position

    def delete_position(self, portfolio_id: str, ticker: Ticker) -> None:
        self.positions.pop((portfolio_id, ticker), None)


class InMemoryTradeRepository(TradeRepository):
    """Imita a função `record_trade`: grava operação e posição e checa concorrência."""

    def __init__(self, positions: InMemoryPositionRepository) -> None:
        self._positions = positions
        self.trades: dict[str, list[Trade]] = {}

    def list_trades(self, portfolio_id: str) -> list[Trade]:
        return sorted(self.trades.get(portfolio_id, []), key=lambda t: t.traded_at)

    def record_trade(
        self,
        user_id: str,
        portfolio_id: str,
        trade: Trade,
        previous_quantity: Decimal | None,
        resulting_position: Position,
    ) -> str:
        current = self._positions.get_position(portfolio_id, trade.ticker)
        current_quantity = current.quantity if current is not None else None
        if current_quantity != previous_quantity:
            raise RuntimeError("A posição mudou desde a leitura.")
        trade_id = f"t{sum(len(v) for v in self.trades.values()) + 1}"
        stored = Trade(
            trade.ticker,
            trade.side,
            trade.strategy,
            trade.traded_at,
            trade.quantity,
            trade.price,
            trade.costs,
            trade_id,
        )
        self.trades.setdefault(portfolio_id, []).append(stored)
        self._positions.save_positions(user_id, portfolio_id, [resulting_position])
        return trade_id


class FakeMarketDataRepository(MarketDataRepository):
    """Preços fixos em memória: `history` por ticker, alinhado pela lista de datas."""

    def __init__(
        self,
        dates: Sequence[date] = (),
        history: dict[str, list[float]] | None = None,
    ) -> None:
        self._dates = tuple(dates)
        self._history = history or {}

    def latest_prices(self, tickers: Sequence[Ticker]) -> dict[Ticker, Money]:
        return {
            t: Money.brl(str(self._history[t.symbol][-1]))
            for t in tickers
            if self._history.get(t.symbol)
        }

    def price_history(self, tickers: Sequence[Ticker], start: date | None = None) -> PriceHistory:
        missing = [t.symbol for t in tickers if t.symbol not in self._history]
        if missing:
            raise MissingMarketDataError(f"Sem histórico para {', '.join(missing)}.")
        # NaN = sem cotação no dia (ativo listado depois): como no Parquet, só ficam as
        # datas em que todos os tickers pedidos têm preço.
        keep = [
            i
            for i, d in enumerate(self._dates)
            if (start is None or d >= start)
            and all(not np.isnan(self._history[t.symbol][i]) for t in tickers)
        ]
        if not keep:
            raise MissingMarketDataError("Sem datas em comum.")
        matrix = np.array(
            [[self._history[t.symbol][i] for t in tickers] for i in keep], dtype=np.float64
        ).reshape(len(keep), len(tickers))
        return PriceHistory(
            tuple(self._dates[i] for i in keep), tuple(t.symbol for t in tickers), matrix
        )


class InMemoryChecklistRepository:
    """Respostas manuais em memória (mesma semântica do Supabase: None apaga)."""

    def __init__(self) -> None:
        self.saved: dict[Ticker, dict[str, bool]] = {}
        self.saved_weights = ChecklistWeights()

    def answers(self, tickers: Sequence[Ticker]) -> dict[Ticker, dict[str, bool | None]]:
        return {t: dict(self.saved[t]) for t in tickers if t in self.saved}

    def save_answers(self, user_id: str, ticker: Ticker, answers: dict[str, bool | None]) -> None:
        current = self.saved.setdefault(ticker, {})
        for key, value in answers.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value

    def weights(self) -> ChecklistWeights:
        return self.saved_weights

    def save_weights(self, user_id: str, weights: ChecklistWeights) -> None:
        self.saved_weights = weights


class FakeFundamentalsRepository:
    """Fundamentos fixos em memória."""

    def __init__(
        self,
        stocks: dict[str, StockFundamentals] | None = None,
        reits: dict[str, ReitFundamentals] | None = None,
    ) -> None:
        self._stocks = stocks or {}
        self._reits = reits or {}

    def listed_reits(self) -> frozenset[str]:
        return frozenset(self._reits)

    def stock_fundamentals(self, tickers: Sequence[Ticker]) -> dict[Ticker, StockFundamentals]:
        return {t: self._stocks[t.symbol] for t in tickers if t.symbol in self._stocks}

    def reit_fundamentals(self, tickers: Sequence[Ticker]) -> dict[Ticker, ReitFundamentals]:
        return {t: self._reits[t.symbol] for t in tickers if t.symbol in self._reits}


class NoopFundamentalsRefresher:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def refresh(self, tickers: Sequence[Ticker]) -> dict[str, str]:
        self.calls.append([t.symbol for t in tickers])
        return {}


class InMemorySavingsGoalRepository:
    """Objetivos e depósitos em memória (mesmas restrições do banco)."""

    def __init__(self) -> None:
        self.goals: dict[str, SavingsGoal] = {}
        self.deposits: dict[str, dict[int, GoalDeposit]] = {}

    def list_goals(self) -> list[SavingsGoal]:
        return list(self.goals.values())

    def create_goal(self, user_id: str, goal: SavingsGoal) -> SavingsGoal:
        goal_id = f"g{len(self.goals) + 1}"
        stored = SavingsGoal(
            goal.name,
            goal.mode,
            goal.frequency,
            goal.unit_amount,
            goal.step_count,
            goal.start_date,
            goal.end_date,
            goal_id,
        )
        self.goals[goal_id] = stored
        self.deposits[goal_id] = {}
        return stored

    def delete_goal(self, goal_id: str) -> None:
        self.goals.pop(goal_id, None)
        self.deposits.pop(goal_id, None)

    def list_deposits(self, goal_id: str) -> list[GoalDeposit]:
        return sorted(self.deposits.get(goal_id, {}).values(), key=lambda d: d.deposited_on)

    def add_deposit(self, user_id: str, goal_id: str, deposit: GoalDeposit) -> None:
        steps = self.deposits[goal_id]
        if deposit.step in steps:
            raise RuntimeError("duplicate key value violates unique constraint")
        steps[deposit.step] = deposit

    def remove_deposit(self, goal_id: str, step: int) -> None:
        self.deposits.get(goal_id, {}).pop(step, None)


class FakeTreasuryRepository:
    """Cotações do Tesouro em memória: lista de TreasuryQuote por ticker."""

    def __init__(self, quotes: Sequence[TreasuryQuote] = ()) -> None:
        self._quotes = sorted(quotes, key=lambda q: q.date)

    def latest_quotes(self, tickers: Sequence[Ticker]) -> dict[Ticker, TreasuryQuote]:
        result: dict[Ticker, TreasuryQuote] = {}
        for quote in self._quotes:
            if quote.pu_sell is not None and Ticker(quote.ticker) in tickers:
                result[Ticker(quote.ticker)] = quote
        return result

    def quote_on(self, ticker: Ticker, day: date) -> TreasuryQuote | None:
        found = [
            q
            for q in self._quotes
            if q.ticker == ticker.symbol and q.date <= day and q.pu_buy is not None
        ]
        return found[-1] if found else None


class InMemoryBondTermsRepository:
    def __init__(self) -> None:
        self.saved: dict[tuple[str, Ticker], BondTerms] = {}

    def terms(self, portfolio_id: str) -> dict[Ticker, BondTerms]:
        return {t: v for (pid, t), v in self.saved.items() if pid == portfolio_id}

    def save_terms(self, user_id: str, portfolio_id: str, ticker: Ticker, terms: BondTerms) -> None:
        self.saved[(portfolio_id, ticker)] = terms

    def delete_terms(self, portfolio_id: str, ticker: Ticker) -> None:
        self.saved.pop((portfolio_id, ticker), None)
