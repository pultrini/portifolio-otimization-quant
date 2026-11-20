"""Implementação em memória de `PortfolioRepository` para testes unitários."""

import itertools

from domain.entities.portfolio import Portfolio
from domain.repositories.portfolio_repository import PortfolioRepository


class InMemoryPortfolioRepository(PortfolioRepository):
    """Imita o comportamento do Supabase com dicionários, sem I/O.

    Reproduz as duas garantias do banco que os use cases dependem:
    - posse: gravar alvos na carteira de outro usuário falha (FK composta + RLS);
    - substituição: salvar alvos troca o perfil inteiro (função `replace_allocation_targets`).
    """

    def __init__(self) -> None:
        self._portfolios: dict[str, Portfolio] = {}
        self._owners: dict[str, str] = {}
        self._targets: dict[str, dict[str, float]] = {}
        # Ids sequenciais ("1", "2", ...) no lugar do UUID gerado pelo banco.
        self._ids = (str(index) for index in itertools.count(1))

    def list_portfolios(self) -> list[Portfolio]:
        return list(self._portfolios.values())

    def create_portfolio(self, user_id: str, name: str) -> Portfolio:
        portfolio = Portfolio(id=next(self._ids), name=name)
        self._portfolios[portfolio.id] = portfolio
        self._owners[portfolio.id] = user_id
        return portfolio

    def get_allocation_targets(self, portfolio_id: str) -> dict[str, float]:
        # Cópia para o teste não alterar o estado interno por referência.
        return dict(self._targets.get(portfolio_id, {}))

    def save_allocation_targets(
        self, user_id: str, portfolio_id: str, targets: dict[str, float]
    ) -> None:
        if self._owners.get(portfolio_id) != user_id:
            raise PermissionError("Carteira pertence a outro usuário.")
        # Substitui em vez de mesclar, como a função SQL.
        self._targets[portfolio_id] = dict(targets)
