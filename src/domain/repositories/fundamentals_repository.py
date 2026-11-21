"""Contratos de fundamentos (dados abertos) e de respostas do checklist."""

from collections.abc import Sequence
from typing import Protocol

from domain.entities.fundamentals import ReitFundamentals, StockFundamentals
from domain.value_objects.ticker import Ticker


class FundamentalsRepository(Protocol):
    """Leitura dos fundamentos já processados (camada Gold)."""

    def stock_fundamentals(self, tickers: Sequence[Ticker]) -> dict[Ticker, StockFundamentals]: ...

    def reit_fundamentals(self, tickers: Sequence[Ticker]) -> dict[Ticker, ReitFundamentals]: ...


class FundamentalsRefresher(Protocol):
    """Baixa e processa fundamentos (Yahoo Finance e CVM) dos tickers."""

    def refresh(self, tickers: Sequence[Ticker]) -> dict[str, str]:
        """Devolve os tickers que falharam, com o motivo."""
        ...


class ChecklistRepository(Protocol):
    """Respostas manuais do usuário ao checklist (prevalecem sobre as automáticas)."""

    def answers(self, tickers: Sequence[Ticker]) -> dict[Ticker, dict[str, bool | None]]: ...

    def save_answers(self, user_id: str, ticker: Ticker, answers: dict[str, bool | None]) -> None:
        """Grava as respostas; None remove a resposta manual (volta a valer a automática)."""
        ...
