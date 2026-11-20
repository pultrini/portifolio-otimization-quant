"""Casamento de compras e vendas em operações fechadas (FIFO por estratégia)."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from domain.entities.trade import Trade
from domain.value_objects.money import Money
from domain.value_objects.strategy_type import StrategyType, TradeSide
from domain.value_objects.ticker import Ticker

# O pregão é definido no horário de Brasília. Comparar datas em UTC erraria operações
# feitas à noite: 01h UTC do dia 20 ainda é 22h do dia 19 em São Paulo.
EXCHANGE_TZ = ZoneInfo("America/Sao_Paulo")


def session_date(moment: datetime) -> date:
    """Data do pregão de um instante UTC (horário de Brasília)."""
    return moment.astimezone(EXCHANGE_TZ).date()


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    """Uma quantidade comprada e depois vendida, com resultado líquido de custos.

    Attributes:
        entry_value: Custo da quantidade, incluindo a parte proporcional dos custos.
        exit_value: Valor recebido na venda, já descontada a parte dos custos.
        pnl: exit_value - entry_value.
        is_day_trade: compra e venda no mesmo pregão (CLAUDE.md 5.4).
    """

    ticker: Ticker
    strategy: StrategyType
    opened_at: datetime
    closed_at: datetime
    quantity: Decimal
    entry_value: Money
    exit_value: Money
    pnl: Money
    is_day_trade: bool

    @property
    def return_pct(self) -> float | None:
        """Retorno da operação: pnl / custo de entrada."""
        if self.entry_value.amount == 0:
            return None
        return float(self.pnl.amount / self.entry_value.amount)


@dataclass(slots=True)
class _Lot:
    remaining: Decimal
    unit_cost: Decimal  # preço + custos de compra, por unidade
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class MatchingResult:
    """Operações fechadas e a quantidade vendida que não tinha compra correspondente.

    Vendas sem compra registrada acontecem quando a posição foi importada (sem
    histórico de operações); essa parte não entra nas estatísticas.
    """

    closed: list[ClosedTrade]
    unmatched_quantity: dict[tuple[Ticker, StrategyType], Decimal]


def close_trades(trades: Sequence[Trade]) -> MatchingResult:
    """Casa vendas com compras anteriores, em ordem de chegada (FIFO).

    O casamento é feito por ativo E estratégia: cada operação pertence a uma única
    estratégia, então uma venda de swing trade nunca fecha uma compra de buy and hold.

    Custos são rateados pela quantidade: uma venda parcial carrega só a fração
    correspondente da corretagem da compra e da venda.
    """
    open_lots: dict[tuple[Ticker, StrategyType], deque[_Lot]] = {}
    closed: list[ClosedTrade] = []
    unmatched: dict[tuple[Ticker, StrategyType], Decimal] = {}

    for trade in sorted(trades, key=lambda t: t.traded_at):
        key = (trade.ticker, trade.strategy)
        lots = open_lots.setdefault(key, deque())
        if trade.side is TradeSide.BUY:
            unit_cost = (trade.gross_value + trade.costs).amount / trade.quantity
            lots.append(_Lot(trade.quantity, unit_cost, trade.traded_at))
            continue

        # Venda: receita líquida por unidade = preço - custos da venda / quantidade.
        unit_proceeds = (trade.gross_value - trade.costs).amount / trade.quantity
        to_close = trade.quantity
        while to_close > 0 and lots:
            lot = lots[0]
            quantity = min(lot.remaining, to_close)
            entry = Money.brl(lot.unit_cost * quantity)
            exit_ = Money.brl(unit_proceeds * quantity)
            closed.append(
                ClosedTrade(
                    ticker=trade.ticker,
                    strategy=trade.strategy,
                    opened_at=lot.opened_at,
                    closed_at=trade.traded_at,
                    quantity=quantity,
                    entry_value=entry,
                    exit_value=exit_,
                    pnl=exit_ - entry,
                    is_day_trade=session_date(lot.opened_at) == session_date(trade.traded_at),
                )
            )
            lot.remaining -= quantity
            to_close -= quantity
            if lot.remaining == 0:
                lots.popleft()
        if to_close > 0:
            unmatched[key] = unmatched.get(key, Decimal("0")) + to_close

    return MatchingResult(closed, unmatched)
