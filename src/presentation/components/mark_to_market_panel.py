"""Marcação a mercado na aba de renda fixa: vender o título hoje ou levar até o fim?"""

import datetime as dt

import streamlit as st

from application.dtos.mark_to_market import BondMarkRow, SaveBondTermsRequest
from domain.exceptions import DomainError
from domain.services.mark_to_market import BondKind
from presentation.components import cache
from presentation.components.formatting import format_brl, format_number, format_ratio_as_pct
from presentation.components.glossary import help_text
from presentation.components.session import PageContext
from presentation.pages import guide


def _rate(value: float | None, row: BondMarkRow) -> str:
    if value is None:
        return "—"
    return f"{format_ratio_as_pct(value)} {row.kind.rate_suffix}"


def _terms_form(ctx: PageContext, row: BondMarkRow) -> None:
    """Taxa da nota de compra, ou estimativa pelo preço médio e pela data da compra."""
    with st.form(f"bond_terms_{row.ticker}", border=False):
        col1, col2 = st.columns(2)
        rate = col1.number_input(
            f"Taxa contratada (% {row.kind.rate_suffix})",
            min_value=0.0,
            max_value=50.0,
            value=round(row.contracted_rate * 100, 2) if row.contracted_rate else None,
            step=0.01,
            format="%.2f",
            help="A taxa que aparece na nota de compra ou no extrato do Tesouro/corretora.",
        )
        purchase = col2.date_input(
            "Ou estime pela data da compra",
            value=None,
            max_value=dt.date.today(),
            format="DD/MM/YYYY",
            help="Sem a taxa, o app estima com o preço médio da carteira e a cotação de "
            "compra do Tesouro nesse dia. Com várias compras, é uma aproximação.",
        )
        saved = st.form_submit_button("Salvar taxa")
    if not saved:
        return
    if rate is None and purchase is None:
        st.error("Informe a taxa ou a data da compra.")
        return
    try:
        stored = ctx.container.save_bond_terms.execute(
            SaveBondTermsRequest(
                user_id=ctx.user_id,
                portfolio_id=ctx.portfolio_id,
                ticker=row.ticker,
                contracted_rate_pct=rate,
                purchase_date=purchase if isinstance(purchase, dt.date) else None,
            )
        )
    except DomainError as error:
        st.error(str(error))
        return
    st.session_state["mtm_flash"] = (
        f"{row.ticker}: taxa contratada {format_ratio_as_pct(stored)} {row.kind.rate_suffix}."
    )
    cache.invalidate()
    st.rerun()


def _verdict(row: BondMarkRow) -> None:
    if row.difference is None or row.maturity is None:
        return
    gap = format_brl(abs(row.difference))
    pct = format_ratio_as_pct(abs(row.difference_pct or 0.0))
    until = f"{row.maturity:%d/%m/%Y}"
    if row.difference > 0:
        st.success(
            f"**Marcação a favor.** Vender hoje entrega **{gap} a mais** ({pct}) do que o "
            "título vale pela sua taxa contratada: o mercado já antecipou parte do ganho. "
            f"Vender só rende mais que levar até {until} se o dinheiro for reinvestido "
            f"acima de **{_rate(row.break_even_rate, row)}** até essa data."
        )
    elif row.difference < 0:
        st.info(
            f"**Marcação contra.** Vender hoje entrega **{gap} a menos** ({pct}) do que o "
            "valor na curva. Levando até o vencimento você recebe a taxa contratada de "
            f"**{_rate(row.contracted_rate, row)}**; para compensar a venda, o dinheiro "
            f"teria de render acima de {_rate(row.break_even_rate, row)} até {until}."
        )
    else:
        st.info("Taxa de mercado igual à contratada: vender ou levar dá o mesmo.")


def _bond(ctx: PageContext, row: BondMarkRow) -> None:
    with st.container(border=True):
        maturity = f" · vence {row.maturity:%d/%m/%Y}" if row.maturity else ""
        st.markdown(f"**{row.ticker}** · {row.kind.label_pt}{maturity}")
        if row.quote_date:
            st.caption(
                f"Cotação de {row.quote_date:%d/%m/%Y} · resgate hoje "
                f"{_rate(row.sell_rate, row)} · compra hoje {_rate(row.buy_rate, row)}"
                + (
                    f" · {format_number(row.business_days, 0)} dias úteis"
                    if row.business_days
                    else ""
                )
            )
        if row.sale_value is not None and row.curve_value is not None:
            cols = st.columns(3)
            cols[0].metric(
                "Vender hoje",
                format_brl(row.sale_value),
                help="Quantidade × PU de resgate antecipado do Tesouro (antes de IR e taxas).",
            )
            label = "estimada" if row.estimated else "contratada"
            cols[1].metric(
                f"Na curva ({format_ratio_as_pct(row.contracted_rate)})",
                format_brl(row.curve_value),
                help=f"Quanto a posição valeria hoje pela taxa {label} da compra: o caminho "
                "de quem leva até o vencimento.",
            )
            cols[2].metric(
                "Diferença da marcação",
                format_brl(row.difference),
                format_ratio_as_pct(row.difference_pct),
                help=help_text("mark_to_market"),
            )
            _verdict(row)
        elif row.message:
            st.caption(row.message)
        if row.kind is not BondKind.SELIC and row.quote_date is not None:
            title = "Alterar taxa contratada" if row.contracted_rate else "Informar taxa"
            with st.expander(title, expanded=row.contracted_rate is None):
                _terms_form(ctx, row)


def render(ctx: PageContext) -> None:
    """Seção de marcação a mercado; não aparece se a carteira não tem títulos do Tesouro."""
    report = ctx.container.mark_to_market.execute(ctx.portfolio_id)
    if not report.rows:
        return
    st.markdown("#### Marcação a mercado", help=help_text("mark_to_market"))
    guide.links(ctx.guide_page, ["mark_to_market"])
    st.caption(
        "Compara vender o título hoje (preço de mercado) com levá-lo até o vencimento "
        "(sua taxa contratada). Não considera IR, que incide sobre o ganho nos dois casos."
    )
    flash = st.session_state.pop("mtm_flash", None)
    if flash:
        st.success(flash)
    for row in report.rows:
        _bond(ctx, row)
