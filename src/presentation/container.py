"""Composition root: monta repositórios concretos e injeta nos use cases.

É o único módulo da apresentação que conhece a Infrastructure. As páginas recebem o
`Container` pronto e só chamam use cases.
"""

from dataclasses import dataclass

from supabase import Client

from application.use_cases.import_positions import ImportPositions
from application.use_cases.portfolios import CreatePortfolio, GetAllocationTargets, ListPortfolios
from application.use_cases.positions import DeletePosition, ListPositions, UpdatePosition
from application.use_cases.save_allocation_targets import SaveAllocationTargets
from application.use_cases.trades import ListTrades, RegisterTrade
from infrastructure.config import Settings
from infrastructure.persistence.empty_market_data_repository import EmptyMarketDataRepository
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


def build_container(client: Client, settings: Settings) -> Container:
    """Liga cada use case às implementações concretas.

    O cliente Supabase já carrega a sessão do usuário, então todos os repositórios
    operam sob o RLS dele.
    """
    del settings  # usado a partir da camada de dados de mercado
    portfolios = SupabasePortfolioRepository(client)
    positions = SupabasePositionRepository(client)
    trades = SupabaseTradeRepository(client)
    market_data = EmptyMarketDataRepository()
    return Container(
        list_portfolios=ListPortfolios(portfolios),
        create_portfolio=CreatePortfolio(portfolios),
        get_allocation_targets=GetAllocationTargets(portfolios),
        save_allocation_targets=SaveAllocationTargets(portfolios),
        list_positions=ListPositions(positions, market_data),
        import_positions=ImportPositions(positions, market_data),
        update_position=UpdatePosition(positions),
        delete_position=DeletePosition(positions),
        register_trade=RegisterTrade(positions, trades),
        list_trades=ListTrades(trades),
    )
