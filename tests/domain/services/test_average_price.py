"""Testes de preço médio com valores calculados à mão."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from domain.entities.position import Position
from domain.entities.trade import Trade
from domain.exceptions import DomainError, InsufficientQuantityError
from domain.services.average_price import (
    apply_buy,
    apply_sell,
    apply_split,
    apply_trade,
    override_average_price,
)
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.money import Money
from domain.value_objects.strategy_type import StrategyType, TradeSide
from domain.value_objects.ticker import Ticker

D = Decimal
PETR4 = Ticker("PETR4")
WHEN = datetime(2026, 11, 19, 15, 0, tzinfo=UTC)


def _trade(side: TradeSide, qty: str, price: str, costs: str = "0") -> Trade:
    return Trade(
        ticker=PETR4,
        side=side,
        strategy=StrategyType.BUY_AND_HOLD,
        traded_at=WHEN,
        quantity=D(qty),
        price=Money.brl(price),
        costs=Money.brl(costs),
    )


def _position(qty: str, avg: str, manual: bool = False) -> Position:
    return Position(PETR4, AssetClass.BR_EQUITY, D(qty), Money.brl(avg), manual)


def test_primeira_compra_inclui_custos() -> None:
    # (10 x 30 + 5) / 10 = 30.50
    position = apply_buy(None, _trade(TradeSide.BUY, "10", "30", "5"), AssetClass.BR_EQUITY)
    assert position.quantity == D("10")
    assert position.average_price.amount == D("30.5")


def test_compra_recalcula_media_ponderada() -> None:
    # (100 x 20 + 50 x 26 + 2) / 150 = 3302 / 150 = 22.0133...
    position = apply_buy(
        _position("100", "20"), _trade(TradeSide.BUY, "50", "26", "2"), AssetClass.BR_EQUITY
    )
    assert position.quantity == D("150")
    assert position.average_price.amount == D("3302") / D("150")


def test_compra_apos_edicao_manual_parte_do_valor_editado_e_limpa_a_flag() -> None:
    # (10 x 25 + 10 x 35) / 20 = 30
    position = apply_buy(
        _position("10", "25", manual=True), _trade(TradeSide.BUY, "10", "35"), AssetClass.BR_EQUITY
    )
    assert position.average_price.amount == D("30")
    assert position.manual_override is False


def test_venda_nao_altera_preco_medio() -> None:
    position = apply_sell(_position("100", "20"), _trade(TradeSide.SELL, "40", "50", "3"))
    assert position.quantity == D("60")
    assert position.average_price.amount == D("20")


def test_venda_total_zera_posicao() -> None:
    position = apply_sell(_position("6", "41.51"), _trade(TradeSide.SELL, "6", "45"))
    assert position.is_closed


def test_venda_maior_que_posicao_falha() -> None:
    with pytest.raises(InsufficientQuantityError):
        apply_sell(_position("5", "20"), _trade(TradeSide.SELL, "6", "20"))


def test_venda_sem_posicao_falha() -> None:
    with pytest.raises(InsufficientQuantityError):
        apply_sell(None, _trade(TradeSide.SELL, "1", "20"))


def test_desdobramento_mantem_custo_total() -> None:
    # 1:2 -> 100 ações a 20 viram 200 a 10; custo total segue 2000.
    original = _position("100", "20")
    position = apply_split(original, D("2"))
    assert position.quantity == D("200")
    assert position.average_price.amount == D("10")
    assert position.total_cost == original.total_cost


def test_grupamento_mantem_custo_total() -> None:
    # 10:1 -> 1000 a 0.50 viram 100 a 5.00.
    position = apply_split(_position("1000", "0.5"), D("0.1"))
    assert position.quantity == D("100")
    assert position.average_price.amount == D("5")


def test_fator_invalido() -> None:
    with pytest.raises(DomainError):
        apply_split(_position("10", "1"), D("0"))


def test_edicao_manual_marca_flag() -> None:
    position = override_average_price(_position("2", "29.30"), Money.brl("28"))
    assert position.average_price.amount == D("28")
    assert position.manual_override


def test_apply_trade_despacha_pelo_lado() -> None:
    bought = apply_trade(None, _trade(TradeSide.BUY, "2", "10"), AssetClass.BR_EQUITY)
    sold = apply_trade(bought, _trade(TradeSide.SELL, "1", "12"), AssetClass.BR_EQUITY)
    assert sold.quantity == D("1")
    assert sold.average_price.amount == D("10")


def test_trade_exige_utc() -> None:
    with pytest.raises(DomainError):
        Trade(
            ticker=PETR4,
            side=TradeSide.BUY,
            strategy=StrategyType.DAY_TRADE,
            traded_at=datetime(2026, 11, 19, 15, 0),
            quantity=D("1"),
            price=Money.brl("1"),
            costs=Money.brl("0"),
        )


def test_fluxo_de_caixa_da_operacao() -> None:
    assert _trade(TradeSide.BUY, "10", "30", "5").cash_flow.amount == D("-305")
    assert _trade(TradeSide.SELL, "10", "30", "5").cash_flow.amount == D("295")
