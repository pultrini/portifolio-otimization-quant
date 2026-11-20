"""Composition root: monta repositórios concretos e injeta nos use cases.

É o único módulo da apresentação que conhece a Infrastructure. As páginas recebem o
`Container` pronto e só chamam use cases.
"""

from dataclasses import dataclass

from supabase import Client

from application.use_cases.import_positions import ImportPositions
from application.use_cases.market_data import RefreshMarketData
from application.use_cases.portfolios import CreatePortfolio, GetAllocationTargets, ListPortfolios
from application.use_cases.positions import DeletePosition, ListPositions, UpdatePosition
from application.use_cases.save_allocation_targets import SaveAllocationTargets
from application.use_cases.trades import ListTrades, RegisterTrade
from domain.repositories.market_data_repository import MarketDataRefresher, MarketDataRepository
from domain.repositories.portfolio_repository import PortfolioRepository
from domain.repositories.position_repository import PositionRepository
from domain.repositories.trade_repository import TradeRepository
from infrastructure.config import Settings
from infrastructure.data_engineering.pipeline import build_default_pipeline
from infrastructure.persistence.parquet_market_data_repository import ParquetMarketDataRepository
from infrastructure.persistence.supabase_portfolio_repository import SupabasePortfolioRepository
from infrastructure.persistence.supabase_position_repository import (
    SupabasePositionRepository,
    SupabaseTradeRepository,
)


@dataclass(frozen=True, slots=True)
class Container:
    """Use cases prontos para a sessão do usuário."""

    list_portfolios: ListPortfolios
    create_portfolio: CreatePortfolio
    get_allocation_targets: GetAllocationTargets
    save_allocation_targets: SaveAllocationTargets
    list_positions: ListPositions
    import_positions: ImportPositions
    update_position: UpdatePosition
    delete_position: DeletePosition
    register_trade: RegisterTrade
    list_trades: ListTrades
    refresh_market_data: RefreshMarketData


def assemble(
    portfolios: PortfolioRepository,
    positions: PositionRepository,
    trades: TradeRepository,
    market_data: MarketDataRepository,
    refresher: MarketDataRefresher,
    years: int,
) -> Container:
    """Liga os use cases a quaisquer implementações dos contratos do domínio.

    Separado de `build_container` para que os testes de interface usem o mesmo
    container com repositórios em memória.
    """
    return Container(
        list_portfolios=ListPortfolios(portfolios),
        create_portfolio=CreatePortfolio(portfolios),
        get_allocation_targets=GetAllocationTargets(portfolios),
        save_allocation_targets=SaveAllocationTargets(portfolios),
        list_positions=ListPositions(positions, market_data),
        import_positions=ImportPositions(positions, market_data, refresher, years),
        update_position=UpdatePosition(positions),
        delete_position=DeletePosition(positions),
        register_trade=RegisterTrade(positions, trades),
        list_trades=ListTrades(trades),
        refresh_market_data=RefreshMarketData(refresher, positions, years),
    )


def build_container(client: Client, settings: Settings) -> Container:
    """Implementações reais: Supabase (com a sessão do usuário, sob RLS) e Parquet local."""
    return assemble(
        portfolios=SupabasePortfolioRepository(client),
        positions=SupabasePositionRepository(client),
        trades=SupabaseTradeRepository(client),
        market_data=ParquetMarketDataRepository(settings.data_dir),
        refresher=build_default_pipeline(settings),
        years=settings.market_history_years,
    )
