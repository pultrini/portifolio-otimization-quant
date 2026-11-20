"""Use case: salvar o perfil de alocação alvo de uma carteira."""

from decimal import Decimal

from application.dtos.allocation import AllocationTargetsResponse, SaveAllocationTargetsRequest
from domain.entities.allocation_profile import AllocationProfile
from domain.repositories.portfolio_repository import PortfolioRepository
from domain.value_objects.asset_class import AssetClass


class SaveAllocationTargets:
    """Valida o perfil no domínio e o persiste via repositório injetado."""

    def __init__(self, repository: PortfolioRepository) -> None:
        # O repositório chega por injeção: em produção é o Supabase, nos testes um fake.
        self._repository = repository

    def execute(self, request: SaveAllocationTargetsRequest) -> AllocationTargetsResponse:
        """Valida que o perfil fecha em 100% e substitui o perfil salvo.

        Args:
            request: Usuário, carteira e percentuais por classe de ativo.

        Returns:
            Perfil de alocação alvo lido de volta do repositório.

        Raises:
            InvalidAllocationError: soma fora de 100% ± 0.01 p.p.
        """
        # float -> str -> Decimal: preserva o número digitado (33.33 vira 33.33, não
        # 33.3299999...). Classes com 0% não são gravadas: ausência já significa zero.
        profile = AllocationProfile(
            {
                asset_class: Decimal(str(pct))
                for asset_class, pct in request.targets.items()
                if pct > 0
            }
        )
        self._repository.save_allocation_targets(
            user_id=request.user_id,
            portfolio_id=request.portfolio_id,
            targets={asset_class.value: float(pct) for asset_class, pct in profile.targets.items()},
        )
        # Relê do repositório em vez de ecoar a entrada: a resposta reflete o que o banco
        # gravou de fato (arredondamento do numeric(5,2), por exemplo).
        saved = self._repository.get_allocation_targets(request.portfolio_id)
        return AllocationTargetsResponse(
            portfolio_id=request.portfolio_id,
            targets={AssetClass(key): value for key, value in saved.items()},
        )
