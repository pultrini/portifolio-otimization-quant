"""Implementações Supabase de `PositionRepository` e `TradeRepository`."""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from supabase import Client

from domain.entities.position import Position
from domain.entities.trade import Trade
from domain.repositories.position_repository import PositionRepository
from domain.repositories.trade_repository import TradeRepository
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.money import Money
from domain.value_objects.strategy_type import StrategyType, TradeSide
from domain.value_objects.ticker import Ticker

# Mesma escala das colunas numeric(20, 8).
_DB_STEP = Decimal("0.00000001")

# `::text` faz o PostgREST devolver o numeric como texto exato. Sem isso ele viria como
# número JSON, convertido para float pelo cliente, e o Decimal herdaria o erro binário.
_POSITION_COLUMNS = "ticker, asset_class, quantity::text, average_price::text, manual_override"
_TRADE_COLUMNS = "id, ticker, side, strategy, traded_at, quantity::text, price::text, costs::text"


def to_db_number(value: Decimal) -> str:
    """Arredonda para 8 casas e envia como texto (o Postgres converte para numeric)."""
    return str(value.quantize(_DB_STEP))


def _rows(data: Any) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], data)


def _to_position(row: dict[str, Any]) -> Position:
    return Position(
        ticker=Ticker(str(row["ticker"])),
        asset_class=AssetClass(str(row["asset_class"])),
        quantity=Decimal(str(row["quantity"])),
        average_price=Money.brl(str(row["average_price"])),
        manual_override=bool(row["manual_override"]),
    )


class SupabasePositionRepository(PositionRepository):
    """Tabela `positions`. O RLS garante que só as posições do usuário são vistas."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def list_positions(self, portfolio_id: str) -> list[Position]:
        response = (
            self._client.table("positions")
            .select(_POSITION_COLUMNS)
            .eq("portfolio_id", portfolio_id)
            .order("ticker")
            .execute()
        )
        return [_to_position(row) for row in _rows(response.data)]

    def get_position(self, portfolio_id: str, ticker: Ticker) -> Position | None:
        response = (
            self._client.table("positions")
            .select(_POSITION_COLUMNS)
            .eq("portfolio_id", portfolio_id)
            .eq("ticker", ticker.symbol)
            .execute()
        )
        rows = _rows(response.data)
        return _to_position(rows[0]) if rows else None

    def save_positions(
        self, user_id: str, portfolio_id: str, positions: Sequence[Position]
    ) -> None:
        if not positions:
            return
        payload = [
            {
                "user_id": user_id,
                "portfolio_id": portfolio_id,
                "ticker": p.ticker.symbol,
                "asset_class": p.asset_class.value,
                "quantity": to_db_number(p.quantity),
                "average_price": to_db_number(p.average_price.amount),
                "manual_override": p.manual_override,
            }
            for p in positions
        ]
        # Um único upsert: todas as linhas entram na mesma transação do PostgREST.
        self._client.table("positions").upsert(payload, on_conflict="portfolio_id,ticker").execute()

    def delete_position(self, portfolio_id: str, ticker: Ticker) -> None:
        (
            self._client.table("positions")
            .delete()
            .eq("portfolio_id", portfolio_id)
            .eq("ticker", ticker.symbol)
            .execute()
        )


class SupabaseTradeRepository(TradeRepository):
    """Tabela `trades` e função `record_trade` (operação + posição na mesma transação)."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def list_trades(self, portfolio_id: str) -> list[Trade]:
        response = (
            self._client.table("trades")
            .select(_TRADE_COLUMNS)
            .eq("portfolio_id", portfolio_id)
            # Desempate por created_at mantém a ordem de registro no mesmo instante.
            .order("traded_at")
            .order("created_at")
            .execute()
        )
        return [
            Trade(
                ticker=Ticker(str(row["ticker"])),
                side=TradeSide(str(row["side"])),
                strategy=StrategyType(str(row["strategy"])),
                # timestamptz chega em ISO 8601 com offset; normaliza para UTC.
                traded_at=datetime.fromisoformat(str(row["traded_at"])).astimezone(UTC),
                quantity=Decimal(str(row["quantity"])),
                price=Money.brl(str(row["price"])),
                costs=Money.brl(str(row["costs"])),
                id=str(row["id"]),
            )
            for row in _rows(response.data)
        ]

    def record_trade(
        self,
        user_id: str,
        portfolio_id: str,
        trade: Trade,
        previous_quantity: Decimal | None,
        resulting_position: Position,
    ) -> str:
        # O dono vem de auth.uid() dentro da função; user_id não é enviado.
        del user_id
        response = self._client.rpc(
            "record_trade",
            {
                "p_portfolio_id": portfolio_id,
                "p_ticker": trade.ticker.symbol,
                "p_asset_class": resulting_position.asset_class.value,
                "p_side": trade.side.value,
                "p_strategy": trade.strategy.value,
                "p_traded_at": trade.traded_at.isoformat(),
                "p_quantity": to_db_number(trade.quantity),
                "p_price": to_db_number(trade.price.amount),
                "p_costs": to_db_number(trade.costs.amount),
                "p_expected_quantity": (
                    to_db_number(previous_quantity) if previous_quantity is not None else None
                ),
                "p_new_quantity": to_db_number(resulting_position.quantity),
                "p_new_average_price": to_db_number(resulting_position.average_price.amount),
                "p_new_manual_override": resulting_position.manual_override,
            },
        ).execute()
        return str(response.data)
