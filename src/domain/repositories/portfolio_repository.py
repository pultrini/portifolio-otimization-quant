"""Contrato de persistência de carteiras e perfis de alocação alvo."""

from typing import Protocol

from domain.entities.portfolio import Portfolio


class PortfolioRepository(Protocol):
    """Abstração de persistência usada pelos use cases.

    Implementações concretas ficam em `infrastructure/persistence`.
    """

    def list_portfolios(self) -> list[Portfolio]:
        """Retorna as carteiras do usuário autenticado."""
        ...

    def create_portfolio(self, user_id: str, name: str) -> Portfolio:
        """Cria uma carteira para o usuário e retorna a versão persistida."""
        ...

    def get_allocation_targets(self, portfolio_id: str) -> dict[str, float]:
        """Retorna o percentual alvo por classe de ativo (valor em p.p.)."""
        ...

    def save_allocation_targets(
        self, user_id: str, portfolio_id: str, targets: dict[str, float]
    ) -> None:
        """Substitui o perfil de alocação alvo da carteira."""
        ...
