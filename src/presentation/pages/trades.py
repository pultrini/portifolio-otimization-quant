"""Página: registro e histórico de operações."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import streamlit as st

from application.dtos.portfolio import RegisterTradeRequest
from domain.exceptions import DomainError
from domain.value_objects.strategy_type import StrategyType, TradeSide
from presentation.components import cache
from presentation.components.formatting import format_brl, format_quantity
from presentation.components.session import PageContext

# Datas são digitadas e exibidas no horário de Brasília; o use case grava em UTC.
SAO_PAULO = ZoneInfo("America/Sao_Paulo")

_SIDE_LABELS = {TradeSide.BUY: "Compra", TradeSide.SELL: "Venda"}


def _register_form(ctx: PageContext) -> None:
    with st.form("register_trade", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        ticker = col1.text_input("Ativo", placeholder="PETR4")
        side = col2.selectbox("Tipo", list(TradeSide), format_func=_SIDE_LABELS.__getitem__)
        strategy = col3.selectbox(
            "Estratégia", list(StrategyType), format_func=lambda s: s.label_pt
        )
        col4, col5 = st.columns(2)
        day = col4.date_input("Data", format="DD/MM/YYYY")
        time = col5.time_input("Hora", step=60)
        col6, col7, col8 = st.columns(3)
        quantity = col6.number_input("Quantidade", min_value=0.0, format="%.8f")
        price = col7.number_input("Preço (R$)", min_value=0.0, format="%.2f")
        costs = col8.number_input("Custos (R$)", min_value=0.0, format="%.2f")
        submitted = st.form_submit_button("Registrar operação")

    if not submitted:
        return
    # O selectbox devolve None só se a lista de opções estiver vazia; aqui nunca está.
    if side is None or strategy is None:
        return
    if not ticker.strip() or quantity <= 0:
        st.error("Informe o ativo e uma quantidade maior que zero.")
        return
    try:
        row = ctx.container.register_trade.execute(
            RegisterTradeRequest(
                user_id=ctx.user_id,
                portfolio_id=ctx.portfolio_id,
                ticker=ticker,
                side=side,
                strategy=strategy,
                traded_at=datetime.combine(day, time, tzinfo=SAO_PAULO),
                # float -> str -> Decimal preserva o número digitado.
                quantity=Decimal(str(quantity)),
                price=Decimal(str(price)),
                costs=Decimal(str(costs)),
            )
        )
    except DomainError as error:
        st.error(str(error))
        return
    cache.invalidate()
    st.success(f"{_SIDE_LABELS[row.side]} de {row.ticker} registrada.")


def render(ctx: PageContext) -> None:
    st.header("Operações")
    st.caption(f"Carteira: {ctx.portfolio_name}")
    _register_form(ctx)

    rows = ctx.container.list_trades.execute(ctx.portfolio_id)
    if not rows:
        st.info("Nenhuma operação registrada.")
        return
    st.dataframe(
        [
            {
                "Data": row.traded_at.astimezone(SAO_PAULO).strftime("%d/%m/%Y %H:%M"),
                "Ativo": row.ticker,
                "Tipo": _SIDE_LABELS[row.side],
                "Estratégia": row.strategy.label_pt,
                "Quantidade": format_quantity(row.quantity),
                "Preço": format_brl(row.price),
                "Custos": format_brl(row.costs),
                "Fluxo de caixa": format_brl(row.cash_flow),
            }
            for row in rows
        ],
        hide_index=True,
        use_container_width=True,
    )
