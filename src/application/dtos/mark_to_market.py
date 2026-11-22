"""DTOs da marcação a mercado (vender o título hoje x levar até o vencimento)."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from domain.services.mark_to_market import BondKind


class BondMarkRow(BaseModel):
    """Um título da carteira. Sem taxa contratada, só os dados de mercado vêm preenchidos."""

    ticker: str
    kind: BondKind
    maturity: date | None
    quantity: Decimal
    average_price: Decimal
    quote_date: date | None
    sell_rate: float | None  # taxa de resgate hoje (fração)
    buy_rate: float | None  # taxa de compra hoje do mesmo título (fração)
    contracted_rate: float | None
    estimated: bool = False
    purchase_date: date | None = None
    business_days: int | None = None
    sale_value: Decimal | None = None
    curve_value: Decimal | None = None
    difference: Decimal | None = None
    difference_pct: float | None = None
    break_even_rate: float | None = None
    message: str = ""  # por que não há comparação (Selic, sem cotação, sem taxa...)

    @property
    def favorable(self) -> bool | None:
        return None if self.difference is None else self.difference > 0


class MarkToMarketReport(BaseModel):
    rows: list[BondMarkRow]


class SaveBondTermsRequest(BaseModel):
    """Taxa digitada (em % a.a.) ou estimada pelo preço médio e pela data da compra."""

    user_id: str = Field(min_length=1)
    portfolio_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    contracted_rate_pct: float | None = Field(default=None, ge=-5, le=50)
    purchase_date: date | None = None
