"""Respostas manuais do checklist no Supabase (tabela `checklist_answers`, com RLS)."""

from collections.abc import Sequence
from typing import Any, cast

from supabase import Client

from domain.repositories.fundamentals_repository import ChecklistRepository
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
