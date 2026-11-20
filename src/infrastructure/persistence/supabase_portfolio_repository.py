"""Implementação de `PortfolioRepository` sobre o Supabase (PostgREST com RLS)."""

from typing import Any, cast

from supabase import Client

from domain.entities.portfolio import Portfolio
from domain.repositories.portfolio_repository import PortfolioRepository


class SupabasePortfolioRepository(PortfolioRepository):
    """Acessa as tabelas `portfolios` e `allocation_targets`.

    O cliente precisa estar autenticado com a sessão do usuário. Assim o PostgREST
    envia o JWT dele e o RLS (`auth.uid() = user_id`) restringe todas as linhas.
    Por isso não há filtro por `user_id` nas leituras: o banco já faz esse filtro.
    """

    def __init__(self, client: Client) -> None:
        self._client = client

    def list_portfolios(self) -> list[Portfolio]:
        response = self._client.table("portfolios").select("id, name").order("created_at").execute()
        # O PostgREST devolve JSON sem tipo; o cast documenta o formato esperado.
        rows = cast(list[dict[str, Any]], response.data)
        return [Portfolio(id=str(row["id"]), name=str(row["name"])) for row in rows]

    def create_portfolio(self, user_id: str, name: str) -> Portfolio:
        # `user_id` é obrigatório no insert. Se for diferente do usuário da sessão,
        # o `with check` do RLS rejeita a gravação.
        response = (
            self._client.table("portfolios").insert({"user_id": user_id, "name": name}).execute()
        )
        # O insert devolve a linha criada (representation), incluindo o id gerado.
        row = cast(list[dict[str, Any]], response.data)[0]
        return Portfolio(id=str(row["id"]), name=str(row["name"]))

    def get_allocation_targets(self, portfolio_id: str) -> dict[str, float]:
        response = (
            self._client.table("allocation_targets")
            .select("asset_class, target_pct")
            .eq("portfolio_id", portfolio_id)
            .execute()
        )
        rows = cast(list[dict[str, Any]], response.data)
        # `target_pct` é numeric no banco e chega como número JSON; vira float para a UI.
        return {str(row["asset_class"]): float(row["target_pct"]) for row in rows}

    def save_allocation_targets(
        self, user_id: str, portfolio_id: str, targets: dict[str, float]
    ) -> None:
        # A função SQL apaga e reinsere o perfil na mesma transação, para que classes
        # removidas não sobrem. O dono vem de `auth.uid()` no banco; `user_id` faz parte
        # do contrato (o fake usa) mas não é enviado, para o cliente não conseguir forjá-lo.
        del user_id
        self._client.rpc(
            "replace_allocation_targets",
            {"p_portfolio_id": portfolio_id, "p_targets": targets},
        ).execute()
