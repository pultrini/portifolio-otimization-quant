"""Operação de compra ou venda."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from domain.exceptions import DomainError
from domain.value_objects.money import Currency, Money
from domain.value_objects.strategy_type import StrategyType, TradeSide
from domain.value_objects.ticker import Ticker


@dataclass(frozen=True, slots=True)
class Trade:
    """Uma operação executada, pertencente a exatamente uma estratégia.

    Attributes:
        ticker: Ativo negociado.
        side: Compra ou venda.
        strategy: Estratégia operacional (segrega as métricas).
        traded_at: Data/hora em UTC (persistência sempre em UTC).
        quantity: Quantidade negociada, sempre positiva.
        price: Preço unitário em BRL.
        costs: Corretagem, emolumentos e taxas em BRL.
        id: Identificador persistido, quando já existe.
    """

    ticker: Ticker
    side: TradeSide
    strategy: StrategyType
    traded_at: datetime
    quantity: Decimal
    price: Money
    costs: Money
    id: str | None = None

    def __post_init__(self) -> None:
        # Datas sem fuso são ambíguas (UTC? São Paulo?); exigir fuso evita erro de pregão.
        if self.traded_at.tzinfo is None or self.traded_at.utcoffset() != timedelta(0):
            raise DomainError("traded_at precisa estar em UTC.")
        if self.quantity <= 0:
            raise DomainError("Quantidade da operação deve ser positiva.")
        if self.price.is_negative() or self.costs.is_negative():
            raise DomainError("Preço e custos não podem ser negativos.")
        if self.price.currency is not Currency.BRL or self.costs.currency is not Currency.BRL:
            raise DomainError("Preço e custos da operação devem estar em BRL.")

    @property
    def gross_value(self) -> Money:
        """Valor financeiro bruto: preço x quantidade."""
        return self.price * self.quantity

    @property
    def cash_flow(self) -> Money:
        """Fluxo de caixa do investidor: compra é saída (negativo), venda é entrada.

        Custos sempre reduzem o caixa: aumentam a saída na compra e reduzem a entrada
        na venda.
        """
        if self.side is TradeSide.BUY:
            return -(self.gross_value + self.costs)
        return self.gross_value - self.costs

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(UTC)
