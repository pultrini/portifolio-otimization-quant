"""Composition root: monta repositórios concretos e injeta nos use cases.

É o único módulo da apresentação que conhece a Infrastructure. As páginas recebem o
`Container` pronto e só chamam use cases.
"""

from dataclasses import dataclass

from supabase import Client

from application.use_cases.contribution import (
    ExecuteContribution,
    GetChecklist,
    GetChecklistWeights,
    RefreshFundamentals,
    SaveChecklist,
    SaveChecklistWeights,
    SuggestAssetContribution,
)
from application.use_cases.goals import (
    CreateGoal,
    DeleteGoal,
    GetGoalDashboard,
    ListGoals,
    PreviewGoal,
    RegisterDeposit,
    UndoDeposit,
)
from application.use_cases.import_positions import ImportPositions
from application.use_cases.mark_to_market import GetMarkToMarket, SaveBondTerms
from application.use_cases.market_data import RefreshMarketData
from application.use_cases.metrics import CalculateMetrics
from application.use_cases.optimization import (
    OptimizePortfolio,
    SimulateQuantPortfolio,
    SuggestContribution,
)
from application.use_cases.portfolios import CreatePortfolio, GetAllocationTargets, ListPortfolios
from application.use_cases.positions import (
    DeletePosition,
    ListPositions,
    ReclassifyRealEstate,
    UpdatePosition,
)
from application.use_cases.save_allocation_targets import SaveAllocationTargets
from application.use_cases.trades import ListTrades, RegisterTrade
from domain.repositories.fundamentals_repository import (
    ChecklistRepository,
    FundamentalsRefresher,
    FundamentalsRepository,
)
from domain.repositories.market_data_repository import (
    BondTermsRepository,
    MarketDataRefresher,
    MarketDataRepository,
    TreasuryRepository,
)
from domain.repositories.portfolio_repository import PortfolioRepository
from domain.repositories.position_repository import PositionRepository
from domain.repositories.savings_goal_repository import SavingsGoalRepository
from domain.repositories.trade_repository import TradeRepository
from infrastructure.config import Settings
from infrastructure.data_engineering.fundamentals import FundamentalsPipeline
from infrastructure.data_engineering.pipeline import build_default_pipeline
from infrastructure.market_data.fundamentals_clients import CvmClient, YahooFundamentalsClient
from infrastructure.persistence.parquet_fundamentals_repository import ParquetFundamentalsRepository
from infrastructure.persistence.parquet_market_data_repository import ParquetMarketDataRepository
from infrastructure.persistence.parquet_treasury_repository import ParquetTreasuryRepository
from infrastructure.persistence.supabase_bond_terms_repository import SupabaseBondTermsRepository
from infrastructure.persistence.supabase_checklist_repository import SupabaseChecklistRepository
from infrastructure.persistence.supabase_portfolio_repository import SupabasePortfolioRepository
from infrastructure.persistence.supabase_position_repository import (
    SupabasePositionRepository,
    SupabaseTradeRepository,
)
from infrastructure.persistence.supabase_savings_goal_repository import (
    SupabaseSavingsGoalRepository,
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
    reclassify_real_estate: ReclassifyRealEstate
    register_trade: RegisterTrade
    list_trades: ListTrades
    refresh_market_data: RefreshMarketData
    calculate_metrics: CalculateMetrics
    optimize_portfolio: OptimizePortfolio
    simulate_quant_portfolio: SimulateQuantPortfolio
    suggest_contribution: SuggestContribution
    suggest_asset_contribution: SuggestAssetContribution
    execute_contribution: ExecuteContribution
    get_checklist: GetChecklist
    save_checklist: SaveChecklist
    get_checklist_weights: GetChecklistWeights
    save_checklist_weights: SaveChecklistWeights
    refresh_fundamentals: RefreshFundamentals
    preview_goal: PreviewGoal
    create_goal: CreateGoal
    list_goals: ListGoals
    delete_goal: DeleteGoal
    goal_dashboard: GetGoalDashboard
    register_deposit: RegisterDeposit
    undo_deposit: UndoDeposit
    mark_to_market: GetMarkToMarket
    save_bond_terms: SaveBondTerms


def assemble(
    portfolios: PortfolioRepository,
    positions: PositionRepository,
    trades: TradeRepository,
    market_data: MarketDataRepository,
    refresher: MarketDataRefresher,
    years: int,
    fundamentals: FundamentalsRepository,
    fundamentals_refresher: FundamentalsRefresher,
    checklist: ChecklistRepository,
    goals: SavingsGoalRepository,
    treasury: TreasuryRepository,
    bond_terms: BondTermsRepository,
) -> Container:
    """Liga os use cases a quaisquer implementações dos contratos do domínio.

    Separado de `build_container` para que os testes de interface usem o mesmo
    container com repositórios em memória.
    """
    register_trade = RegisterTrade(positions, trades, fundamentals)
    suggest_contribution = SuggestContribution(portfolios, positions, market_data)
    return Container(
        list_portfolios=ListPortfolios(portfolios),
        create_portfolio=CreatePortfolio(portfolios),
        get_allocation_targets=GetAllocationTargets(portfolios),
        save_allocation_targets=SaveAllocationTargets(portfolios),
        list_positions=ListPositions(positions, market_data),
        import_positions=ImportPositions(positions, market_data, refresher, years, fundamentals),
        update_position=UpdatePosition(positions),
        delete_position=DeletePosition(positions),
        reclassify_real_estate=ReclassifyRealEstate(positions, fundamentals),
        register_trade=register_trade,
        list_trades=ListTrades(trades),
        refresh_market_data=RefreshMarketData(refresher, positions, years),
        calculate_metrics=CalculateMetrics(positions, trades, market_data),
        optimize_portfolio=OptimizePortfolio(positions, market_data),
        simulate_quant_portfolio=SimulateQuantPortfolio(portfolios, positions, market_data),
        suggest_contribution=suggest_contribution,
        suggest_asset_contribution=SuggestAssetContribution(
            suggest_contribution, positions, market_data, fundamentals, checklist
        ),
        execute_contribution=ExecuteContribution(register_trade),
        get_checklist=GetChecklist(fundamentals, checklist, market_data),
        save_checklist=SaveChecklist(checklist),
        get_checklist_weights=GetChecklistWeights(checklist),
        save_checklist_weights=SaveChecklistWeights(checklist),
        refresh_fundamentals=RefreshFundamentals(fundamentals_refresher, positions),
        preview_goal=PreviewGoal(),
        create_goal=CreateGoal(goals),
        list_goals=ListGoals(goals),
        delete_goal=DeleteGoal(goals),
        goal_dashboard=GetGoalDashboard(goals),
        register_deposit=RegisterDeposit(goals),
        undo_deposit=UndoDeposit(goals),
        mark_to_market=GetMarkToMarket(positions, treasury, bond_terms),
        save_bond_terms=SaveBondTerms(positions, treasury, bond_terms),
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
        fundamentals=ParquetFundamentalsRepository(settings.data_dir),
        fundamentals_refresher=FundamentalsPipeline(
            settings.data_dir, YahooFundamentalsClient(), CvmClient()
        ),
        checklist=SupabaseChecklistRepository(client),
        goals=SupabaseSavingsGoalRepository(client),
        treasury=ParquetTreasuryRepository(settings.data_dir),
        bond_terms=SupabaseBondTermsRepository(client),
    )
