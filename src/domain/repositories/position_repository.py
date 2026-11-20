"""Contrato de persistência de posições."""

from collections.abc import Sequence
from typing import Protocol

from domain.entities.position import Position
from domain.value_objects.ticker import Ticker


class PositionRepository(Protocol):
    """Posições de uma carteira (uma por ticker)."""

    def list_positions(self, portfolio_id: str) -> list[Position]:
        """Todas as posições da carteira, inclusive as zeradas."""
        ...

    def get_position(self, portfolio_id: str, ticker: Ticker) -> Position | None:
        """Posição do ticker, ou None se o ativo nunca esteve na carteira."""
        ...

    def save_positions(
        self, user_id: str, portfolio_id: str, positions: Sequence[Position]
    ) -> None:
        """Cria ou substitui as posições informadas (chave: carteira + ticker)."""
        ...

    def delete_position(self, portfolio_id: str, ticker: Ticker) -> None:
        """Remove a posição do ticker. Não apaga operações já registradas."""
        ...
