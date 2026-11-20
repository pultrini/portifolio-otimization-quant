"""Use case: salvar o perfil de alocação alvo de uma carteira."""

from application.dtos.allocation import AllocationTargetsResponse, SaveAllocationTargetsRequest
from domain.repositories.portfolio_repository import PortfolioRepository
from domain.value_objects.asset_class import AssetClass


class SaveAllocationTargets:
    """Persiste o perfil de alocação alvo via repositório injetado.

    TODO(domínio): validar que a soma fecha em 100% (tolerância 0.01 p.p.) com um serviço
    de domínio antes de chamar o repositório (CLAUDE.md 5.1). Hoje a UI só avisa.
    """

    def __init__(self, repository: PortfolioRepository) -> None:
        # O repositório chega por injeção: em produção é o Supabase, nos testes um fake.
        self._repository = repository

    def execute(self, request: SaveAllocationTargetsRequest) -> AllocationTargetsResponse:
        """Substitui o perfil de alocação e devolve o que ficou persistido.

        Args:
            request: Usuário, carteira e percentuais por classe de ativo.

        Returns:
            Perfil de alocação alvo lido de volta do repositório.
        """
        # O repositório trabalha com chaves texto (valor do enum), o formato do banco.
        targets_by_key = {asset_class.value: pct for asset_class, pct in request.targets.items()}
        self._repository.save_allocation_targets(
            user_id=request.user_id,
            portfolio_id=request.portfolio_id,
            targets=targets_by_key,
        )
        # Relê do repositório em vez de ecoar a entrada: a resposta reflete o que o banco
        # gravou de fato (arredondamento do numeric(5,2), por exemplo).
        saved = self._repository.get_allocation_targets(request.portfolio_id)
        return AllocationTargetsResponse(
            portfolio_id=request.portfolio_id,
            targets={AssetClass(key): value for key, value in saved.items()},
        )
