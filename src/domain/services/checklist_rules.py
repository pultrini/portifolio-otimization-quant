"""Respostas automáticas do checklist a partir de dados abertos (sem LLM).

Cada regra devolve Sim/Não com a evidência usada, ou None quando o dado não existe.
Perguntas de julgamento (liderança, governança, perenidade, localização...) não têm
regra: ficam para o usuário responder.
"""

from __future__ import annotations

from datetime import date

from domain.entities.fundamentals import ReitFundamentals, StockFundamentals
from domain.value_objects.checklist import AnswerSource, ChecklistAnswer

ROE_THRESHOLD = 0.05
GROWTH_THRESHOLD = 0.05
MIN_AGE_YEARS = 30
BLUE_CHIP_MARKET_CAP_BRL = 10_000_000_000.0  # R$ 10 bilhões
MAX_NET_DEBT_TO_EBITDA = 2.0
DIVIDEND_YEARS_REQUIRED = 5
P_VP_BUY = 1.0
P_VP_DISCARD = 1.5
REIT_DIVIDEND_MONTHS = 48
REIT_DIVIDEND_MIN_MONTHS = 44  # tolera até 4 meses sem distribuição em 4 anos


def _auto(value: bool, evidence: str) -> ChecklistAnswer:
    return ChecklistAnswer(value, AnswerSource.AUTO, evidence)


def _br(text: str) -> str:
    """Troca o ponto decimal por vírgula no texto da evidência."""
    return text.replace(".", ",")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%".replace(".", ",")


def _cagr(first: float, last: float, years: int) -> float | None:
    if years <= 0 or first <= 0 or last <= 0:
        return None
    return float((last / first) ** (1 / years) - 1)


def stock_answers(fund: StockFundamentals, today: date) -> dict[str, ChecklistAnswer]:
    """Responde as perguntas de ações que têm regra objetiva.

    Regras:
        roe: ROE > 5% em todos os anos disponíveis (lucro / patrimônio).
        cagr: CAGR da receita OU do lucro > 5% entre o ano mais antigo e o mais recente.
        dividends: pagou proventos em cada um dos últimos 5 anos-calendário completos.
        age: data de constituição na CVM há mais de 30 anos.
        blue_chip: valor de mercado >= R$ 10 bilhões.
        independence: controle estatal (CVM) = Não. Sem controle estatal = Sim, com a
            ressalva de que concentração em cliente único não está em dado aberto.
        low_debt: dívida líquida / EBITDA < 2 em todos os anos disponíveis.
    """
    answers: dict[str, ChecklistAnswer] = {}
    years = sorted(fund.annual, key=lambda a: a.year)

    roes = [(a.year, a.roe) for a in years if a.roe is not None]
    if roes:
        text = ", ".join(f"{y}: {_pct(r)}" for y, r in roes)
        answers["roe"] = _auto(all(r > ROE_THRESHOLD for _, r in roes), f"ROE {text}")

    growths: list[str] = []
    passed = False
    for label, values in (
        ("receita", [(a.year, a.revenue) for a in years if a.revenue is not None]),
        ("lucro", [(a.year, a.net_income) for a in years if a.net_income is not None]),
    ):
        if len(values) >= 2:
            (y0, v0), (y1, v1) = values[0], values[-1]
            growth = _cagr(v0, v1, y1 - y0)
            if growth is not None:
                growths.append(f"{label} {y0}-{y1}: {_pct(growth)} a.a.")
                passed = passed or growth > GROWTH_THRESHOLD
    if growths:
        answers["cagr"] = _auto(passed, "CAGR " + "; ".join(growths))

    if fund.dividend_years:
        last_full = today.year - 1
        required = set(range(last_full - DIVIDEND_YEARS_REQUIRED + 1, last_full + 1))
        missing = sorted(required - fund.dividend_years)
        evidence = (
            f"Proventos em todos os anos de {min(required)} a {last_full}"
            if not missing
            else f"Sem proventos em: {', '.join(map(str, missing))}"
        )
        answers["dividends"] = _auto(not missing, evidence)

    if fund.constitution_date is not None:
        age = (
            today.year
            - fund.constitution_date.year
            - (
                (today.month, today.day)
                < (fund.constitution_date.month, fund.constitution_date.day)
            )
        )
        evidence = f"Constituição na CVM: {fund.constitution_date:%d/%m/%Y} ({age} anos)."
        if age <= MIN_AGE_YEARS:
            # A CVM registra a constituição da pessoa jurídica atual; holdings e
            # reorganizações podem ser bem mais novas que a empresa operacional.
            evidence += " Confira a fundação: reorganizações deixam essa data mais recente."
        answers["age"] = _auto(age > MIN_AGE_YEARS, evidence)

    if fund.market_cap_brl is not None:
        answers["blue_chip"] = _auto(
            fund.market_cap_brl >= BLUE_CHIP_MARKET_CAP_BRL,
            _br(f"Valor de mercado: R$ {fund.market_cap_brl / 1e9:.1f} bi (critério: >= R$ 10 bi)"),
        )

    if fund.control:
        state = "ESTATAL" in fund.control.upper()
        answers["independence"] = _auto(
            not state,
            f"Controle acionário (CVM): {fund.control}."
            + ("" if state else " Concentração em cliente único não verificada."),
        )

    leverage = [(a.year, a.net_debt_to_ebitda) for a in years if a.net_debt_to_ebitda is not None]
    if leverage:
        text = ", ".join(f"{y}: {v:.2f}".replace(".", ",") for y, v in leverage)
        answers["low_debt"] = _auto(
            all(v < MAX_NET_DEBT_TO_EBITDA for _, v in leverage), f"Dív. líq./EBITDA {text}"
        )
    return answers


def reit_answers(fund: ReitFundamentals, price: float | None) -> dict[str, ChecklistAnswer]:
    """Responde as perguntas de FIIs que têm regra objetiva.

    Regras:
        price_to_book: P/VP = preço / valor patrimonial por cota < 1.
        reit_dividends: dividend yield > 0 em pelo menos 44 dos últimos 48 meses.
        sector_yield: yield de 12 meses >= mediana do mesmo segmento.
    """
    answers: dict[str, ChecklistAnswer] = {}
    p_vp = price_to_book(fund, price)
    if p_vp is not None:
        answers["price_to_book"] = _auto(
            p_vp < P_VP_BUY,
            _br(
                f"P/VP {p_vp:.2f} (preço {price:.2f} / VP por cota {fund.book_value_per_share:.2f})"
            ),
        )
    if fund.months_observed >= REIT_DIVIDEND_MONTHS:
        answers["reit_dividends"] = _auto(
            fund.months_with_dividends >= REIT_DIVIDEND_MIN_MONTHS,
            f"Distribuiu em {fund.months_with_dividends} dos últimos {fund.months_observed} meses",
        )
    elif fund.months_observed:
        answers["reit_dividends"] = _auto(
            False, f"Só {fund.months_observed} meses de informes disponíveis (precisa de 48)"
        )
    if fund.dividend_yield_12m is not None and fund.segment_median_yield_12m is not None:
        answers["sector_yield"] = _auto(
            fund.dividend_yield_12m >= fund.segment_median_yield_12m,
            f"Yield 12m {_pct(fund.dividend_yield_12m)} vs. mediana de "
            f"{fund.segment or 'segmento'} {_pct(fund.segment_median_yield_12m)}",
        )
    return answers


def price_to_book(fund: ReitFundamentals, price: float | None) -> float | None:
    if price is None or not fund.book_value_per_share or fund.book_value_per_share <= 0:
        return None
    return price / fund.book_value_per_share


def is_discarded(fund: ReitFundamentals | None, price: float | None) -> str | None:
    """Regra eliminatória do usuário: FII com P/VP acima de 1,5 é descartado."""
    if fund is None:
        return None
    p_vp = price_to_book(fund, price)
    if p_vp is not None and p_vp > P_VP_DISCARD:
        return f"P/VP {p_vp:.2f} acima de 1,5".replace(".", ",")
    return None
