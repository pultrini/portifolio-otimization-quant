"""Testes do casamento FIFO, day trade e séries de performance."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from domain.entities.trade import Trade
from domain.services.performance import (
    constant_holdings_returns,
    index_returns_on,
    strategy_returns,
)
from domain.services.trade_matching import close_trades
from domain.value_objects.money import Money
from domain.value_objects.price_history import PriceHistory
from domain.value_objects.strategy_type import StrategyType, TradeSide
from domain.value_objects.ticker import Ticker

D = Decimal
BRT = timezone(timedelta(hours=-3))
ABC = Ticker("ABCD3")


def _trade(
    side: TradeSide,
    qty: str,
    price: str,
    when: datetime,
    costs: str = "0",
    strategy: StrategyType = StrategyType.SWING_TRADE,
) -> Trade:
    return Trade(
        ABC, side, strategy, when.astimezone(UTC), D(qty), Money.brl(price), Money.brl(costs)
    )


class TestFifo:
    def test_venda_fecha_lotes_em_ordem_com_custos_rateados(self) -> None:
        trades = [
            _trade(TradeSide.BUY, "10", "10", datetime(2026, 1, 5, 10, tzinfo=BRT), "2"),
            _trade(TradeSide.BUY, "10", "12", datetime(2026, 1, 6, 10, tzinfo=BRT)),
            _trade(TradeSide.SELL, "15", "13", datetime(2026, 1, 7, 10, tzinfo=BRT), "3"),
        ]
        result = close_trades(trades)
        first, second = result.closed
        # Lote 1: custo 10 x 10 + 2 = 102; venda (15 x 13 - 3) / 15 = 12,80 x 10 = 128.
        assert first.entry_value.amount == D("102")
        assert first.exit_value.amount == D("128")
        assert first.pnl.amount == D("26")
        # Lote 2 (parcial): 5 x 12 = 60; 5 x 12,80 = 64.
        assert second.quantity == D("5")
        assert second.pnl.amount == D("4")
        assert first.return_pct == pytest.approx(26 / 102)
        assert result.unmatched_quantity == {}

    def test_day_trade_no_mesmo_pregao(self) -> None:
        trades = [
            _trade(TradeSide.BUY, "1", "10", datetime(2026, 1, 5, 10, tzinfo=BRT)),
            _trade(TradeSide.SELL, "1", "11", datetime(2026, 1, 5, 16, tzinfo=BRT)),
        ]
        assert close_trades(trades).closed[0].is_day_trade

    def test_pregao_e_definido_no_horario_de_brasilia(self) -> None:
        # 23h30 de 19/01 em Brasília = 02h30 de 20/01 em UTC: pregões diferentes.
        trades = [
            _trade(TradeSide.BUY, "1", "10", datetime(2026, 1, 19, 23, 30, tzinfo=BRT)),
            _trade(TradeSide.SELL, "1", "11", datetime(2026, 1, 20, 10, tzinfo=BRT)),
        ]
        assert not close_trades(trades).closed[0].is_day_trade

    def test_estrategias_nao_se_misturam(self) -> None:
        trades = [
            _trade(
                TradeSide.BUY,
                "5",
                "10",
                datetime(2026, 1, 5, 10, tzinfo=BRT),
                strategy=StrategyType.BUY_AND_HOLD,
            ),
            _trade(TradeSide.SELL, "2", "11", datetime(2026, 1, 6, 10, tzinfo=BRT)),
        ]
        result = close_trades(trades)
        assert result.closed == []
        assert result.unmatched_quantity == {(ABC, StrategyType.SWING_TRADE): D("2")}


DATES = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8))


class TestPerformance:
    def test_quantidades_constantes(self) -> None:
        history = PriceHistory(
            DATES[:3], ("A", "B"), np.array([[10.0, 100.0], [11.0, 100.0], [11.0, 110.0]])
        )
        series = constant_holdings_returns(history, {"A": 1.0, "B": 1.0})
        # V = 110, 111, 121.
        assert series.returns == pytest.approx([111 / 110 - 1, 121 / 111 - 1])
        assert series.dates == DATES[1:3]

    def test_indice_alinhado_com_forward_fill(self) -> None:
        index = PriceHistory(
            (DATES[0], DATES[1], DATES[3]), ("CDI",), np.array([[1.0], [1.01], [1.0201]])
        )
        assert index_returns_on(DATES, index, "CDI") == pytest.approx([0.01, 0.0, 0.01])

    def test_twr_com_aporte_e_resgate(self) -> None:
        history = PriceHistory(DATES, ("ABCD3",), np.array([[10.0], [11.0], [12.0], [12.0]]))
        trades = [
            _trade(TradeSide.BUY, "10", "10", datetime(2026, 1, 5, 10, tzinfo=BRT)),
            _trade(TradeSide.SELL, "5", "12", datetime(2026, 1, 7, 15, tzinfo=BRT)),
        ]
        result = strategy_returns(trades, history)
        # V: 100, 110, 60, 60. Resgate de 60 em 07/01: (60 + 60) / 110 - 1 = 10/110.
        assert result.values == pytest.approx([100, 110, 60, 60])
        assert result.series.returns == pytest.approx([0.10, 10 / 110, 0.0])

    def test_twr_estrategia_que_comeca_no_meio(self) -> None:
        history = PriceHistory(DATES, ("ABCD3",), np.array([[10.0], [11.0], [12.1], [12.1]]))
        trades = [_trade(TradeSide.BUY, "10", "11", datetime(2026, 1, 6, 10, tzinfo=BRT))]
        result = strategy_returns(trades, history)
        # 05/01 sem patrimônio fica de fora; 06/01 começa com retorno 0; 07/01 +10%.
        assert result.series.dates == DATES[1:]
        assert result.series.returns == pytest.approx([0.0, 0.10, 0.0])
