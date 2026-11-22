"""Use cases da marcação a mercado dos títulos do Tesouro na carteira."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from application.dtos.mark_to_market import BondMarkRow, MarkToMarketReport, SaveBondTermsRequest
from domain.entities.treasury import BondTerms
from domain.exceptions import DomainError
from domain.repositories.market_data_repository import BondTermsRepository, TreasuryRepository
from domain.repositories.position_repository import PositionRepository
from domain.services.mark_to_market import (
    BondKind,
    bond_kind,
    estimate_contracted_rate,
    mark_to_market,
)
from domain.value_objects.ticker import Ticker


class GetMarkToMarket:
    """Para cada título do Tesouro na carteira: vender hoje x valor na curva contratada.

    A data de referência é a da última cotação (o CSV do Tesouro sai com um dia de
    atraso), não a data de hoje: preço e taxa precisam ser do mesmo dia.
    """

    def __init__(
        self,
        positions: PositionRepository,
        treasury: TreasuryRepository,
        terms: BondTermsRepository,
    ) -> None:
        self._positions = positions
        self._treasury = treasury
        self._terms = terms

    def execute(self, portfolio_id: str) -> MarkToMarketReport:
        bonds = [
            (p, kind)
            for p in self._positions.list_positions(portfolio_id)
            if not p.is_closed and (kind := bond_kind(p.ticker)) is not None
        ]
        quotes = self._treasury.latest_quotes([p.ticker for p, _ in bonds])
        saved = self._terms.terms(portfolio_id)
        rows: list[BondMarkRow] = []
        for position, kind in bonds:
            quote = quotes.get(position.ticker)
            terms = saved.get(position.ticker)
            row = BondMarkRow(
                ticker=position.ticker.symbol,
                kind=kind,
                maturity=quote.maturity if quote else None,
                quantity=position.quantity,
                average_price=position.average_price.amount,
                quote_date=quote.date if quote else None,
                sell_rate=quote.sell_rate if quote else None,
                buy_rate=quote.buy_rate if quote else None,
                contracted_rate=terms.contracted_rate if terms else None,
                estimated=terms.estimated if terms else False,
                purchase_date=terms.purchase_date if terms else None,
            )
            if kind is BondKind.SELIC:
                row.message = "Tesouro Selic acompanha a Selic: a marcação a mercado é quase nula."
            elif quote is None or quote.pu_sell is None or quote.sell_rate is None:
                row.message = "Sem cotação de resgate: atualize os dados de mercado."
            elif terms is None:
                row.message = "Informe a taxa contratada para comparar."
            else:
                try:
                    result = mark_to_market(
                        position.ticker,
                        quote.maturity,
                        quote.date,
                        position.quantity,
                        quote.pu_sell,
                        quote.sell_rate,
                        quote.buy_rate if quote.buy_rate is not None else quote.sell_rate,
                        terms.contracted_rate,
                    )
                except DomainError as error:
                    row.message = str(error)
                else:
                    row.business_days = result.business_days
                    row.sale_value = result.sale_value
                    row.curve_value = result.curve_value
                    row.difference = result.difference
                    row.difference_pct = result.difference_pct
                    row.break_even_rate = result.break_even_rate
            rows.append(row)
        rows.sort(key=lambda r: (r.maturity is None, r.maturity or date.max, r.ticker))
        return MarkToMarketReport(rows=rows)


class SaveBondTerms:
    """Grava a taxa contratada: digitada, ou estimada pelo preço médio e data da compra."""

    def __init__(
        self,
        positions: PositionRepository,
        treasury: TreasuryRepository,
        terms: BondTermsRepository,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._positions = positions
        self._treasury = treasury
        self._terms = terms
        self._today = today

    def execute(self, request: SaveBondTermsRequest) -> float:
        """Returns: a taxa gravada, em fração.

        Raises:
            DomainError: sem taxa nem data, data no futuro, sem cotação na data ou
                título fora da carteira.
        """
        ticker = Ticker.parse(request.ticker)
        if request.contracted_rate_pct is not None:
            terms = BondTerms(request.contracted_rate_pct / 100, request.purchase_date, False)
        elif request.purchase_date is not None:
            terms = BondTerms(
                self._estimate(request.portfolio_id, ticker, request.purchase_date),
                request.purchase_date,
                True,
            )
        else:
            raise DomainError("Informe a taxa contratada ou a data da compra.")
        self._terms.save_terms(request.user_id, request.portfolio_id, ticker, terms)
        return terms.contracted_rate

    def _estimate(self, portfolio_id: str, ticker: Ticker, purchase_date: date) -> float:
        if purchase_date > self._today():
            raise DomainError("A data da compra não pode estar no futuro.")
        position = self._positions.get_position(portfolio_id, ticker)
        if position is None or position.average_price.amount <= 0:
            raise DomainError(f"{ticker} sem preço médio na carteira para estimar a taxa.")
        quote = self._treasury.quote_on(ticker, purchase_date)
        if quote is None or quote.pu_buy is None or quote.buy_rate is None:
            raise DomainError(f"Sem cotação de compra de {ticker} até {purchase_date:%d/%m/%Y}.")
        return estimate_contracted_rate(
            ticker,
            quote.maturity,
            purchase_date,
            float(position.average_price.amount),
            quote.pu_buy,
            quote.buy_rate,
        )
