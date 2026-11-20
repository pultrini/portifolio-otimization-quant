"""Matriz de preços históricos alinhados por data, em BRL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from numpy.typing import NDArray

from domain.exceptions import DomainError, MissingMarketDataError


@dataclass(frozen=True, slots=True, eq=False)
class PriceHistory:
    """Preços de vários ativos nas mesmas datas.

    Linhas são datas (crescentes) e colunas são tickers. Só entram datas em que todos
    os ativos têm preço: assim, o retorno entre duas linhas consecutivas é o retorno
    real do período, mesmo que entre elas haja feriado em uma das bolsas.

    `float64` é permitido aqui: é série analítica, não saldo (CLAUDE.md 5.2).

    Attributes:
        dates: Datas das linhas, em ordem crescente.
        tickers: Tickers canônicos das colunas.
        prices: Matriz (len(dates) x len(tickers)) de preços positivos em BRL.
    """

    dates: tuple[date, ...]
    tickers: tuple[str, ...]
    prices: NDArray[np.float64]

    def __post_init__(self) -> None:
        if self.prices.shape != (len(self.dates), len(self.tickers)):
            raise DomainError(
                f"Formato inválido: {self.prices.shape} para "
                f"{len(self.dates)} datas x {len(self.tickers)} tickers."
            )
        if len(set(self.tickers)) != len(self.tickers):
            raise DomainError("Tickers repetidos na série de preços.")
        if any(
            later <= earlier for earlier, later in zip(self.dates, self.dates[1:], strict=False)
        ):
            raise DomainError("Datas da série de preços precisam ser estritamente crescentes.")
        if self.prices.size and (not np.isfinite(self.prices).all() or (self.prices <= 0).any()):
            raise DomainError("Série de preços com valor ausente, infinito ou não positivo.")

    def __len__(self) -> int:
        return len(self.dates)

    def column(self, ticker: str) -> NDArray[np.float64]:
        """Preços de um ticker ao longo das datas."""
        try:
            index = self.tickers.index(ticker)
        except ValueError as error:
            raise MissingMarketDataError(f"Sem preços para {ticker}.") from error
        return self.prices[:, index]

    def simple_returns(self) -> NDArray[np.float64]:
        """Retornos simples entre linhas consecutivas: P_t / P_{t-1} - 1.

        Returns:
            Matriz (len(dates) - 1) x len(tickers).
        """
        return self.prices[1:] / self.prices[:-1] - 1.0

    def latest(self) -> dict[str, float]:
        """Último preço de cada ticker."""
        if not self.dates:
            raise MissingMarketDataError("Série de preços vazia.")
        return {ticker: float(self.prices[-1, i]) for i, ticker in enumerate(self.tickers)}
