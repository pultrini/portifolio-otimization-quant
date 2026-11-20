"""Use cases de operações: registrar e listar."""

from datetime import UTC

from application.dtos.portfolio import RegisterTradeRequest, TradeRow
from domain.entities.trade import Trade
from domain.repositories.position_repository import PositionRepository
from domain.repositories.trade_repository import TradeRepository
from domain.services.asset_classification import infer_asset_class
from domain.services.average_price import apply_trade
from domain.value_objects.money import Money
from domain.value_objects.ticker import Ticker


def _to_row(trade: Trade) -> TradeRow:
    return TradeRow(
        id=trade.id,
        ticker=trade.ticker.symbol,
        side=trade.side,
        strategy=trade.strategy,
        traded_at=trade.traded_at,
        quantity=trade.quantity,
        price=trade.price.amount,
        costs=trade.costs.amount,
        cash_flow=trade.cash_flow.amount,
    )


class RegisterTrade:
    """Registra uma operação e atualiza a posição com a regra de preço médio."""

    def __init__(self, positions: PositionRepository, trades: TradeRepository) -> None:
        self._positions = positions
        self._trades = trades

    def execute(self, request: RegisterTradeRequest) -> TradeRow:
        """Valida a operação, recalcula a posição e grava as duas juntas.

        Raises:
            InsufficientQuantityError: venda maior que a posição.
            DomainError: operação inválida (data sem UTC, valores negativos...).
        """
        ticker = Ticker.parse(request.ticker)
        trade = Trade(
            ticker=ticker,
            side=request.side,
            strategy=request.strategy,
            # Persistência sempre em UTC; a interface converte de America/Sao_Paulo.
            traded_at=request.traded_at.astimezone(UTC),
            quantity=request.quantity,
            price=Money.brl(request.price),
            costs=Money.brl(request.costs),
        )
        current = self._positions.get_position(request.portfolio_id, ticker)
        # Classe: a informada, senão a da posição existente, senão a inferida do ticker.
        asset_class = request.asset_class or (
            current.asset_class if current is not None else infer_asset_class(ticker)
        )
        resulting = apply_trade(current, trade, asset_class)
        trade_id = self._trades.record_trade(
            user_id=request.user_id,
            portfolio_id=request.portfolio_id,
            trade=trade,
            previous_quantity=current.quantity if current is not None else None,
            resulting_position=resulting,
        )
        row = _to_row(trade)
        row.id = trade_id
        return row


class ListTrades:
    """Histórico de operações da carteira, da mais recente para a mais antiga."""

    def __init__(self, trades: TradeRepository) -> None:
        self._trades = trades

    def execute(self, portfolio_id: str) -> list[TradeRow]:
        trades = self._trades.list_trades(portfolio_id)
        return [_to_row(trade) for trade in reversed(trades)]
