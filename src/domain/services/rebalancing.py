"""Delta entre alocação atual e alvo, com sugestão de aporte (CLAUDE.md 5.5)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from domain.entities.allocation_profile import AllocationProfile
from domain.exceptions import DomainError
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.money import CENTS, Money
from domain.value_objects.percentage import HUNDRED

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ClassRebalance:
    """Situação de uma classe antes e depois da sugestão (valores em BRL)."""

    asset_class: AssetClass
    current_value: Money
    target_pct: Decimal
    target_value: Money  # alvo calculado sobre o patrimônio após o aporte
    contribution: Money
    sale: Money

    @property
    def final_value(self) -> Money:
        return self.current_value + self.contribution - self.sale


@dataclass(frozen=True, slots=True)
class RebalancePlan:
    classes: list[ClassRebalance]
    total_before: Money
    total_after: Money


def water_fill[K](deficits: Mapping[K, Decimal], budget: Decimal) -> dict[K, Decimal]:
    """Distribui `budget` reduzindo primeiro os maiores déficits ("encher até o nível").

    Encontra λ >= 0 tal que Σ max(0, d_i - λ) = budget e compra d_i - λ em cada classe.
    Resultado: as classes mais abaixo do alvo recebem primeiro, e ao final todas as
    que receberam aporte ficam com o mesmo déficit residual λ. Isso minimiza a soma dos
    quadrados das diferenças para o alvo, sem vender nada.
    """
    ordered = sorted(
        ((d, c) for c, d in deficits.items() if d > 0), reverse=True, key=lambda x: x[0]
    )
    if not ordered or budget <= 0:
        return {}
    running = ZERO
    level = ZERO
    for k, (deficit, _) in enumerate(ordered, start=1):
        running += deficit
        candidate = (running - budget) / k
        next_deficit = ordered[k][0] if k < len(ordered) else ZERO
        # λ precisa ficar entre o k-ésimo déficit e o próximo (ordem decrescente).
        if candidate >= next_deficit:
            level = max(candidate, ZERO)
            break
    return {c: d - level for d, c in ordered if d > level}


def _to_cents[K](amounts: dict[K, Decimal], total: Decimal) -> dict[K, Decimal]:
    """Arredonda para centavos sem perder nem criar dinheiro.

    Trunca cada valor e entrega os centavos que sobraram à maior parcela, para que a
    soma das sugestões seja exatamente o valor do aporte.
    """
    rounded = {c: v.quantize(CENTS, rounding=ROUND_DOWN) for c, v in amounts.items()}
    remainder = total.quantize(CENTS) - sum(rounded.values(), ZERO)
    if rounded and remainder:
        largest = max(rounded, key=lambda c: rounded[c])
        rounded[largest] += remainder
    return rounded


def eligible_classes(
    values: Mapping[AssetClass, Decimal], profile: AllocationProfile
) -> set[AssetClass]:
    """Classes que podem receber aporte: percentual atual abaixo do alvo.

    Carteira vazia: todas as classes com alvo maior que zero.
    """
    total = sum(values.values(), ZERO)
    if total <= 0:
        return {c for c, pct in profile.targets.items() if pct > 0}
    return {
        c
        for c in set(values) | set(profile.targets)
        if values.get(c, ZERO) / total * HUNDRED < profile.target_for(c)
    }


def _underweight_fill(
    values: Mapping[AssetClass, Decimal],
    profile: AllocationProfile,
    deficits: Mapping[AssetClass, Decimal],
    budget: Decimal,
) -> dict[AssetClass, Decimal]:
    """Enchimento de nível só entre as classes abaixo do alvo; excedente pelo alvo %."""
    eligible = eligible_classes(values, profile)
    buys = water_fill({c: d for c, d in deficits.items() if c in eligible}, budget)
    excess = budget - sum(buys.values(), ZERO)
    weights = {c: profile.target_for(c) for c in eligible if profile.target_for(c) > 0}
    total_weight = sum(weights.values(), ZERO)
    if excess > 0 and total_weight > 0:
        for c, weight in weights.items():
            buys[c] = buys.get(c, ZERO) + excess * weight / total_weight
    return buys


def suggest_contribution(
    current: Mapping[AssetClass, Money],
    profile: AllocationProfile,
    contribution: Money,
    allow_sales: bool = False,
) -> RebalancePlan:
    """Sugere como aportar (e, se permitido, vender) para se aproximar do alvo.

    Patrimônio após o aporte: T = Σ atual + aporte. Valor alvo da classe: T x alvo%.
    Déficit: max(0, alvo - atual).

    - Sem vendas (padrão, aportes antes de vendas): só recebem classes cujo
      percentual ATUAL está abaixo do alvo (quem já está no alvo ou acima não
      recebe, mesmo que o alvo em reais cresça com o aporte). Entre elas, o aporte
      é distribuído por enchimento de nível sobre os déficits (`water_fill`); o que
      sobrar depois de cobrir os déficits é dividido entre elas na proporção do alvo.
    - Com vendas: compra todo o déficit e vende todo o excesso; a carteira termina
      exatamente no alvo (compras - vendas = aporte).

    Raises:
        DomainError: aporte negativo ou valores fora de BRL.
    """
    if contribution.is_negative():
        raise DomainError("O aporte não pode ser negativo.")
    classes = sorted(set(current) | set(profile.targets))
    values = {c: current.get(c, Money.zero()).amount for c in classes}
    budget = contribution.amount
    total_after = sum(values.values(), ZERO) + budget
    targets = {c: total_after * profile.target_for(c) / HUNDRED for c in classes}
    deficits = {c: max(targets[c] - values[c], ZERO) for c in classes}

    if allow_sales:
        buys = {c: d for c, d in deficits.items() if d > 0}
        sales = {c: values[c] - targets[c] for c in classes if values[c] > targets[c]}
        sales = _to_cents(sales, sum(sales.values(), ZERO))
        buys = _to_cents(buys, budget + sum(sales.values(), ZERO))
    else:
        buys = _to_cents(_underweight_fill(values, profile, deficits, budget), budget)
        sales = {}

    return RebalancePlan(
        classes=[
            ClassRebalance(
                asset_class=c,
                current_value=Money.brl(values[c]),
                target_pct=profile.target_for(c),
                target_value=Money.brl(targets[c]).rounded(),
                contribution=Money.brl(buys.get(c, ZERO)),
                sale=Money.brl(sales.get(c, ZERO)),
            )
            for c in classes
        ],
        total_before=Money.brl(total_after - budget),
        total_after=Money.brl(total_after),
    )
