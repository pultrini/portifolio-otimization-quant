"""Use cases de carteira: listar, criar e ler o perfil de alocação."""

from application.dtos.allocation import AllocationTargetsResponse
from application.dtos.portfolio import CreatePortfolioRequest, PortfolioDTO
from domain.repositories.portfolio_repository import PortfolioRepository
from domain.value_objects.asset_class import AssetClass


class ListPortfolios:
    """Carteiras do usuário autenticado (o RLS filtra no banco)."""

    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def execute(self) -> list[PortfolioDTO]:
        return [PortfolioDTO(id=p.id, name=p.name) for p in self._repository.list_portfolios()]


class CreatePortfolio:
    """Cria uma carteira vazia."""

    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def execute(self, request: CreatePortfolioRequest) -> PortfolioDTO:
        portfolio = self._repository.create_portfolio(request.user_id, request.name.strip())
        return PortfolioDTO(id=portfolio.id, name=portfolio.name)


class GetAllocationTargets:
    """Perfil de alocação alvo salvo para a carteira (vazio se nunca foi definido)."""

    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def execute(self, portfolio_id: str) -> AllocationTargetsResponse:
        saved = self._repository.get_allocation_targets(portfolio_id)
        return AllocationTargetsResponse(
            portfolio_id=portfolio_id,
            targets={AssetClass(key): value for key, value in saved.items()},
        )
