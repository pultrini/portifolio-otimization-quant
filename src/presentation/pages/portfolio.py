"""Página: posições da carteira, importação e edição de preço médio."""

from decimal import Decimal

import streamlit as st

from application.dtos.portfolio import (
    ImportPositionsRequest,
    PositionRow,
    PositionsView,
    UpdatePositionRequest,
)
from domain.exceptions import DomainError
from domain.value_objects.asset_class import AssetClass
from presentation.components import cache
from presentation.components.formatting import (
    format_brl,
    format_number,
    format_pct,
    format_quantity,
)
from presentation.components.questionnaire import render_form, weights_editor
from presentation.components.session import PageContext

IMPORT_EXAMPLE = """# TICKER QUANTIDADE PRECO_MEDIO
EGIE3 2 29,30
# TICKER R$ VALOR_ATUAL [VALOR_INVESTIDO]  (renda fixa, cripto)
CDI R$ 652,46
BTC R$ 158,00 175,20
# Lista de desejos (ativos que quer ter): quantidade e preço médio zerados
VALE3 0 0"""

TABLE_MAX_HEIGHT = 390
QUESTIONNAIRE_HEIGHT = 440


def _positions_table(view: PositionsView) -> None:
    if not view.rows:
        st.info("Nenhuma posição. Importe sua carteira abaixo ou registre operações.")
        return

    # Totais no topo: patrimônio, custo e resultado.
    total_cost = view.total_cost
    total_value = view.total_market_value
    pnl = total_value - total_cost if total_value is not None else None
    pnl_pct = float(pnl / total_cost * 100) if pnl is not None and total_cost else None
    col1, col2, col3 = st.columns(3)
    col1.metric("Patrimônio", format_brl(total_value))
    col2.metric("Custo", format_brl(total_cost))
    col3.metric("Resultado", format_brl(pnl), format_pct(pnl_pct) if pnl_pct is not None else None)

    if view.missing_prices:
        st.warning(
            "Sem cotação para: "
            + ", ".join(view.missing_prices)
            + ". Atualize os dados de mercado para ver o patrimônio."
        )

    # Lista de dicts: o st.dataframe aceita sem precisar de pandas na apresentação.
    st.dataframe(
        [
            {
                "Ativo": row.ticker,
                "Classe": row.asset_class.label_pt,
                "Quantidade": format_quantity(row.quantity),
                "Preço médio": format_brl(row.average_price),
                # Preço médio informado pelo usuário (importação ou edição), não calculado.
                "Manual": "✓" if row.manual_override else "",
                "Último preço": format_brl(row.last_price),
                "Custo": format_brl(row.cost),
                "Valor de mercado": format_brl(row.market_value),
                "Resultado": format_brl(row.pnl),
                "Resultado %": format_pct(row.pnl_pct),
                "Peso": format_pct(row.weight_pct),
            }
            for row in view.rows
        ],
        hide_index=True,
        width="stretch",
        # Altura fixa: com muitos ativos a tabela rola por dentro e a página não cresce.
        height=min(TABLE_MAX_HEIGHT, 38 + 35 * len(view.rows)),
    )


def _import_form(ctx: PageContext) -> None:
    with st.expander("Importar posições", expanded=False):
        st.caption(
            "Uma posição por linha. Linhas com `R$` são lidas por valor: a quantidade é "
            "calculada com a última cotação (útil para renda fixa e cripto)."
        )
        st.caption(
            "Ações e ETFs americanos: use o ticker da bolsa americana (AAPL, BRK.B, VOO). "
            "Valores e preço médio sempre em **R$**; o app converte as cotações pela PTAX. "
            "Se só souber o preço em dólar, importe por valor: `AAPL R$ 1500 1200` "
            "(valor atual e valor investido em reais)."
        )
        with st.form("import_positions"):
            text = st.text_area("Posições", height=220, placeholder=IMPORT_EXAMPLE)
            replace = st.checkbox("Remover posições que não estão na lista")
            submitted = st.form_submit_button("Importar")
        if submitted and text.strip():
            response = ctx.container.import_positions.execute(
                ImportPositionsRequest(
                    user_id=ctx.user_id,
                    portfolio_id=ctx.portfolio_id,
                    text=text,
                    replace_existing=replace,
                )
            )
            if response.imported:
                cache.invalidate()
                st.success("Importados: " + ", ".join(response.imported))
            for error in response.errors:
                st.error(error)


def _edit_form(ctx: PageContext, view: PositionsView) -> None:
    # Carteira e lista de desejos: os dois podem ter o questionário respondido.
    classes_by_ticker = {row.ticker: row.asset_class for row in view.rows}
    classes_by_ticker.update(view.watchlist_classes)
    if not classes_by_ticker:
        return
    with st.expander("Editar ou remover posição"):
        ticker = st.selectbox(
            "Ativo",
            list(classes_by_ticker),
            key="edit_ticker",
            format_func=lambda t: t + ("  (desejado)" if t in view.watchlist_classes else ""),
        )
        if ticker is None:
            return
        row = next((r for r in view.rows if r.ticker == ticker), None)
        tab_position, tab_questions = st.tabs(["Posição", "📝 Questionário de importância"])
        with tab_position:
            if row is not None:
                _position_fields(ctx, row)
            else:
                st.caption("Ativo da lista de desejos: ainda sem cotas nem preço médio.")
            if st.button(f"Remover {ticker}", type="secondary"):
                ctx.container.delete_position.execute(ctx.portfolio_id, ticker)
                cache.invalidate()
                st.rerun()
        with tab_questions:
            _questionnaire(ctx, ticker, classes_by_ticker[ticker])


def _position_fields(ctx: PageContext, row: PositionRow) -> None:
    with st.form("edit_position"):
        avg = st.number_input(
            "Preço médio (R$)",
            min_value=0.0,
            value=float(row.average_price),
            format="%.8f",
        )
        classes = list(AssetClass)
        asset_class = st.selectbox(
            "Classe",
            classes,
            index=classes.index(row.asset_class),
            format_func=lambda c: c.label_pt,
        )
        save = st.form_submit_button("Salvar")
    if not save:
        return
    # O preço só é enviado se mudou, para não marcar edição manual à toa.
    new_avg = Decimal(str(avg))
    changed_avg = new_avg if abs(new_avg - row.average_price) > Decimal("1e-8") else None
    try:
        ctx.container.update_position.execute(
            UpdatePositionRequest(
                user_id=ctx.user_id,
                portfolio_id=ctx.portfolio_id,
                ticker=row.ticker,
                average_price=changed_avg,
                asset_class=asset_class,
            )
        )
    except DomainError as error:
        st.error(str(error))
    else:
        cache.invalidate()
        st.rerun()


def _questionnaire(ctx: PageContext, ticker: str, asset_class: AssetClass) -> None:
    """Perguntas do ativo numa caixa com rolagem, mais a postura (pesos de Sim e Não)."""
    view = ctx.container.get_checklist.execute(ticker, asset_class)
    if view is None:
        st.info(
            f"{asset_class.label_pt} não tem questionário: ele vale para ações e FIIs. "
            "Nessa classe a decisão de aporte usa só a nota quant."
        )
        return
    with st.popover("⚖️ Peso das respostas"):
        weights_editor(ctx, "portfolio")
    with st.container(height=QUESTIONNAIRE_HEIGHT):
        render_form(ctx, view, "portfolio")


def _reclassify_notice(ctx: PageContext) -> None:
    """Oferece mover FIIs e REITs da renda variável para as classes imobiliárias."""
    rows = ctx.container.reclassify_real_estate.preview(ctx.portfolio_id)
    if not rows:
        return
    moves = ", ".join(f"{r.ticker} → {r.proposed.label_pt}" for r in rows)
    with st.container(border=True):
        st.markdown(
            "**FIIs e REITs agora têm classe própria.** Estes ativos estão em renda "
            f"variável: {moves}."
        )
        st.caption(
            "Depois de mover, defina um alvo para a nova classe em Alocação Alvo: com "
            "alvo 0% ela não recebe aporte. Dá para voltar a classe em Editar posição."
        )
        if st.button("Mover para a classe imobiliária", type="primary"):
            ctx.container.reclassify_real_estate.execute(ctx.user_id, ctx.portfolio_id)
            cache.invalidate()
            st.rerun()


def _refresh_button(ctx: PageContext) -> None:
    """Roda o pipeline medalhão para os ativos da carteira e limpa os caches."""
    if not st.button("Atualizar dados de mercado", help="Baixa cotações, CDI e câmbio."):
        return
    with st.spinner("Baixando cotações e processando Bronze → Silver → Gold..."):
        report = ctx.container.refresh_market_data.execute(ctx.portfolio_id)
    # Leituras da Gold em cache ficam obsoletas depois do pipeline.
    cache.invalidate()
    gold_rows = format_number(report.rows_by_layer.get("gold", 0), decimals=0)
    st.success(f"Dados atualizados: {gold_rows} linhas na camada Gold.")
    for ticker, reason in report.failed_tickers.items():
        st.warning(f"{ticker}: {reason}")


def _watchlist(ctx: PageContext, view: PositionsView) -> None:
    """Ativos desejados (0 cotas): concorrem nas sugestões de aporte da Alocação Alvo."""
    st.subheader("Lista de desejos")
    st.caption("Ativos que você quer ter. Entram na decisão de aporte junto com a carteira.")
    if view.watchlist:
        cols = st.columns(min(len(view.watchlist), 6))
        for index, ticker in enumerate(view.watchlist):
            column = cols[index % len(cols)]
            column.markdown(f"**{ticker}**")
            if column.button("Remover", key=f"unwish_{ticker}"):
                ctx.container.delete_position.execute(ctx.portfolio_id, ticker)
                cache.invalidate()
                st.rerun()
    with st.form("add_wish", clear_on_submit=True):
        col1, col2 = st.columns([3, 1])
        ticker = col1.text_input("Adicionar ativo desejado", placeholder="VALE3")
        col2.write("")
        added = col2.form_submit_button("Adicionar", width="stretch")
    if added and ticker.strip():
        # Mesmo caminho da importação: "TICKER 0 0" cria a posição desejada.
        response = ctx.container.import_positions.execute(
            ImportPositionsRequest(
                user_id=ctx.user_id, portfolio_id=ctx.portfolio_id, text=f"{ticker.strip()} 0 0"
            )
        )
        for error in response.errors:
            st.error(error)
        if response.imported:
            cache.invalidate()
            st.rerun()


def render(ctx: PageContext) -> None:
    st.header("Carteira")
    st.caption(f"Carteira: {ctx.portfolio_name}")
    _refresh_button(ctx)
    _reclassify_notice(ctx)
    view = ctx.container.list_positions.execute(ctx.portfolio_id)
    _positions_table(view)
    _watchlist(ctx, view)
    _import_form(ctx)
    _edit_form(ctx, view)
