"""Estratégias operacionais e lado da operação (CLAUDE.md 5.4)."""

from enum import StrEnum


class StrategyType(StrEnum):
    """Estratégia a que cada operação pertence. Toda métrica é segregada por ela.

    Os valores são os mesmos do enum `public.strategy_type` no Postgres.
    """

    BUY_AND_HOLD = "BUY_AND_HOLD"
    SWING_TRADE = "SWING_TRADE"
    DAY_TRADE = "DAY_TRADE"
    POSITION_TRADE = "POSITION_TRADE"
    ARBITRAGE = "ARBITRAGE"
    HEDGE_OPTIONS = "HEDGE_OPTIONS"

    @property
    def label_pt(self) -> str:
        return _STRATEGY_LABELS_PT[self]


class TradeSide(StrEnum):
    """Compra ou venda. Mesmos valores do enum `public.trade_side`."""

    BUY = "BUY"
    SELL = "SELL"


_STRATEGY_LABELS_PT: dict[StrategyType, str] = {
    StrategyType.BUY_AND_HOLD: "Buy and Hold",
    StrategyType.SWING_TRADE: "Swing Trade",
    StrategyType.DAY_TRADE: "Day Trade",
    StrategyType.POSITION_TRADE: "Position Trade",
    StrategyType.ARBITRAGE: "Arbitragem",
    StrategyType.HEDGE_OPTIONS: "Hedge com Opções",
}
