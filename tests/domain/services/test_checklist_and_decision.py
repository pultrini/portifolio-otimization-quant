"""Testes das respostas automáticas do checklist e da decisão de aporte por ativo."""

from datetime import date
from decimal import Decimal

import pytest

from domain.entities.fundamentals import AnnualFigures, ReitFundamentals, StockFundamentals
from domain.services.checklist_rules import is_discarded, reit_answers, stock_answers
from domain.services.contribution_decision import (
    Candidate,
    Decision,
    decide_class,
    final_score,
    lot_size,
    quant_scores,
)
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.ticker import Ticker

D = Decimal
TODAY = date(2026, 11, 21)
EQ = AssetClass.BR_EQUITY


def _stock(**overrides: object) -> StockFundamentals:
    base: dict[str, object] = {
        "ticker": "ABCD3",
        "annual": (
            AnnualFigures(
                2022, revenue=100, net_income=10, ebitda=20, equity=100, total_debt=30, cash=10
            ),
            AnnualFigures(
                2025, revenue=133.1, net_income=12, ebitda=25, equity=110, total_debt=40, cash=5
            ),
        ),
        "dividend_years": frozenset(range(2018, 2026)),
        "constitution_date": date(1961, 6, 30),
        "control": "PRIVADO HOLDING",
        "market_cap_brl": 214.5e9,
    }
    base.update(overrides)
    return StockFundamentals(**base)  # type: ignore[arg-type]


class TestStockRules:
    def test_empresa_que_passa_em_tudo(self) -> None:
        answers = stock_answers(_stock(), TODAY)
        # Receita 100 -> 133,1 em 3 anos = 10% a.a.; ROE 10% e 10,9%; DL/EBITDA 1,0 e 1,4.
        assert {k: a.value for k, a in answers.items()} == {
            "roe": True,
            "cagr": True,
            "dividends": True,
            "age": True,
            "blue_chip": True,
            "independence": True,
            "low_debt": True,
        }
        assert "10,0% a.a." in answers["cagr"].evidence
        assert "65 anos" in answers["age"].evidence

    def test_um_ano_de_roe_baixo_reprova(self) -> None:
        annual = (
            AnnualFigures(2023, net_income=10, equity=100),
            AnnualFigures(2024, net_income=4, equity=100),
        )
        assert stock_answers(_stock(annual=annual), TODAY)["roe"].value is False

    def test_estatal_reprova_independencia(self) -> None:
        answer = stock_answers(_stock(control="ESTATAL HOLDING"), TODAY)["independence"]
        assert answer.value is False

    def test_ano_sem_dividendo_reprova(self) -> None:
        answer = stock_answers(_stock(dividend_years=frozenset({2021, 2022, 2024, 2025})), TODAY)
        assert answer["dividends"].value is False
        assert "2023" in answer["dividends"].evidence

    def test_endividada(self) -> None:
        annual = (AnnualFigures(2025, ebitda=10, total_debt=40, cash=5),)
        assert stock_answers(_stock(annual=annual), TODAY)["low_debt"].value is False

    def test_sem_dados_nao_responde(self) -> None:
        empty = StockFundamentals("ABCD3")
        assert stock_answers(empty, TODAY) == {}


class TestReitRules:
    FUND = ReitFundamentals(
        "WXYZ11",
        segment="Logística",
        book_value_per_share=100.0,
        months_with_dividends=46,
        months_observed=48,
        dividend_yield_12m=0.11,
        segment_median_yield_12m=0.10,
    )

    def test_regras(self) -> None:
        answers = reit_answers(self.FUND, price=95.0)
        assert answers["price_to_book"].value is True
        assert "0,95" in answers["price_to_book"].evidence
        assert answers["reit_dividends"].value is True
        assert answers["sector_yield"].value is True

    def test_historico_curto(self) -> None:
        short = ReitFundamentals("WXYZ11", months_with_dividends=20, months_observed=20)
        assert reit_answers(short, None)["reit_dividends"].value is False

    @pytest.mark.parametrize(("price", "discarded"), [(150.0, False), (151.0, True)])
    def test_descarte_por_p_vp(self, price: float, discarded: bool) -> None:
        assert (is_discarded(self.FUND, price) is not None) is discarded


class TestNotas:
    def test_quant_percentil_medio(self) -> None:
        a = Candidate(Ticker("AAAA3"), EQ, D(0), D(10), (1.0, 1.5, 2.0))
        b = Candidate(Ticker("BBBB3"), EQ, D(0), D(10), (0.5, 2.0, None))
        c = Candidate(Ticker("CCCC3"), EQ, D(0), D(10), (None, 1.0, 1.0))
        scores = quant_scores([a, b, c])
        # Sharpe: C(None) < B < A; Sortino: C < A < B; Calmar: B(None) < C < A.
        assert scores[Ticker("AAAA3")] == pytest.approx((1 + 0.5 + 1) / 3 * 100)
        assert scores[Ticker("BBBB3")] == pytest.approx((0.5 + 1 + 0) / 3 * 100)
        assert scores[Ticker("CCCC3")] == pytest.approx((0 + 0 + 0.5) / 3 * 100)

    def test_empate_recebe_posicao_media(self) -> None:
        a = Candidate(Ticker("AAAA3"), EQ, D(0), D(10), (1.0, 1.0, 1.0))
        b = Candidate(Ticker("BBBB3"), EQ, D(0), D(10), (1.0, 1.0, 1.0))
        c = Candidate(Ticker("CCCC3"), EQ, D(0), D(10), (2.0, 2.0, 2.0))
        scores = quant_scores([a, b, c])
        assert scores[Ticker("AAAA3")] == scores[Ticker("BBBB3")] == pytest.approx(25.0)
        assert scores[Ticker("CCCC3")] == pytest.approx(100.0)

    def test_candidato_unico(self) -> None:
        only = Candidate(Ticker("AAAA3"), EQ, D(0), D(10))
        assert quant_scores([only]) == {Ticker("AAAA3"): 100.0}

    def test_nota_final(self) -> None:
        assert final_score(80, 50, 0.5) == 65
        assert final_score(80, None, 0.5) == 80

    def test_lotes(self) -> None:
        assert lot_size(Ticker("PETR4"), EQ) == 1
        assert lot_size(Ticker("NTNB-2060"), AssetClass.BR_FIXED_INCOME) == D("0.01")
        assert lot_size(Ticker("BTC"), AssetClass.CRYPTO) == D("0.00000001")


class TestDecisao:
    def test_aporte_em_cotas_inteiras_para_quem_tem_mais_nota(self) -> None:
        # Mesma nota quant (empate impossível com 2 candidatos: 100 e 0), checklist
        # define. A: quant 100 + checklist 100% -> 100; B: quant 0 + checklist 50% -> 25.
        a = Candidate(Ticker("AAAA3"), EQ, D("0"), D("10"), (2.0, 2.0, 2.0), 1.0)
        b = Candidate(Ticker("BBBB3"), EQ, D("0"), D("7"), (1.0, 1.0, 1.0), 0.5)
        result = decide_class(EQ, [a, b], D("100"))
        by = {d.ticker.symbol: d for d in result.decisions}
        # Pesos ideais 100/125 = 80% e 20%: alvos 80 e 20 -> 8 cotas de A e 2 de B (14).
        # Troco de 6: nenhum alvo ainda em aberto que caiba -> sobra 6.
        assert by["AAAA3"].ideal_weight == pytest.approx(0.8)
        assert by["AAAA3"].quantity == D("8")
        assert by["BBBB3"].quantity == D("2")
        assert result.leftover == D("6")
        assert result.decisions[0].ticker.symbol == "AAAA3"

    def test_troco_compra_lote_extra(self) -> None:
        # Sem métricas de risco os dois empatam (quant 50) e têm o mesmo checklist:
        # pesos 50/50, alvos 50 e 50 -> 1 cota de cada (60); troco 40 compra mais 1 de
        # quem está mais longe do alvo (ambos a 20; vale o primeiro) -> 3 cotas, sobra 10.
        a = Candidate(Ticker("AAAA3"), EQ, D("0"), D("30"), checklist_score=1.0)
        b = Candidate(Ticker("BBBB3"), EQ, D("0"), D("30"), checklist_score=1.0)
        result = decide_class(EQ, [a, b], D("100"))
        assert {d.quant_score for d in result.decisions} == {50.0}
        assert sum(d.quantity for d in result.decisions) == 3
        assert result.leftover == D("10")

    def test_descartado_e_sem_preco(self) -> None:
        ok = Candidate(Ticker("AAAA3"), EQ, D("0"), D("10"), checklist_score=0.5)
        bad = Candidate(Ticker("FIIX11"), EQ, D("0"), D("200"), discarded_reason="P/VP 2,00")
        nop = Candidate(Ticker("NOPE3"), EQ, D("0"), None, checklist_score=1.0)
        result = decide_class(EQ, [ok, bad, nop], D("50"))
        by = {d.ticker.symbol: d for d in result.decisions}
        assert by["FIIX11"].decision is Decision.DISCARDED
        assert by["NOPE3"].decision is Decision.NO_PRICE
        assert by["AAAA3"].quantity == D("5")

    def test_ativo_acima_do_peso_espera(self) -> None:
        big = Candidate(Ticker("AAAA3"), EQ, D("1000"), D("10"), (2.0, 2.0, 2.0), 0.5)
        small = Candidate(Ticker("BBBB3"), EQ, D("0"), D("10"), (1.0, 1.0, 1.0), 0.5)
        result = decide_class(EQ, [big, small], D("100"))
        by = {d.ticker.symbol: d for d in result.decisions}
        assert by["AAAA3"].decision is Decision.WAIT
        assert by["BBBB3"].quantity == D("10")

    def test_sem_checklist_mantem_proporcao_atual(self) -> None:
        fi = AssetClass.BR_FIXED_INCOME
        cdi = Candidate(Ticker("CDI"), fi, D("750"), D("2.5"))
        ntnb = Candidate(Ticker("NTNB-2060"), fi, D("250"), D("4000"))
        result = decide_class(fi, [cdi, ntnb], D("100"))
        assert not result.uses_checklist
        by = {d.ticker.symbol: d for d in result.decisions}
        # Proporção 75/25: alvos 825 e 275 -> aportes 75 (CDI) e 25 (0,01 NTN-B = 40 > 25).
        assert by["CDI"].amount + by["NTNB-2060"].amount + result.leftover == D("100")
        assert by["NTNB-2060"].quantity == D("0")
        assert by["CDI"].quantity * D("2.5") == by["CDI"].amount


def test_abaixo_do_ideal_mas_aporte_nao_chega_aguarda() -> None:
    # Três ativos de mesma nota (pesos 1/3). Atuais 0, 20 e 100; aporte 15 -> classe 135,
    # alvos 45 cada. Déficits: A 45, B 25, C 0 (C está acima). Enchimento com 15:
    # λ = 45 - 15 = 30 > 25, então só A recebe (1 cota de 10; troco 5 não paga B a 6).
    a = Candidate(Ticker("AAAA3"), EQ, D("0"), D("10"), (1.0, 1.0, 1.0), 1.0)
    b = Candidate(Ticker("BBBB3"), EQ, D("20"), D("6"), (1.0, 1.0, 1.0), 1.0)
    c = Candidate(Ticker("CCCC3"), EQ, D("100"), D("5"), (1.0, 1.0, 1.0), 1.0)
    result = decide_class(EQ, [a, b, c], D("15"))
    by = {d.ticker.symbol: d for d in result.decisions}
    assert by["AAAA3"].quantity == D("1")
    assert by["BBBB3"].decision is Decision.WAIT
    assert "mais abaixo" in by["BBBB3"].reason
    assert by["CCCC3"].decision is Decision.WAIT
    assert "peso ideal ou acima" in by["CCCC3"].reason
