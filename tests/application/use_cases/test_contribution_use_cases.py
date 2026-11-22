"""Testes da decisão de aporte por ativo, do checklist e do botão Aportar."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from application.dtos.contribution import (
    AssetContributionRequest,
    ExecuteContributionRequest,
    SaveChecklistRequest,
)
from application.dtos.portfolio import ImportPositionsRequest
from application.use_cases.contribution import (
    ExecuteContribution,
    GetChecklist,
    SaveChecklist,
    SuggestAssetContribution,
    checklist_kind,
)
from application.use_cases.import_positions import ImportPositions
from application.use_cases.optimization import SuggestContribution
from application.use_cases.trades import RegisterTrade
from domain.entities.fundamentals import AnnualFigures, ReitFundamentals, StockFundamentals
from domain.exceptions import DomainError
from domain.services.contribution_decision import Decision
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.checklist import AnswerSource, ChecklistKind
from domain.value_objects.ticker import Ticker
from tests.fakes.in_memory_portfolio_repository import InMemoryPortfolioRepository
from tests.fakes.in_memory_repositories import (
    FakeFundamentalsRepository,
    FakeMarketDataRepository,
    InMemoryChecklistRepository,
    InMemoryPositionRepository,
    InMemoryTradeRepository,
)

N = 200
TODAY = date(2026, 11, 20)
DATES = [TODAY - timedelta(days=N - 1 - i) for i in range(N)]
rng = np.random.default_rng(3)


def _walk(start: float, drift: float, vol: float) -> list[float]:
    steps = rng.normal(drift, vol, N - 1)
    return [round(v, 2) for v in start * np.concatenate(([1.0], np.cumprod(1 + steps)))]


MARKET = FakeMarketDataRepository(
    dates=DATES,
    history={
        "AAAA3": _walk(20.0, 0.002, 0.01),
        "BBBB3": _walk(10.0, 0.0005, 0.02),
        "FIIX11": _walk(160.0, 0.0, 0.005),
        "CDI": [1.0005**i for i in range(N)],
    },
)
GOOD_STOCK = StockFundamentals(
    "AAAA3",
    annual=(
        AnnualFigures(
            2022, revenue=100, net_income=15, ebitda=30, equity=100, total_debt=20, cash=10
        ),
        AnnualFigures(
            2025, revenue=140, net_income=20, ebitda=40, equity=110, total_debt=20, cash=15
        ),
    ),
    dividend_years=frozenset(range(2015, 2026)),
    constitution_date=date(1950, 1, 1),
    control="PRIVADO",
    market_cap_brl=50e9,
)
EXPENSIVE_REIT = ReitFundamentals("FIIX11", book_value_per_share=100.0, months_observed=48)


def _setup() -> tuple[
    InMemoryPortfolioRepository,
    InMemoryPositionRepository,
    InMemoryTradeRepository,
    InMemoryChecklistRepository,
    SuggestAssetContribution,
    str,
]:
    portfolios = InMemoryPortfolioRepository()
    pid = portfolios.create_portfolio("u", "Principal").id
    positions = InMemoryPositionRepository()
    trades = InMemoryTradeRepository(positions)
    ImportPositions(positions, MARKET).execute(
        ImportPositionsRequest(
            user_id="u",
            portfolio_id=pid,
            # AAAA3 na carteira; BBBB3 só desejada (0 cotas); FIIX11 caro; CDI na RF.
            text="AAAA3 5 18\nBBBB3 0 0\nFIIX11 1 150\nCDI R$ 500",
        )
    )
    portfolios.save_allocation_targets("u", pid, {"BR_EQUITY": 70.0, "BR_FIXED_INCOME": 30.0})
    checklist = InMemoryChecklistRepository()
    fundamentals = FakeFundamentalsRepository(
        stocks={"AAAA3": GOOD_STOCK}, reits={"FIIX11": EXPENSIVE_REIT}
    )
    use_case = SuggestAssetContribution(
        SuggestContribution(portfolios, positions, MARKET),
        positions,
        MARKET,
        fundamentals,
        checklist,
        today=lambda: TODAY,
    )
    return portfolios, positions, trades, checklist, use_case, pid


def test_sugestao_por_ativo() -> None:
    _, _, _, _, use_case, pid = _setup()
    result = use_case.execute(AssetContributionRequest(portfolio_id=pid, amount=Decimal("1000")))

    equity = next(c for c in result.classes if c.asset_class is AssetClass.BR_EQUITY)
    rows = {r.ticker: r for r in equity.rows}
    assert equity.uses_checklist
    # FII com P/VP > 1,5 é eliminado em qualquer hipótese.
    assert rows["FIIX11"].decision is Decision.DISCARDED
    assert "P/VP" in rows["FIIX11"].reason
    # BBBB3 está só na lista de desejos e concorre normalmente.
    assert rows["BBBB3"].in_watchlist
    assert rows["AAAA3"].checklist is not None
    assert rows["AAAA3"].checklist.yes == 7  # todas as regras automáticas deram Sim
    # Cotas inteiras e soma das ordens + troco = aporte.
    assert all(
        o.quantity == o.quantity.to_integral_value() for o in result.orders if o.ticker != "CDI"
    )
    assert sum(o.amount for o in result.orders) + result.leftover == Decimal("1000")
    assert {o.ticker for o in result.orders} <= {"AAAA3", "BBBB3", "CDI"}


def test_resposta_manual_prevalece() -> None:
    _, _, _, checklist, use_case, pid = _setup()
    SaveChecklist(checklist).execute(
        SaveChecklistRequest(
            user_id="u",
            ticker="AAAA3",
            kind=ChecklistKind.STOCK,
            answers={"roe": False, "governance": True},
        )
    )
    result = use_case.execute(AssetContributionRequest(portfolio_id=pid, amount=Decimal("0")))
    row = next(r for c in result.classes for r in c.rows if r.ticker == "AAAA3")
    assert row.checklist is not None
    by_key = {q.key: q for q in row.checklist.questions}
    assert by_key["roe"].answer is False
    assert by_key["roe"].auto_answer is True
    assert by_key["roe"].source is AnswerSource.MANUAL
    assert by_key["governance"].answer is True
    # 7 automáticas - ROE + governança = 7.
    assert row.checklist.yes == 7

    # Limpar a resposta manual devolve a automática.
    SaveChecklist(checklist).execute(
        SaveChecklistRequest(
            user_id="u", ticker="AAAA3", kind=ChecklistKind.STOCK, answers={"roe": None}
        )
    )
    view = GetChecklist(
        FakeFundamentalsRepository(stocks={"AAAA3": GOOD_STOCK}), checklist, MARKET, lambda: TODAY
    ).execute("AAAA3", AssetClass.BR_EQUITY)
    assert view is not None
    assert {q.key: q.answer for q in view.questions}["roe"] is True


def test_pergunta_invalida() -> None:
    with pytest.raises(DomainError):
        SaveChecklist(InMemoryChecklistRepository()).execute(
            SaveChecklistRequest(
                user_id="u", ticker="AAAA3", kind=ChecklistKind.REIT, answers={"roe": True}
            )
        )


def test_aportar_registra_operacoes() -> None:
    _, positions, trades, _, use_case, pid = _setup()
    result = use_case.execute(AssetContributionRequest(portfolio_id=pid, amount=Decimal("1000")))
    executor = ExecuteContribution(
        RegisterTrade(positions, trades), now=lambda: datetime(2026, 11, 21, 15, tzinfo=UTC)
    )
    response = executor.execute(
        ExecuteContributionRequest(user_id="u", portfolio_id=pid, orders=result.orders)
    )
    assert response.errors == []
    assert sorted(response.registered) == sorted(o.ticker for o in result.orders)
    for order in result.orders:
        position = positions.get_position(pid, Ticker(order.ticker))
        assert position is not None
        if order.ticker == "BBBB3":
            # Saiu da lista de desejos: quantidade comprada ao preço da ordem.
            assert position.quantity == order.quantity
            assert position.average_price.amount == order.price
    assert len(trades.list_trades(pid)) == len(result.orders)


def test_tipo_de_checklist() -> None:
    assert checklist_kind(Ticker("PETR4"), AssetClass.BR_EQUITY, None) is ChecklistKind.STOCK
    assert checklist_kind(Ticker("MXRF11"), AssetClass.BR_EQUITY, None) is ChecklistKind.REIT
    assert checklist_kind(Ticker("CDI"), AssetClass.BR_FIXED_INCOME, None) is None
    assert (
        checklist_kind(Ticker("KLBN11"), AssetClass.BR_EQUITY, ReitFundamentals("KLBN11"))
        is ChecklistKind.REIT
    )


def test_classe_acima_do_alvo_nao_recebe_e_aporte_vai_ate_o_maximo() -> None:
    # Exemplo do usuário: perfil com 40% em ações brasileiras, mas a carteira já tem
    # bem mais que isso. O aporte deve ir inteiro para onde falta percentual.
    portfolios = InMemoryPortfolioRepository()
    pid = portfolios.create_portfolio("u", "Principal").id
    positions = InMemoryPositionRepository()
    ImportPositions(positions, MARKET).execute(
        ImportPositionsRequest(user_id="u", portfolio_id=pid, text="AAAA3 20 18\nCDI R$ 100")
    )
    portfolios.save_allocation_targets("u", pid, {"BR_EQUITY": 40.0, "BR_FIXED_INCOME": 60.0})
    use_case = SuggestAssetContribution(
        SuggestContribution(portfolios, positions, MARKET),
        positions,
        MARKET,
        FakeFundamentalsRepository(stocks={"AAAA3": GOOD_STOCK}),
        InMemoryChecklistRepository(),
        today=lambda: TODAY,
    )
    result = use_case.execute(AssetContributionRequest(portfolio_id=pid, amount=Decimal("500")))

    equity = next(r for r in result.plan.rows if r.asset_class is AssetClass.BR_EQUITY)
    assert equity.current_pct > 40  # já acima do alvo
    assert equity.contribution == 0
    assert all(o.asset_class is not AssetClass.BR_EQUITY for o in result.orders)
    # Tudo em renda fixa (CDI é fracionado): o aporte é usado até o último centavo.
    assert [o.ticker for o in result.orders] == ["CDI"]
    assert result.leftover < Decimal("0.01")
