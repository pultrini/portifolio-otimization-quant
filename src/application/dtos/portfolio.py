"""DTOs de carteira, posições e operações."""

from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, Field

from domain.value_objects.asset_class import AssetClass
from domain.value_objects.strategy_type import StrategyType, TradeSide


class PortfolioDTO(BaseModel):
    id: str
    name: str


class CreatePortfolioRequest(BaseModel):
    user_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=80)


class PositionRow(BaseModel):
    """Uma linha da tabela de posições, já valorizada a mercado.

    Campos de mercado são None quando o ativo ainda não tem cotação na camada Gold.
    """

    ticker: str
    asset_class: AssetClass
    quantity: Decimal
    average_price: Decimal
    cost: Decimal
    manual_override: bool
    last_price: Decimal | None = None
    market_value: Decimal | None = None
    pnl: Decimal | None = None
    pnl_pct: float | None = None
    weight_pct: float | None = None


class PositionsView(BaseModel):
    """Posições abertas com totais por classe de ativo."""

    rows: list[PositionRow]
    total_cost: Decimal
    total_market_value: Decimal | None
    market_value_by_class: dict[AssetClass, Decimal]
    missing_prices: list[str]
    # Ativos com 0 cotas: desejados, ainda não comprados. Concorrem nas sugestões de aporte.
    watchlist: list[str] = []


class UpdatePositionRequest(BaseModel):
    user_id: str = Field(min_length=1)
    portfolio_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    average_price: Decimal | None = Field(default=None, ge=0)
    asset_class: AssetClass | None = None


class ImportPositionsRequest(BaseModel):
    """Texto colado pelo usuário, uma posição por linha.

    Formatos aceitos (vírgula ou ponto decimal; quantidade 0 = lista de desejos):
        `TICKER QUANTIDADE PRECO_MEDIO`          ex.: `EGIE3 2 29,30`
        `TICKER R$ VALOR_ATUAL [VALOR_INVESTIDO]` ex.: `BTC R$ 158,00 175,20`
    """

    user_id: str = Field(min_length=1)
    portfolio_id: str = Field(min_length=1)
    text: str
    replace_existing: bool = False


class ImportPositionsResponse(BaseModel):
    imported: list[str]
    errors: list[str]


class RegisterTradeRequest(BaseModel):
    user_id: str = Field(min_length=1)
    portfolio_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    side: TradeSide
    strategy: StrategyType
    # AwareDatetime: rejeita data/hora sem fuso já na entrada.
    traded_at: AwareDatetime
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(ge=0)
    costs: Decimal = Field(default=Decimal("0"), ge=0)
    asset_class: AssetClass | None = None


class TradeRow(BaseModel):
    id: str | None
    ticker: str
    side: TradeSide
    strategy: StrategyType
    traded_at: datetime
    quantity: Decimal
    price: Decimal
    costs: Decimal
    cash_flow: Decimal
