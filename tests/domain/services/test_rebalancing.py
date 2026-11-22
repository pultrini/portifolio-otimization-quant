"""Testes da sugestão de aporte (valores calculados à mão)."""

from decimal import Decimal

import pytest

from domain.entities.allocation_profile import AllocationProfile
from domain.exceptions import DomainError
from domain.services.rebalancing import suggest_contribution
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.money import Money

D = Decimal
EQ, FI, CR = AssetClass.BR_EQUITY, AssetClass.BR_FIXED_INCOME, AssetClass.CRYPTO


def _plan_values(plan: object, field: str) -> dict[AssetClass, Decimal]:
    return {c.asset_class: getattr(c, field).amount for c in plan.classes}  # type: ignore[attr-defined]


def test_aporte_vai_para_a_classe_abaixo_do_alvo() -> None:
    # Atual 700/300, alvo 50/50, aporte 200 -> patrimônio 1200, alvo 600/600.
    plan = suggest_contribution(
        {EQ: Money.brl("700"), FI: Money.brl("300")},
        AllocationProfile({EQ: D("50"), FI: D("50")}),
        Money.brl("200"),
    )
    assert _plan_values(plan, "contribution") == {EQ: D("0"), FI: D("200")}
    assert _plan_values(plan, "sale") == {EQ: D("0"), FI: D("0")}
    assert plan.total_after.amount == D("1200")


def test_enchimento_de_nivel_prioriza_maior_deficit() -> None:
    # Patrimônio 1000 + 200 = 1200; alvos 40/30/30% = 480 / 360 / 360.
    # Déficits: FI 360 e CR 60. λ = 360 - 200 = 160 >= 60: todo o aporte vai para FI,
    # que continua mais abaixo do alvo que CR mesmo depois de receber.
    current = {EQ: Money.brl("700"), FI: Money.brl("0"), CR: Money.brl("300")}
    profile = AllocationProfile({EQ: D("40"), FI: D("30"), CR: D("30")})
    plan = suggest_contribution(current, profile, Money.brl("200"))
    assert _plan_values(plan, "contribution") == {EQ: D("0"), FI: D("200"), CR: D("0")}


def test_enchimento_divide_quando_niveis_se_encontram() -> None:
    # Patrimônio 900 + 300 = 1200, alvos 400 cada: déficits EQ 0, FI 300, CR 100.
    # λ = (300 + 100 - 300) / 2 = 50 -> compra 250 em FI e 50 em CR.
    current = {EQ: Money.brl("500"), FI: Money.brl("100"), CR: Money.brl("300")}
    profile = AllocationProfile({EQ: D("33.33"), FI: D("33.33"), CR: D("33.34")})
    plan = suggest_contribution(current, profile, Money.brl("300"))
    buys = _plan_values(plan, "contribution")
    assert sum(buys.values()) == D("300")
    finals = _plan_values(plan, "final_value")
    targets = _plan_values(plan, "target_value")
    # As duas classes que receberam aporte terminam com o mesmo déficit residual.
    assert targets[FI] - finals[FI] == pytest.approx(targets[CR] - finals[CR], abs=D("0.02"))


def test_com_vendas_termina_exatamente_no_alvo() -> None:
    plan = suggest_contribution(
        {EQ: Money.brl("700"), FI: Money.brl("300")},
        AllocationProfile({EQ: D("50"), FI: D("50")}),
        Money.brl("200"),
        allow_sales=True,
    )
    assert _plan_values(plan, "contribution") == {EQ: D("0"), FI: D("300")}
    assert _plan_values(plan, "sale") == {EQ: D("100"), FI: D("0")}
    assert _plan_values(plan, "final_value") == {EQ: D("600"), FI: D("600")}


def test_classe_nova_do_perfil_e_centavos_exatos() -> None:
    # Carteira só com EQ; perfil pede 1/3 em cripto; aporte com centavos.
    plan = suggest_contribution(
        {EQ: Money.brl("100")},
        AllocationProfile({EQ: D("66.67"), CR: D("33.33")}),
        Money.brl("10.01"),
    )
    buys = _plan_values(plan, "contribution")
    assert sum(buys.values()) == D("10.01")
    assert all(v == v.quantize(D("0.01")) for v in buys.values())
    assert buys[CR] == D("10.01")


def test_aporte_negativo() -> None:
    with pytest.raises(DomainError):
        suggest_contribution({}, AllocationProfile({EQ: D("100")}), Money.brl("-1"))


def test_classe_acima_do_alvo_hoje_nao_recebe() -> None:
    # Exemplo do usuário: renda variável com 560 / 1.000 = 56%, alvo 40%. Já está acima
    # do alvo hoje, então não recebe nada (mesmo que 40% do patrimônio futuro de 2.000,
    # ou seja 800, seja maior que os 560 atuais).
    current = {EQ: Money.brl("560"), FI: Money.brl("370"), CR: Money.brl("70")}
    profile = AllocationProfile({EQ: D("40"), FI: D("50"), CR: D("10")})
    plan = suggest_contribution(current, profile, Money.brl("1000"))
    buys = _plan_values(plan, "contribution")
    assert buys[EQ] == D("0")
    # Patrimônio 2000: alvos FI 1000 e CR 200 -> déficits 630 e 130 (760 < 1000).
    # Excedente de 240 dividido entre FI e CR na proporção 50:10 -> 200 e 40.
    assert buys[FI] == D("830.00")
    assert buys[CR] == D("170.00")
    assert sum(buys.values()) == D("1000")
