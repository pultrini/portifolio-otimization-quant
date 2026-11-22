"""Taxa contratada dos títulos do Tesouro no Supabase (tabela `bond_terms`, com RLS)."""

from datetime import date
from typing import Any, cast

from supabase import Client

from domain.entities.treasury import BondTerms
from domain.repositories.market_data_repository import BondTermsRepository
from domain.value_objects.ticker import Ticker


class SupabaseBondTermsRepository(BondTermsRepository):
    def __init__(self, client: Client) -> None:
        self._client = client

    def terms(self, portfolio_id: str) -> dict[Ticker, BondTerms]:
        response = (
            self._client.table("bond_terms")
            # Numérico como texto: a taxa não passa por float no caminho.
            .select("ticker, contracted_rate::text, purchase_date, estimated")
            .eq("portfolio_id", portfolio_id)
            .execute()
        )
        result: dict[Ticker, BondTerms] = {}
        for row in cast(list[dict[str, Any]], response.data):
            purchase = row.get("purchase_date")
            result[Ticker(str(row["ticker"]))] = BondTerms(
                contracted_rate=float(row["contracted_rate"]),
                purchase_date=date.fromisoformat(purchase) if purchase else None,
                estimated=bool(row["estimated"]),
            )
        return result

    def save_terms(self, user_id: str, portfolio_id: str, ticker: Ticker, terms: BondTerms) -> None:
        self._client.table("bond_terms").upsert(
            {
                "user_id": user_id,
                "portfolio_id": portfolio_id,
                "ticker": ticker.symbol,
                "contracted_rate": round(terms.contracted_rate, 6),
                "purchase_date": terms.purchase_date.isoformat() if terms.purchase_date else None,
                "estimated": terms.estimated,
            },
            on_conflict="portfolio_id,ticker",
        ).execute()

    def delete_terms(self, portfolio_id: str, ticker: Ticker) -> None:
        (
            self._client.table("bond_terms")
            .delete()
            .eq("portfolio_id", portfolio_id)
            .eq("ticker", ticker.symbol)
            .execute()
        )
