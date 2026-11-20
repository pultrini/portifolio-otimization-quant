"""Regras de preço médio (CLAUDE.md 5.3).

Funções puras: recebem a posição atual e devolvem uma nova, sem I/O.
"""

from decimal import Decimal

from domain.entities.position import Position
from domain.entities.trade import Trade
from domain.exceptions import DomainError, InsufficientQuantityError
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.money import Money
from domain.value_objects.strategy_type import TradeSide


def apply_buy(position: Position | None, trade: Trade, asset_class: AssetClass) -> Position:
    """Soma uma compra à posição e recalcula o preço médio ponderado.

    Fórmula:
        PM_novo = (PM_atual x Q_atual + P_compra x Q_compra + custos) / (Q_atual + Q_compra)

    Os custos entram no preço médio porque fazem parte do custo de aquisição (é o que a
    Receita considera no ganho de capital). O resultado deixa de ser manual: passa a ser
    o cálculo a partir do preço médio vigente, mesmo que ele tenha sido editado.

    Args:
        position: Posição atual, ou None se o ativo ainda não está na carteira.
        trade: Operação de compra.
        asset_class: Classe usada quando a posição ainda não existe.

    Returns:
        Nova posição com quantidade e preço médio atualizados.
    """
    if trade.side is not TradeSide.BUY:
        raise DomainError("apply_buy recebeu uma venda.")
    if position is None:
        position = Position(trade.ticker, asset_class, Decimal("0"), Money.zero())

    new_quantity = position.quantity + trade.quantity
    new_total_cost = position.total_cost + trade.gross_value + trade.costs
    return Position(
        ticker=position.ticker,
        asset_class=position.asset_class,
        quantity=new_quantity,
        average_price=new_total_cost / new_quantity,
        manual_override=False,
    )


def apply_sell(position: Position | None, trade: Trade) -> Position:
    """Reduz a quantidade sem alterar o preço médio.

    O preço médio é o custo das unidades que restam; vender não muda quanto elas
    custaram. O lucro da venda é apurado à parte (ver `trade_matching`).

    Raises:
        InsufficientQuantityError: venda maior que a posição (sem venda a descoberto).
    """
    if trade.side is not TradeSide.SELL:
        raise DomainError("apply_sell recebeu uma compra.")
    held = position.quantity if position is not None else Decimal("0")
    if position is None or trade.quantity > held:
        raise InsufficientQuantityError(
            f"{trade.ticker}: venda de {trade.quantity} com apenas {held} em carteira."
        )
    return Position(
        ticker=position.ticker,
        asset_class=position.asset_class,
        quantity=position.quantity - trade.quantity,
        average_price=position.average_price,
        manual_override=position.manual_override,
    )


def apply_trade(position: Position | None, trade: Trade, asset_class: AssetClass) -> Position:
    """Despacha para compra ou venda conforme o lado da operação."""
    if trade.side is TradeSide.BUY:
        return apply_buy(position, trade, asset_class)
    return apply_sell(position, trade)


def apply_split(position: Position, ratio: Decimal) -> Position:
    """Ajusta a posição por desdobramento ou grupamento, mantendo o custo total.

    `ratio` é quantas ações novas cada ação antiga vira: 2 para um desdobramento 1:2,
    0.1 para um grupamento 10:1. Quantidade multiplica e preço médio divide pelo mesmo
    fator, então `quantidade x preço médio` não muda.
    """
    if ratio <= 0:
        raise DomainError("Fator de desdobramento/grupamento deve ser positivo.")
    return Position(
        ticker=position.ticker,
        asset_class=position.asset_class,
        quantity=position.quantity * ratio,
        average_price=position.average_price / ratio,
        manual_override=position.manual_override,
    )


def override_average_price(position: Position, new_average_price: Money) -> Position:
    """Aplica a edição manual do usuário e marca `manual_override`.

    O valor digitado prevalece sobre o calculado (ex.: custódia transferida de outra
    corretora com histórico incompleto). A flag permite mostrar que o número é manual.
    """
    return Position(
        ticker=position.ticker,
        asset_class=position.asset_class,
        quantity=position.quantity,
        average_price=new_average_price,
        manual_override=True,
    )
