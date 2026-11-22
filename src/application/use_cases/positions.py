"""Use cases de posições: valorização, edição e remoção."""

from decimal import Decimal

from application.dtos.portfolio import (
    PositionRow,
    PositionsView,
    ReclassificationRow,
    UpdatePositionRequest,
)
from domain.entities.position import Position
from domain.exceptions import DomainError
from domain.repositories.fundamentals_repository import FundamentalsRepository
from domain.repositories.market_data_repository import MarketDataRepository
from domain.repositories.position_repository import PositionRepository
from domain.services.asset_classification import infer_asset_class
from domain.services.average_price import override_average_price
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.money import Money
from domain.value_objects.ticker import Ticker

HUNDRED = Decimal("100")


class ListPositions:
    """Posições abertas valorizadas pelo último preço da camada Gold."""

    def __init__(self, positions: PositionRepository, market_data: MarketDataRepository) -> None:
        self._positions = positions
        self._market_data = market_data

    def execute(self, portfolio_id: str) -> PositionsView:
        """Monta a tabela de posições com custo, valor de mercado, resultado e peso.

        Fórmulas por linha:
            custo = quantidade x preço médio
            valor de mercado = quantidade x último preço
            resultado = valor de mercado - custo; resultado % = resultado / custo
            peso = valor de mercado / soma dos valores de mercado
        """
        all_positions = self._positions.list_positions(portfolio_id)
        positions = [p for p in all_positions if not p.is_closed]
        watchlist = sorted(p.ticker.symbol for p in all_positions if p.is_closed)
        prices = self._market_data.latest_prices([p.ticker for p in positions])

        rows: list[PositionRow] = []
        by_class: dict[AssetClass, Decimal] = {}
        missing: list[str] = []
        for position in positions:
            cost = position.total_cost.amount
            price = prices.get(position.ticker)
            row = PositionRow(
                ticker=position.ticker.symbol,
                asset_class=position.asset_class,
                quantity=position.quantity,
                average_price=position.average_price.amount,
                cost=cost,
                manual_override=position.manual_override,
            )
            if price is None:
                missing.append(position.ticker.symbol)
            else:
                market_value = position.quantity * price.amount
                row.last_price = price.amount
                row.market_value = market_value
                row.pnl = market_value - cost
                row.pnl_pct = float((market_value - cost) / cost * HUNDRED) if cost else None
                by_class[position.asset_class] = (
                    by_class.get(position.asset_class, Decimal("0")) + market_value
                )
            rows.append(row)

        # Total de mercado só faz sentido se todos os ativos têm preço; senão fica None
        # para a interface não exibir um patrimônio subestimado.
        total_market = sum(by_class.values(), Decimal("0")) if not missing else None
        if total_market:
            for row in rows:
                if row.market_value is not None:
                    row.weight_pct = float(row.market_value / total_market * HUNDRED)

        rows.sort(key=lambda r: (r.asset_class.value, r.ticker))
        return PositionsView(
            rows=rows,
            total_cost=sum((r.cost for r in rows), Decimal("0")),
            total_market_value=total_market,
            market_value_by_class=by_class,
            missing_prices=missing,
            watchlist=watchlist,
            watchlist_classes={
                p.ticker.symbol: p.asset_class for p in all_positions if p.is_closed
            },
        )


class UpdatePosition:
    """Edita preço médio (marca edição manual) e/ou classe de ativo de uma posição."""

    def __init__(self, positions: PositionRepository) -> None:
        self._positions = positions

    def execute(self, request: UpdatePositionRequest) -> None:
        ticker = Ticker.parse(request.ticker)
        position = self._positions.get_position(request.portfolio_id, ticker)
        if position is None:
            raise DomainError(f"{ticker} não está na carteira.")
        if request.average_price is not None:
            position = override_average_price(position, Money.brl(request.average_price))
        if request.asset_class is not None:
            position = Position(
                ticker=position.ticker,
                asset_class=request.asset_class,
                quantity=position.quantity,
                average_price=position.average_price,
                manual_override=position.manual_override,
            )
        self._positions.save_positions(request.user_id, request.portfolio_id, [position])


class DeletePosition:
    """Remove uma posição (as operações registradas continuam no histórico)."""

    def __init__(self, positions: PositionRepository) -> None:
        self._positions = positions

    def execute(self, portfolio_id: str, ticker: str) -> None:
        self._positions.delete_position(portfolio_id, Ticker.parse(ticker))


# Só posições nestas classes são candidatas: antes da 0.5.0 os FIIs entravam em Renda
# Variável Brasil e os REITs em Renda Variável Internacional.
_EQUITY_TO_REAL_ESTATE = {
    AssetClass.BR_EQUITY: AssetClass.BR_REAL_ESTATE,
    AssetClass.INTL_EQUITY: AssetClass.INTL_REAL_ESTATE,
}


class ReclassifyRealEstate:
    """Move FIIs e REITs das classes de renda variável para as classes imobiliárias.

    `preview` lista o que mudaria; `execute` grava. Só troca posições cuja classe atual
    é a de renda variável correspondente (BR_EQUITY -> BR_REAL_ESTATE, INTL_EQUITY ->
    INTL_REAL_ESTATE), para nunca desfazer uma classe escolhida à mão em outra classe.
    """

    def __init__(self, positions: PositionRepository, fundamentals: FundamentalsRepository) -> None:
        self._positions = positions
        self._fundamentals = fundamentals

    def preview(self, portfolio_id: str) -> list[ReclassificationRow]:
        listed = self._fundamentals.listed_reits()
        rows: list[ReclassificationRow] = []
        for position in self._positions.list_positions(portfolio_id):
            target = _EQUITY_TO_REAL_ESTATE.get(position.asset_class)
            if target is not None and infer_asset_class(position.ticker, listed) is target:
                rows.append(
                    ReclassificationRow(
                        ticker=position.ticker.symbol,
                        current=position.asset_class,
                        proposed=target,
                    )
                )
        return rows

    def execute(self, user_id: str, portfolio_id: str) -> list[ReclassificationRow]:
        rows = self.preview(portfolio_id)
        if not rows:
            return rows
        by_ticker = {r.ticker: r.proposed for r in rows}
        moved = [
            Position(
                ticker=p.ticker,
                asset_class=by_ticker[p.ticker.symbol],
                quantity=p.quantity,
                average_price=p.average_price,
                manual_override=p.manual_override,
            )
            for p in self._positions.list_positions(portfolio_id)
            if p.ticker.symbol in by_ticker
        ]
        self._positions.save_positions(user_id, portfolio_id, moved)
        return rows
