"""Séries de patrimônio e retorno de carteiras e estratégias."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray

from domain.entities.trade import Trade
from domain.exceptions import MissingMarketDataError
from domain.services.trade_matching import session_date
from domain.value_objects.price_history import PriceHistory
from domain.value_objects.strategy_type import TradeSide

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True, eq=False)
class ReturnSeries:
    """Retornos por período com as datas de fim de cada período.

    `dates[i]` é a data em que o retorno `returns[i]` terminou.
    """

    dates: tuple[date, ...]
    returns: FloatArray

    def __post_init__(self) -> None:
        if len(self.dates) != self.returns.shape[0]:
            raise ValueError("Datas e retornos com tamanhos diferentes.")


def constant_holdings_returns(
    history: PriceHistory, quantities: Mapping[str, float]
) -> ReturnSeries:
    """Retornos de uma carteira com quantidades fixas ao longo do histórico.

    Responde "como teria se comportado a carteira de hoje": V_t = Σ q_i x P_i,t e
    r_t = V_t / V_{t-1} - 1. Não depende de operações registradas, então funciona para
    carteiras importadas.
    """
    weights = np.array([quantities.get(t, 0.0) for t in history.tickers], dtype=np.float64)
    values = history.prices @ weights
    if values.size < 2 or (values <= 0).any():
        raise MissingMarketDataError("Histórico insuficiente para a carteira.")
    return ReturnSeries(history.dates[1:], values[1:] / values[:-1] - 1.0)


def index_returns_on(dates: Sequence[date], index: PriceHistory, ticker: str) -> FloatArray:
    """Retornos de um índice (CDI, T-Bill) entre datas de outro calendário.

    Para cada data usa o último valor do índice até aquela data (forward-fill, válido
    para séries de taxa). Assim o retorno da taxa livre de risco cobre exatamente o
    mesmo intervalo que o retorno do ativo, inclusive fins de semana de cripto.

    Returns:
        len(dates) - 1 retornos, alinhados com os retornos dos ativos.
    """
    levels = index.column(ticker)
    positions = np.searchsorted(np.array(index.dates), np.array(dates), side="right") - 1
    if (positions < 0).any():
        raise MissingMarketDataError(f"{ticker} começa depois do histórico dos ativos.")
    aligned = levels[positions]
    return aligned[1:] / aligned[:-1] - 1.0


@dataclass(frozen=True, slots=True, eq=False)
class StrategyPerformance:
    """Patrimônio e retornos ponderados pelo tempo de uma estratégia."""

    values: FloatArray
    series: ReturnSeries


def strategy_returns(trades: Sequence[Trade], history: PriceHistory) -> StrategyPerformance:
    """Retorno ponderado pelo tempo (TWR) de uma estratégia a partir das operações.

    A cada data t:
        quantidades q_i,t somam as compras e subtraem as vendas até o pregão t;
        V_t = Σ q_i,t x P_i,t (fechamento);
        F_t = aportes líquidos do dia = Σ compras (com custos) - Σ vendas (líquidas).
    Retorno do período:
        r_t = (V_t - F_t) / V_{t-1} - 1          se V_{t-1} > 0
        r_t = (V_t - F_t) / F_t                   se a estratégia começou no dia (Dietz)
    Dias sem patrimônio e sem aporte não têm retorno e ficam de fora.

    O TWR neutraliza o efeito de aportes e resgates: mede a qualidade das decisões,
    não o tamanho do patrimônio. Preços da Gold são ajustados por proventos, então o
    resultado já inclui dividendos.
    """
    if len(history) < 2:
        raise MissingMarketDataError("Histórico insuficiente para a estratégia.")
    index = {ticker: i for i, ticker in enumerate(history.tickers)}
    quantities = np.zeros(len(history.tickers), dtype=np.float64)
    flows = np.zeros(len(history), dtype=np.float64)
    values = np.zeros(len(history), dtype=np.float64)
    dates = np.array(history.dates)

    ordered = sorted(trades, key=lambda t: t.traded_at)
    cursor = 0
    for row, current in enumerate(history.dates):
        # Aplica todas as operações cujo pregão é até a data atual. Operações antes do
        # início do histórico entram na primeira data.
        while cursor < len(ordered) and session_date(ordered[cursor].traded_at) <= current:
            trade = ordered[cursor]
            if trade.ticker.symbol not in index:
                raise MissingMarketDataError(f"Sem preços para {trade.ticker}.")
            signed = (
                float(trade.quantity) if trade.side is TradeSide.BUY else -float(trade.quantity)
            )
            quantities[index[trade.ticker.symbol]] += signed
            # cash_flow é do ponto de vista do investidor (compra negativa); aporte na
            # estratégia é o oposto.
            flows[row] += -float(trade.cash_flow.amount)
            cursor += 1
        values[row] = float(history.prices[row] @ quantities)

    returns: list[float] = []
    kept: list[date] = []
    for row in range(1, len(history)):
        previous = values[row - 1]
        if previous > 0:
            base = previous
        elif flows[row] > 0:
            base = flows[row]
            previous = 0.0
        else:
            continue
        returns.append((values[row] - flows[row] - previous) / base)
        kept.append(dates[row])
    return StrategyPerformance(values, ReturnSeries(tuple(kept), np.array(returns)))
