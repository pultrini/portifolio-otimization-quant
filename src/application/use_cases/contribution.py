"""Use cases da decisão de aporte por ativo e do registro do aporte ("Aportar")."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from application.dtos.contribution import (
    AssetContributionRequest,
    AssetContributionResult,
    AssetDecisionRow,
    BuyOrder,
    ChecklistQuestionRow,
    ChecklistView,
    ChecklistWeightsDTO,
    ClassDecisionDTO,
    ExecuteContributionRequest,
    ExecuteContributionResult,
    SaveChecklistRequest,
    SaveChecklistWeightsRequest,
)
from application.dtos.optimization import ContributionRequest
from application.dtos.portfolio import RegisterTradeRequest
from application.use_cases.optimization import SuggestContribution
from application.use_cases.trades import RegisterTrade
from domain.entities.fundamentals import ReitFundamentals, StockFundamentals
from domain.entities.position import Position
from domain.exceptions import DomainError, MissingMarketDataError
from domain.repositories.fundamentals_repository import (
    ChecklistRepository,
    FundamentalsRefresher,
    FundamentalsRepository,
)
from domain.repositories.market_data_repository import MarketDataRepository
from domain.repositories.position_repository import PositionRepository
from domain.services import metrics as m
from domain.services.checklist_rules import is_discarded, reit_answers, stock_answers
from domain.services.contribution_decision import (
    Candidate,
    ClassDecision,
    decide_class,
    spend_leftover,
)
from domain.services.performance import index_returns_on
from domain.value_objects.asset_class import CDI, AssetClass
from domain.value_objects.checklist import (
    QUESTIONS,
    AnswerSource,
    ChecklistAnswer,
    ChecklistKind,
    ChecklistWeights,
)
from domain.value_objects.money import Money
from domain.value_objects.strategy_type import TradeSide
from domain.value_objects.ticker import Ticker

_EQUITY = {AssetClass.BR_EQUITY, AssetClass.INTL_EQUITY}


def checklist_kind(
    ticker: Ticker, asset_class: AssetClass, reit: ReitFundamentals | None
) -> ChecklistKind | None:
    """Qual checklist se aplica ao ativo.

    FII quando há informe na CVM. Sem fundamentos baixados ainda, um ticker "11" de
    renda variável é tratado como FII (as units, como KLBN11, viram ação depois que
    os fundamentos forem atualizados). Renda fixa e cripto não têm checklist.
    """
    if reit is not None:
        return ChecklistKind.REIT
    if asset_class not in _EQUITY:
        return None
    if asset_class is AssetClass.BR_EQUITY and ticker.symbol.endswith("11"):
        return ChecklistKind.REIT
    return ChecklistKind.STOCK


def build_checklist(
    ticker: Ticker,
    kind: ChecklistKind,
    auto: dict[str, ChecklistAnswer],
    manual: dict[str, bool | None],
    weights: ChecklistWeights | None = None,
) -> ChecklistView:
    """Junta respostas automáticas e manuais (a manual prevalece) e calcula a nota."""
    rows: list[ChecklistQuestionRow] = []
    for question in QUESTIONS[kind]:
        automatic = auto.get(question.key)
        manual_answer = manual.get(question.key)
        if manual_answer is not None:
            answer, source = manual_answer, AnswerSource.MANUAL
        elif automatic is not None and automatic.value is not None:
            answer, source = automatic.value, AnswerSource.AUTO
        else:
            answer, source = None, None
        rows.append(
            ChecklistQuestionRow(
                key=question.key,
                title=question.title,
                text=question.text,
                auto_answer=automatic.value if automatic else None,
                evidence=automatic.evidence if automatic else "",
                manual_answer=manual_answer,
                answer=answer,
                source=source,
            )
        )
    yes = sum(1 for r in rows if r.answer is True)
    no = sum(1 for r in rows if r.answer is False)
    return ChecklistView(
        ticker=ticker.symbol,
        kind=kind,
        questions=rows,
        yes=yes,
        no=no,
        answered=yes + no,
        total=len(rows),
        score=(weights or ChecklistWeights()).score(yes, no, len(rows)),
    )


class SaveChecklist:
    """Grava respostas manuais (None remove e devolve a palavra à resposta automática)."""

    def __init__(self, checklist: ChecklistRepository) -> None:
        self._checklist = checklist

    def execute(self, request: SaveChecklistRequest) -> None:
        valid = {q.key for q in QUESTIONS[request.kind]}
        unknown = set(request.answers) - valid
        if unknown:
            raise DomainError(f"Perguntas inválidas: {', '.join(sorted(unknown))}.")
        self._checklist.save_answers(request.user_id, Ticker.parse(request.ticker), request.answers)


class GetChecklistWeights:
    """Pesos de Sim/Não salvos pelo usuário (padrão 1 e 0)."""

    def __init__(self, checklist: ChecklistRepository) -> None:
        self._checklist = checklist

    def execute(self) -> ChecklistWeightsDTO:
        weights = self._checklist.weights()
        return ChecklistWeightsDTO(yes=weights.yes, no=weights.no)


class SaveChecklistWeights:
    """Grava a postura do usuário; a validação dos limites é do domínio."""

    def __init__(self, checklist: ChecklistRepository) -> None:
        self._checklist = checklist

    def execute(self, request: SaveChecklistWeightsRequest) -> None:
        weights = ChecklistWeights(yes=request.weights.yes, no=request.weights.no)
        self._checklist.save_weights(request.user_id, weights)


class RefreshFundamentals:
    """Atualiza fundamentos (Yahoo + CVM) de todos os ativos da carteira, inclusive desejados."""

    def __init__(self, refresher: FundamentalsRefresher, positions: PositionRepository) -> None:
        self._refresher = refresher
        self._positions = positions

    def execute(self, portfolio_id: str) -> dict[str, str]:
        tickers = sorted({p.ticker for p in self._positions.list_positions(portfolio_id)})
        return self._refresher.refresh(tickers)


class SuggestAssetContribution:
    """Sugere o aporte por classe e, dentro de cada classe, por ativo.

    1. Distribui o valor entre classes pelo perfil alvo (SuggestContribution).
    2. Em cada classe, avalia os candidatos (posições e lista de desejos) pela nota
       quant (Sharpe, Sortino e Calmar no período) e pelo checklist, e converte o
       aporte da classe em lotes (domain.services.contribution_decision).
    """

    def __init__(
        self,
        class_suggestion: SuggestContribution,
        positions: PositionRepository,
        market_data: MarketDataRepository,
        fundamentals: FundamentalsRepository,
        checklist: ChecklistRepository,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._class_suggestion = class_suggestion
        self._positions = positions
        self._market_data = market_data
        self._fundamentals = fundamentals
        self._checklist = checklist
        self._today = today

    def execute(self, request: AssetContributionRequest) -> AssetContributionResult:
        plan = self._class_suggestion.execute(
            ContributionRequest(
                portfolio_id=request.portfolio_id,
                amount=request.amount,
                allow_sales=request.allow_sales,
            )
        )
        positions = self._positions.list_positions(request.portfolio_id)
        tickers = [p.ticker for p in positions]
        prices = self._market_data.latest_prices(tickers)
        stocks = self._fundamentals.stock_fundamentals(tickers)
        reits = self._fundamentals.reit_fundamentals(tickers)
        manual = self._checklist.answers(tickers)
        weights = self._checklist.weights()
        start = self._today() - timedelta(days=365 * request.lookback_years)

        budgets = {row.asset_class: row.contribution for row in plan.rows}
        by_class: dict[AssetClass, list[Position]] = {}
        for position in positions:
            by_class.setdefault(position.asset_class, []).append(position)

        decided: list[ClassDecision] = []
        views: dict[Ticker, ChecklistView] = {}
        closed: set[Ticker] = set()
        for asset_class in sorted(set(by_class) | set(budgets)):
            members = by_class.get(asset_class, [])
            if not members:
                continue
            candidates: list[Candidate] = []
            for position in members:
                price = prices.get(position.ticker)
                view = self._checklist_view(position, stocks, reits, manual, price, weights)
                if view is not None:
                    views[position.ticker] = view
                if position.is_closed:
                    closed.add(position.ticker)
                candidates.append(
                    Candidate(
                        ticker=position.ticker,
                        asset_class=asset_class,
                        current_value=position.quantity * price.amount if price else Decimal(0),
                        price=price.amount if price else None,
                        risk_adjusted=self._risk_adjusted(position.ticker, asset_class, start),
                        checklist_score=view.score if view is not None else None,
                        discarded_reason=is_discarded(
                            reits.get(position.ticker), float(price.amount) if price else None
                        ),
                    )
                )
            decided.append(
                decide_class(
                    asset_class,
                    candidates,
                    budgets.get(asset_class, Decimal(0)),
                    request.quant_weight,
                )
            )

        # Troco das classes (arredondamento em lotes) vai para onde ainda falta: classe
        # que já estava no alvo ou acima hoje nunca recebe. Nas demais, a falta é o maior
        # entre (alvo depois do aporte - atual - comprado) e (parte do aporte da classe
        # ainda não usada), para que o troco da própria classe sempre possa ser gasto.
        spent = {c.asset_class: sum((d.amount for d in c.decisions), Decimal(0)) for c in decided}
        gaps: dict[AssetClass, Decimal] = {}
        for row in plan.rows:
            used = spent.get(row.asset_class, Decimal(0))
            if row.current_pct >= row.target_pct and row.current_value > 0:
                gaps[row.asset_class] = Decimal(0)
            else:
                gaps[row.asset_class] = max(
                    row.target_value - row.current_value - used, row.contribution - used
                )
        decided, _ = spend_leftover(decided, gaps, sum((c.leftover for c in decided), Decimal(0)))

        classes = [
            ClassDecisionDTO(
                asset_class=cls.asset_class,
                budget=cls.budget,
                leftover=cls.budget - sum((d.amount for d in cls.decisions), Decimal(0)),
                uses_checklist=cls.uses_checklist,
                rows=[
                    AssetDecisionRow(
                        ticker=d.ticker.symbol,
                        asset_class=cls.asset_class,
                        in_watchlist=d.ticker in closed,
                        price=d.price,
                        current_value=d.current_value,
                        quant_score=d.quant_score,
                        checklist_score=d.checklist_score,
                        final_score=d.final_score,
                        ideal_weight_pct=d.ideal_weight * 100,
                        target_value=d.target_value,
                        quantity=d.quantity,
                        amount=d.amount,
                        decision=d.decision,
                        reason=d.reason,
                        checklist=views.get(d.ticker),
                    )
                    for d in sorted(
                        cls.decisions,
                        key=lambda d: (d.amount, d.final_score or -1.0),
                        reverse=True,
                    )
                ],
            )
            for cls in decided
        ]

        orders = [
            BuyOrder(
                ticker=row.ticker,
                asset_class=row.asset_class,
                quantity=row.quantity,
                price=row.price or Decimal(0),
            )
            for cls in classes
            for row in cls.rows
            if row.quantity > 0 and row.price
        ]
        leftover = request.amount - sum((o.amount for o in orders), Decimal(0))
        return AssetContributionResult(plan=plan, classes=classes, orders=orders, leftover=leftover)

    def _checklist_view(
        self,
        position: Position,
        stocks: dict[Ticker, StockFundamentals],
        reits: dict[Ticker, ReitFundamentals],
        manual: dict[Ticker, dict[str, bool | None]],
        price: Money | None,
        weights: ChecklistWeights,
    ) -> ChecklistView | None:
        reit = reits.get(position.ticker)
        kind = checklist_kind(position.ticker, position.asset_class, reit)
        if kind is None:
            return None
        if kind is ChecklistKind.REIT:
            auto = reit_answers(reit, float(price.amount) if price else None) if reit else {}
        else:
            stock = stocks.get(position.ticker)
            auto = stock_answers(stock, self._today()) if stock else {}
        return build_checklist(
            position.ticker, kind, auto, manual.get(position.ticker, {}), weights
        )

    def _risk_adjusted(
        self, ticker: Ticker, asset_class: AssetClass, start: date
    ) -> tuple[float | None, float | None, float | None]:
        """(Sharpe, Sortino, Calmar) do ativo sozinho no período, contra o CDI."""
        try:
            history = self._market_data.price_history([ticker], start)
            if len(history) < 3:
                return (None, None, None)
            rf_history = self._market_data.price_history([Ticker(CDI)], start - timedelta(days=15))
            returns = history.simple_returns()[:, 0]
            risk_free = index_returns_on(history.dates, rf_history, CDI)
        except MissingMarketDataError:
            return (None, None, None)
        periods = asset_class.periods_per_year
        return (
            m.sharpe_ratio(returns, risk_free, periods),
            m.sortino_ratio(returns, risk_free, periods),
            m.calmar_ratio(returns, periods),
        )


class GetChecklist:
    """Checklist de um único ativo (para a tela de edição)."""

    def __init__(
        self,
        fundamentals: FundamentalsRepository,
        checklist: ChecklistRepository,
        market_data: MarketDataRepository,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._fundamentals = fundamentals
        self._checklist = checklist
        self._market_data = market_data
        self._today = today

    def execute(self, ticker: str, asset_class: AssetClass) -> ChecklistView | None:
        symbol = Ticker.parse(ticker)
        reit = self._fundamentals.reit_fundamentals([symbol]).get(symbol)
        kind = checklist_kind(symbol, asset_class, reit)
        if kind is None:
            return None
        price = self._market_data.latest_prices([symbol]).get(symbol)
        if kind is ChecklistKind.REIT:
            auto = reit_answers(reit, float(price.amount) if price else None) if reit else {}
        else:
            stock = self._fundamentals.stock_fundamentals([symbol]).get(symbol)
            auto = stock_answers(stock, self._today()) if stock else {}
        manual = self._checklist.answers([symbol]).get(symbol, {})
        return build_checklist(symbol, kind, auto, manual, self._checklist.weights())


class ExecuteContribution:
    """Registra as compras sugeridas como operações (botão "Aportar").

    Cada ordem vira uma operação de compra ao último preço, pelo mesmo caminho de
    `RegisterTrade`: o preço médio é recalculado e operação e posição são gravadas
    juntas no banco. Uma ordem que falha não impede as demais.
    """

    def __init__(
        self,
        register_trade: RegisterTrade,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._register_trade = register_trade
        self._now = now

    def execute(self, request: ExecuteContributionRequest) -> ExecuteContributionResult:
        registered: list[str] = []
        errors: list[str] = []
        moment = self._now()
        for order in request.orders:
            try:
                self._register_trade.execute(
                    RegisterTradeRequest(
                        user_id=request.user_id,
                        portfolio_id=request.portfolio_id,
                        ticker=order.ticker,
                        side=TradeSide.BUY,
                        strategy=request.strategy,
                        traded_at=moment,
                        quantity=order.quantity,
                        price=order.price,
                        costs=Decimal(0),
                        asset_class=order.asset_class,
                    )
                )
                registered.append(order.ticker)
            except (DomainError, RuntimeError) as error:
                errors.append(f"{order.ticker}: {error}")
        return ExecuteContributionResult(registered=registered, errors=errors)
