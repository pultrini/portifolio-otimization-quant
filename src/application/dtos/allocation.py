"""DTOs de entrada e saída dos use cases de alocação alvo."""

from typing import Annotated

from pydantic import BaseModel, Field

from domain.value_objects.asset_class import AssetClass

# Percentual em pontos percentuais (0 a 100), mesma faixa do check constraint no banco.
# Validar aqui evita ida ao Supabase com um valor que seria rejeitado de qualquer forma.
TargetPercentage = Annotated[float, Field(ge=0.0, le=100.0)]


class SaveAllocationTargetsRequest(BaseModel):
    """Pedido para salvar o perfil de alocação alvo de uma carteira.

    Attributes:
        user_id: Usuário autenticado dono da carteira.
        portfolio_id: Carteira que receberá o perfil.
        targets: Percentual (0-100) por classe de ativo. Substitui o perfil inteiro.
    """

    user_id: str = Field(min_length=1)
    portfolio_id: str = Field(min_length=1)
    targets: dict[AssetClass, TargetPercentage]


class AllocationTargetsResponse(BaseModel):
    """Perfil de alocação alvo como ficou persistido."""

    portfolio_id: str
    targets: dict[AssetClass, float]
