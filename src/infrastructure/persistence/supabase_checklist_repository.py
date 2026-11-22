"""Checklist no Supabase: respostas manuais (`checklist_answers`) e pesos (`checklist_weights`).

As duas tabelas têm RLS: sem filtro por usuário, o select só enxerga as linhas da sessão.
"""

from collections.abc import Sequence
from typing import Any, cast

from supabase import Client

from domain.repositories.fundamentals_repository import ChecklistRepository
from domain.value_objects.checklist import ChecklistWeights
from domain.value_objects.ticker import Ticker


class SupabaseChecklistRepository(ChecklistRepository):
    def __init__(self, client: Client) -> None:
        self._client = client

    def answers(self, tickers: Sequence[Ticker]) -> dict[Ticker, dict[str, bool | None]]:
        if not tickers:
            return {}
        response = (
            self._client.table("checklist_answers")
            .select("ticker, question_key, answer")
            .in_("ticker", [t.symbol for t in tickers])
            .execute()
        )
        result: dict[Ticker, dict[str, bool | None]] = {}
        for row in cast(list[dict[str, Any]], response.data):
            result.setdefault(Ticker(str(row["ticker"])), {})[str(row["question_key"])] = bool(
                row["answer"]
            )
        return result

    def save_answers(self, user_id: str, ticker: Ticker, answers: dict[str, bool | None]) -> None:
        # Respostas preenchidas viram upsert; "sem resposta" apaga a linha para que a
        # resposta automática volte a valer.
        rows = [
            {"user_id": user_id, "ticker": ticker.symbol, "question_key": key, "answer": value}
            for key, value in answers.items()
            if value is not None
        ]
        cleared = [key for key, value in answers.items() if value is None]
        if rows:
            self._client.table("checklist_answers").upsert(
                rows, on_conflict="user_id,ticker,question_key"
            ).execute()
        if cleared:
            (
                self._client.table("checklist_answers")
                .delete()
                .eq("ticker", ticker.symbol)
                .in_("question_key", cleared)
                .execute()
            )

    def weights(self) -> ChecklistWeights:
        # Numéricos chegam como texto para não perder precisão no caminho (padrão do projeto).
        response = (
            self._client.table("checklist_weights")
            .select("yes_weight::text, no_weight::text")
            .limit(1)
            .execute()
        )
        rows = cast(list[dict[str, Any]], response.data)
        if not rows:
            return ChecklistWeights()
        return ChecklistWeights(yes=float(rows[0]["yes_weight"]), no=float(rows[0]["no_weight"]))

    def save_weights(self, user_id: str, weights: ChecklistWeights) -> None:
        self._client.table("checklist_weights").upsert(
            {"user_id": user_id, "yes_weight": weights.yes, "no_weight": weights.no},
            on_conflict="user_id",
        ).execute()
