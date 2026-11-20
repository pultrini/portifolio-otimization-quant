"""Posição em carteira: quantidade e preço médio de um ativo."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from domain.exceptions import DomainError
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.money import Currency, Money
from domain.value_objects.ticker import Ticker


@dataclass(frozen=True, slots=True)
class Position:
    """Quantidade de um ativo e seu preço médio de aquisição.

    O preço médio é guardado em BRL, a moeda base: é o custo que o investidor brasileiro
    pagou, inclusive para ativos cotados em dólar (o câmbio da compra já está embutido).

    Attributes:
        ticker: Ativo da posição.
        asset_class: Classe usada na alocação e na escolha de benchmark.
        quantity: Cotas/ações (fracionário permitido para cripto e Tesouro).
        average_price: Preço médio por unidade, incluindo custos de compra.
        manual_override: True quando o usuário editou o preço médio à mão.
    """

    ticker: Ticker
    asset_class: AssetClass
    quantity: Decimal
    average_price: Money
    manual_override: bool = False

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise DomainError(f"{self.ticker}: quantidade negativa ({self.quantity}).")
        if self.average_price.is_negative():
            raise DomainError(f"{self.ticker}: preço médio negativo.")
        if self.average_price.currency is not Currency.BRL:
            raise DomainError(f"{self.ticker}: preço médio deve estar em BRL.")

    @property
    def total_cost(self) -> Money:
        """Custo total da posição: preço médio x quantidade."""
        return self.average_price * self.quantity

    @property
    def is_closed(self) -> bool:
        return self.quantity == 0
