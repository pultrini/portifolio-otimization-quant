"""Testes de importação, valorização e registro de operações."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from application.dtos.portfolio import (
    ImportPositionsRequest,
    RegisterTradeRequest,
    UpdatePositionRequest,
)
from application.use_cases.import_positions import (
    ImportPositions,
    parse_decimal,
    parse_positions_text,
)
from application.use_cases.positions import DeletePosition, ListPositions, UpdatePosition
from application.use_cases.trades import ListTrades, RegisterTrade
from domain.entities.fundamentals import ReitFundamentals
from domain.exceptions import DomainError, InsufficientQuantityError
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.strategy_type import StrategyType, TradeSide
from domain.value_objects.ticker import Ticker
from tests.fakes.in_memory_repositories import (
    FakeMarketDataRepository,
    InMemoryPositionRepository,
    InMemoryTradeRepository,
)

D = Decimal
SAMPLE = """
# exemplo de extrato
ABCD3 10 20,00
WXYZ11 4 100
CDI R$ 1.000,00
BTC R$ 150,00 200,00
"""


def _market() -> FakeMarketDataRepository:
    return FakeMarketDataRepository(
        history={"ABCD3": [22.0], "WXYZ11": [90.0], "CDI": [2.5], "BTC": [300000.0]}
    )


class TestParser:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("29,30", "29.30"), ("1.234,56", "1234.56"), ("29.30", "29.30"), ("35", "35")],
    )
    def test_numeros(self, raw: str, expected: str) -> None:
        assert parse_decimal(raw) == D(expected)

    def test_linhas_validas_e_erros(self) -> None:
        parsed, errors = parse_positions_text(SAMPLE + "ABCD3 1 1\nfoo\nZZZZ3 0 0\n")
        assert [p.ticker.symbol for p in parsed] == ["ABCD3", "WXYZ11", "CDI", "BTC", "ZZZZ3"]
        assert parsed[3].current_value == D("150.00")
        assert parsed[3].invested_value == D("200.00")
        # Ticker repetido e linha mal formada; quantidade zero é lista de desejos.
        assert len(errors) == 2
        assert parsed[-1].ticker.symbol == "ZZZZ3"
        assert parsed[-1].quantity == 0

    def test_numero_negativo_invalido(self) -> None:
        with pytest.raises(DomainError):
            parse_decimal("-1")


class TestImport:
    def test_importa_por_quantidade_e_por_valor(self) -> None:
        positions = InMemoryPositionRepository()
        response = ImportPositions(positions, _market()).execute(
            ImportPositionsRequest(user_id="u", portfolio_id="p", text=SAMPLE)
        )
        assert response.errors == []
        assert response.imported == ["ABCD3", "WXYZ11", "CDI", "BTC"]

        cdi = positions.get_position("p", Ticker("CDI"))
        assert cdi is not None
        # 1000 / 2.5 = 400 cotas; sem valor investido, preço médio = último preço.
        assert cdi.quantity == D("400")
        assert cdi.average_price.amount == D("2.5")
        assert cdi.asset_class is AssetClass.BR_FIXED_INCOME

        btc = positions.get_position("p", Ticker("BTC"))
        assert btc is not None
        # 150 / 300000 = 0.0005; custo 200 -> preço médio 400000.
        assert btc.quantity == D("0.0005")
        assert btc.total_cost.amount == D("200")
        assert btc.manual_override

    def test_linha_por_valor_sem_cotacao_vira_erro(self) -> None:
        positions = InMemoryPositionRepository()
        response = ImportPositions(positions, FakeMarketDataRepository()).execute(
            ImportPositionsRequest(user_id="u", portfolio_id="p", text="CDI R$ 10\nABCD3 1 5")
        )
        assert response.imported == ["ABCD3"]
        assert "sem cotação" in response.errors[0]

    def test_substituir_remove_o_que_nao_veio(self) -> None:
        positions = InMemoryPositionRepository()
        importer = ImportPositions(positions, _market())
        importer.execute(ImportPositionsRequest(user_id="u", portfolio_id="p", text=SAMPLE))
        importer.execute(
            ImportPositionsRequest(
                user_id="u", portfolio_id="p", text="ABCD3 1 1", replace_existing=True
            )
        )
        assert [p.ticker.symbol for p in positions.list_positions("p")] == ["ABCD3"]


class TestListPositions:
    def test_valoriza_e_calcula_pesos(self) -> None:
        positions = InMemoryPositionRepository()
        ImportPositions(positions, _market()).execute(
            ImportPositionsRequest(user_id="u", portfolio_id="p", text="ABCD3 10 20\nWXYZ11 4 100")
        )
        view = ListPositions(positions, _market()).execute("p")
        abcd = next(r for r in view.rows if r.ticker == "ABCD3")
        # Valor 10 x 22 = 220; custo 200; resultado 20 (10%).
        assert abcd.market_value == D("220.0")
        assert abcd.pnl == D("20.0")
        assert abcd.pnl_pct == pytest.approx(10.0)
        # Total 220 + 360 = 580; peso ABCD3 = 220 / 580.
        assert view.total_market_value == D("580.0")
        assert abcd.weight_pct == pytest.approx(220 / 580 * 100)
        assert view.missing_prices == []

    def test_sem_preco_total_de_mercado_fica_none(self) -> None:
        positions = InMemoryPositionRepository()
        ImportPositions(positions, _market()).execute(
            ImportPositionsRequest(user_id="u", portfolio_id="p", text="ABCD3 1 20\nNOPE3 1 1")
        )
        view = ListPositions(positions, _market()).execute("p")
        assert view.total_market_value is None
        assert view.missing_prices == ["NOPE3"]


class TestTrades:
    def _request(
        self, side: TradeSide, qty: str, price: str, costs: str = "0"
    ) -> RegisterTradeRequest:
        return RegisterTradeRequest(
            user_id="u",
            portfolio_id="p",
            ticker="abcd3",
            side=side,
            strategy=StrategyType.SWING_TRADE,
            # 10h em São Paulo (UTC-3) = 13h UTC.
            traded_at=datetime(2026, 11, 19, 10, 0, tzinfo=timezone(timedelta(hours=-3))),
            quantity=D(qty),
            price=D(price),
            costs=D(costs),
        )

    def test_compra_venda_e_historico(self) -> None:
        positions = InMemoryPositionRepository()
        trades = InMemoryTradeRepository(positions)
        register = RegisterTrade(positions, trades)

        register.execute(self._request(TradeSide.BUY, "10", "30", "5"))
        row = register.execute(self._request(TradeSide.SELL, "4", "35", "1"))

        position = positions.get_position("p", Ticker("ABCD3"))
        assert position is not None
        assert position.quantity == D("6")
        assert position.average_price.amount == D("30.5")
        assert position.asset_class is AssetClass.BR_EQUITY
        assert row.traded_at == datetime(2026, 11, 19, 13, 0, tzinfo=UTC)
        assert row.cash_flow == D("139")

        history = ListTrades(trades).execute("p")
        assert [r.side for r in history] == [TradeSide.SELL, TradeSide.BUY]

    def test_venda_a_descoberto_bloqueada(self) -> None:
        positions = InMemoryPositionRepository()
        register = RegisterTrade(positions, InMemoryTradeRepository(positions))
        with pytest.raises(InsufficientQuantityError):
            register.execute(self._request(TradeSide.SELL, "1", "10"))


class TestUpdateAndDelete:
    def test_edicao_manual_e_troca_de_classe(self) -> None:
        positions = InMemoryPositionRepository()
        ImportPositions(positions, _market()).execute(
            ImportPositionsRequest(user_id="u", portfolio_id="p", text="WXYZ11 4 100")
        )
        UpdatePosition(positions).execute(
            UpdatePositionRequest(
                user_id="u",
                portfolio_id="p",
                ticker="WXYZ11",
                average_price=D("95"),
                asset_class=AssetClass.BR_FIXED_INCOME,
            )
        )
        position = positions.get_position("p", Ticker("WXYZ11"))
        assert position is not None
        assert position.average_price.amount == D("95")
        assert position.asset_class is AssetClass.BR_FIXED_INCOME

        DeletePosition(positions).execute("p", "wxyz11")
        assert positions.list_positions("p") == []

    def test_editar_posicao_inexistente(self) -> None:
        with pytest.raises(DomainError):
            UpdatePosition(InMemoryPositionRepository()).execute(
                UpdatePositionRequest(user_id="u", portfolio_id="p", ticker="NOPE3")
            )


def test_lista_de_desejos() -> None:
    positions = InMemoryPositionRepository()
    response = ImportPositions(positions, _market()).execute(
        ImportPositionsRequest(user_id="u", portfolio_id="p", text="ABCD3 1 20\nVALE3 0 0")
    )
    assert response.errors == []
    view = ListPositions(positions, _market()).execute("p")
    assert [r.ticker for r in view.rows] == ["ABCD3"]
    assert view.watchlist == ["VALE3"]
    wish = positions.get_position("p", Ticker("VALE3"))
    assert wish is not None
    assert wish.average_price.amount == 0
    assert not wish.manual_override


def test_reclassifica_fiis_e_reits_que_estavam_em_renda_variavel() -> None:
    from application.use_cases.positions import ReclassifyRealEstate
    from domain.entities.position import Position
    from domain.value_objects.money import Money
    from tests.fakes.in_memory_repositories import FakeFundamentalsRepository

    positions = InMemoryPositionRepository()
    old = [
        ("MXRF11", AssetClass.BR_EQUITY),  # FII da carteira antiga
        ("TAEE11", AssetClass.BR_EQUITY),  # unit: continua em renda variável
        ("O", AssetClass.INTL_EQUITY),  # REIT americano
        ("VISC11", AssetClass.BR_FIXED_INCOME),  # classe escolhida à mão: não mexe
    ]
    positions.save_positions(
        "u",
        "p",
        [Position(Ticker(t), c, Decimal("2"), Money.brl("10"), True) for t, c in old],
    )
    fundamentals = FakeFundamentalsRepository(reits={"MXRF11": ReitFundamentals("MXRF11")})
    use_case = ReclassifyRealEstate(positions, fundamentals)

    preview = {r.ticker: r.proposed for r in use_case.preview("p")}
    assert preview == {
        "MXRF11": AssetClass.BR_REAL_ESTATE,
        "O": AssetClass.INTL_REAL_ESTATE,
    }
    use_case.execute("u", "p")
    classes = {p.ticker.symbol: p.asset_class for p in positions.list_positions("p")}
    assert classes["MXRF11"] is AssetClass.BR_REAL_ESTATE
    assert classes["O"] is AssetClass.INTL_REAL_ESTATE
    assert classes["TAEE11"] is AssetClass.BR_EQUITY
    assert classes["VISC11"] is AssetClass.BR_FIXED_INCOME
    # Quantidade e preço médio intactos; segunda execução não muda nada.
    mxrf = positions.get_position("p", Ticker("MXRF11"))
    assert mxrf is not None and mxrf.quantity == Decimal("2") and mxrf.manual_override
    assert use_case.preview("p") == []


def test_importacao_usa_a_lista_de_fiis_da_cvm() -> None:
    from tests.fakes.in_memory_repositories import FakeFundamentalsRepository

    positions = InMemoryPositionRepository()
    fundamentals = FakeFundamentalsRepository(reits={"ABCD11": ReitFundamentals("ABCD11")})
    ImportPositions(positions, _market(), fundamentals=fundamentals).execute(
        ImportPositionsRequest(user_id="u", portfolio_id="p", text="ABCD11 0 0\nWXYZ11 0 0")
    )
    classes = {p.ticker.symbol: p.asset_class for p in positions.list_positions("p")}
    # Com a lista da CVM, só ABCD11 é FII; WXYZ11 (fora dela) fica em renda variável.
    assert classes == {"ABCD11": AssetClass.BR_REAL_ESTATE, "WXYZ11": AssetClass.BR_EQUITY}
