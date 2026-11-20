"""Contrato de persistência de operações."""

from decimal import Decimal
from typing import Protocol

from domain.entities.position import Position
from domain.entities.trade import Trade


class TradeRepository(Protocol):
    """Operações de uma carteira."""

    def list_trades(self, portfolio_id: str) -> list[Trade]:
        """Operações em ordem cronológica (a ordem importa para o casamento FIFO)."""
        ...

    def record_trade(
        self,
        user_id: str,
        portfolio_id: str,
        trade: Trade,
        previous_quantity: Decimal | None,
        resulting_position: Position,
    ) -> str:
        """Grava a operação e a nova posição de forma atômica.

        Args:
            user_id: Dono da carteira.
            portfolio_id: Carteira da operação.
            trade: Operação já validada pelo domínio.
            previous_quantity: Quantidade lida antes do cálculo (None se não havia
                posição). Se a posição mudou nesse meio tempo, a gravação falha.
            resulting_position: Posição calculada pelo serviço de preço médio.

        Returns:
            Id da operação gravada.
        """
        ...
