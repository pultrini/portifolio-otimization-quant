"""Decisão de aporte dentro de uma classe: em quais ativos colocar o dinheiro.

Dois critérios, combinados numa nota final por ativo:
    - quant: desempenho ajustado a risco (Sharpe, Sortino, Calmar) comparado entre
      os candidatos da classe;
    - checklist: fração de "Sim" nas perguntas qualitativas.

Cada ativo recebe um peso ideal proporcional à nota final (quem tem nota maior deve
ter mais peso). O aporte vai primeiro para quem está mais abaixo do peso ideal e é
convertido em lotes negociáveis (cotas inteiras na B3).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

from domain.services.rebalancing import water_fill
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.ticker import Ticker

ZERO = Decimal("0")
DEFAULT_QUANT_WEIGHT = 0.5
_TESOURO_PREFIXES = ("NTNB-", "IPCA-", "PRE-", "SELIC-")


def lot_size(ticker: Ticker, asset_class: AssetClass) -> Decimal:
    """Menor quantidade negociável.

    Ações, FIIs e BDRs na B3: 1 cota (mercado fracionário). Tesouro Direto: 0,01
    título. Cripto e CDI (aplicação por valor): fracionário até 8 casas.
    """
    if ticker.symbol == "CDI" or asset_class is AssetClass.CRYPTO:
        return Decimal("0.00000001")
    if ticker.symbol.startswith(_TESOURO_PREFIXES):
        return Decimal("0.01")
    return Decimal("1")


class Decision(StrEnum):
    BUY = "BUY"
    WAIT = "WAIT"  # já está no peso ideal (ou acima)
    DISCARDED = "DISCARDED"  # regra eliminatória (ex.: FII com P/VP > 1,5)
    NO_PRICE = "NO_PRICE"  # sem cotação para converter em quantidade
    TOO_EXPENSIVE = "TOO_EXPENSIVE"  # um lote custa mais que o disponível


@dataclass(frozen=True, slots=True)
class Candidate:
    """Ativo elegível para receber aporte dentro de uma classe.

    Attributes:
        risk_adjusted: (Sharpe, Sortino, Calmar) do ativo; None quando indefinido.
        checklist_score: Fração de "Sim" (0 a 1); None se a classe não tem checklist.
        discarded_reason: Preenchido quando uma regra eliminatória exclui o ativo.
    """

    ticker: Ticker
    asset_class: AssetClass
    current_value: Decimal
    price: Decimal | None
    risk_adjusted: tuple[float | None, float | None, float | None] = (None, None, None)
    checklist_score: float | None = None
    discarded_reason: str | None = None


@dataclass(frozen=True, slots=True)
class AssetDecision:
    ticker: Ticker
    quant_score: float | None  # 0-100
    checklist_score: float | None  # 0-100
    final_score: float | None  # 0-100
    ideal_weight: float  # fração da classe após o aporte
    current_value: Decimal
    target_value: Decimal
    quantity: Decimal
    amount: Decimal
    decision: Decision
    reason: str = ""
    price: Decimal | None = None

    @property
    def gap(self) -> Decimal:
        """Quanto falta para o ativo chegar ao alvo depois das compras já sugeridas."""
        return self.target_value - self.current_value - self.amount


@dataclass(frozen=True, slots=True)
class ClassDecision:
    asset_class: AssetClass
    budget: Decimal
    decisions: list[AssetDecision]
    leftover: Decimal
    uses_checklist: bool


def quant_scores(candidates: Sequence[Candidate]) -> dict[Ticker, float]:
    """Nota quant de 0 a 100: percentil médio em Sharpe, Sortino e Calmar.

    Para cada métrica, os candidatos são ordenados e recebem (posição) / (n - 1):
    o pior vale 0 e o melhor vale 1. Métrica indefinida (None) conta como a pior.
    A nota é a média das três posições x 100. Com um único candidato, a nota é 100.

    É uma comparação relativa: diz quem foi melhor entre as opções da classe, não se
    o ativo é bom em termos absolutos.
    """
    n = len(candidates)
    if n == 0:
        return {}
    if n == 1:
        return {candidates[0].ticker: 100.0}
    totals = {c.ticker: 0.0 for c in candidates}
    metrics = len(candidates[0].risk_adjusted)
    for index in range(metrics):
        # None fica no fim da ordenação (pior posição).
        def key(c: Candidate, index: int = index) -> tuple[bool, float]:
            value = c.risk_adjusted[index]
            return (value is not None, value if value is not None else 0.0)

        ordered = sorted(candidates, key=key)
        # Empates recebem a posição média do grupo: a nota não pode depender da ordem
        # em que os ativos chegaram (ex.: dois ativos sem histórico ficam com 0,5).
        start = 0
        while start < n:
            end = start
            while end + 1 < n and key(ordered[end + 1]) == key(ordered[start]):
                end += 1
            average_position = (start + end) / 2
            for candidate in ordered[start : end + 1]:
                totals[candidate.ticker] += average_position / (n - 1)
            start = end + 1
    return {ticker: total / metrics * 100 for ticker, total in totals.items()}


def final_score(quant: float | None, checklist: float | None, quant_weight: float) -> float:
    """Nota final = peso_quant x quant + (1 - peso_quant) x checklist (0 a 100).

    Sem checklist, a nota final é a própria nota quant.
    """
    if checklist is None:
        return quant or 0.0
    return quant_weight * (quant or 0.0) + (1 - quant_weight) * checklist


def decide_class(
    asset_class: AssetClass,
    candidates: Sequence[Candidate],
    budget: Decimal,
    quant_weight: float = DEFAULT_QUANT_WEIGHT,
) -> ClassDecision:
    """Distribui o aporte da classe entre os ativos e converte em lotes.

    Passos:
        1. Exclui descartados e ativos sem cotação.
        2. Peso ideal: proporcional à nota final quando há checklist; sem checklist
           (renda fixa, cripto), mantém a proporção atual entre os ativos.
        3. Alvo do ativo = peso ideal x (valor atual da classe + aporte); o aporte vai
           primeiro para quem está mais abaixo do alvo (enchimento de nível).
        4. Arredonda para baixo em lotes; o troco compra lotes adicionais de quem
           ficou mais longe do alvo, enquanto couber no valor disponível.
    """
    uses_checklist = any(c.checklist_score is not None for c in candidates)
    eligible = [c for c in candidates if c.discarded_reason is None and c.price]
    quant = quant_scores(eligible)

    scores: dict[Ticker, float] = {}
    for c in eligible:
        checklist = c.checklist_score * 100 if c.checklist_score is not None else None
        scores[c.ticker] = final_score(quant.get(c.ticker), checklist, quant_weight)

    weights = _ideal_weights(eligible, scores, uses_checklist)
    class_after = sum((c.current_value for c in eligible), ZERO) + budget
    targets = {c.ticker: class_after * Decimal(str(weights[c.ticker])) for c in eligible}
    deficits = {c.ticker: max(targets[c.ticker] - c.current_value, ZERO) for c in eligible}
    amounts = water_fill(deficits, budget)
    quantities, spent = _to_lots(eligible, amounts, targets, budget)
    leftover = budget - sum(spent.values(), ZERO)

    decisions: list[AssetDecision] = []
    for c in candidates:
        if c.discarded_reason is not None:
            decision, reason = Decision.DISCARDED, c.discarded_reason
        elif not c.price:
            decision, reason = Decision.NO_PRICE, "Sem cotação: atualize os dados."
        elif quantities.get(c.ticker, ZERO) > 0:
            decision, reason = Decision.BUY, ""
        elif budget <= 0:
            # A classe inteira não recebe neste aporte (já no alvo ou acima).
            decision, reason = Decision.WAIT, "Classe sem aporte (no alvo ou acima)."
        elif amounts.get(c.ticker, ZERO) > 0:
            # Recebeu parte do aporte, mas ela não paga um lote inteiro.
            decision, reason = Decision.TOO_EXPENSIVE, "Valor não paga 1 lote."
        elif deficits.get(c.ticker, ZERO) > 0:
            # Abaixo do ideal, mas outros estão ainda mais abaixo: o aporte não chegou aqui.
            decision, reason = Decision.WAIT, "Outros mais abaixo do ideal."
        else:
            decision, reason = Decision.WAIT, "Já no peso ideal ou acima."
        checklist_pct = c.checklist_score * 100 if c.checklist_score is not None else None
        decisions.append(
            AssetDecision(
                ticker=c.ticker,
                quant_score=quant.get(c.ticker),
                checklist_score=checklist_pct,
                final_score=scores.get(c.ticker),
                ideal_weight=weights.get(c.ticker, 0.0),
                current_value=c.current_value,
                target_value=targets.get(c.ticker, ZERO),
                quantity=quantities.get(c.ticker, ZERO),
                amount=spent.get(c.ticker, ZERO),
                decision=decision,
                reason=reason,
                price=c.price,
            )
        )
    decisions.sort(key=lambda d: (d.amount, d.final_score or -1.0), reverse=True)
    return ClassDecision(asset_class, budget, decisions, leftover, uses_checklist)


def _ideal_weights(
    eligible: Sequence[Candidate], scores: dict[Ticker, float], uses_checklist: bool
) -> dict[Ticker, float]:
    if not eligible:
        return {}
    if uses_checklist:
        basis = {c.ticker: scores[c.ticker] for c in eligible}
    else:
        basis = {c.ticker: float(c.current_value) for c in eligible}
    total = sum(basis.values())
    if total <= 0:
        # Ninguém pontuou (ou classe sem posições): divide igualmente.
        return {c.ticker: 1 / len(eligible) for c in eligible}
    return {ticker: value / total for ticker, value in basis.items()}


def _to_lots(
    eligible: Sequence[Candidate],
    amounts: dict[Ticker, Decimal],
    targets: dict[Ticker, Decimal],
    budget: Decimal,
) -> tuple[dict[Ticker, Decimal], dict[Ticker, Decimal]]:
    """Converte valores em lotes inteiros e reaproveita o troco."""
    by_ticker = {c.ticker: c for c in eligible}
    quantities: dict[Ticker, Decimal] = {}
    spent: dict[Ticker, Decimal] = {}
    for ticker, amount in amounts.items():
        candidate = by_ticker[ticker]
        price = candidate.price or ZERO
        step = lot_size(ticker, candidate.asset_class)
        lots = (amount / price / step).to_integral_value(rounding=ROUND_DOWN)
        quantities[ticker] = lots * step
        spent[ticker] = quantities[ticker] * price

    # Troco: um lote por vez para quem está mais longe do alvo, se couber.
    leftover = budget - sum(spent.values(), ZERO)
    while True:
        options = [
            c
            for c in eligible
            if c.price
            and lot_size(c.ticker, c.asset_class) * c.price <= leftover
            and targets[c.ticker] - c.current_value - spent.get(c.ticker, ZERO) > 0
        ]
        if not options:
            break
        best = max(
            options, key=lambda c: targets[c.ticker] - c.current_value - spent.get(c.ticker, ZERO)
        )
        price = best.price or ZERO
        step = lot_size(best.ticker, best.asset_class)
        quantities[best.ticker] = quantities.get(best.ticker, ZERO) + step
        spent[best.ticker] = spent.get(best.ticker, ZERO) + step * price
        leftover -= step * price
    return quantities, spent


_SPENDABLE = {Decision.BUY, Decision.WAIT, Decision.TOO_EXPENSIVE}


def spend_leftover(
    classes: Sequence[ClassDecision],
    class_gaps: dict[AssetClass, Decimal],
    leftover: Decimal,
) -> tuple[list[ClassDecision], Decimal]:
    """Usa o troco de todas as classes onde ainda falta percentual.

    Cada classe arredonda o próprio aporte para lotes e sobra um troco. Somados, esses
    trocos ainda compram lotes, mas só em classes abaixo do valor alvo (`class_gaps`
    > 0): uma classe acima do alvo nunca recebe, nem pelo troco.

    A cada passo escolhe a classe mais longe do alvo e, nela, o ativo de maior nota
    entre os que ainda estão abaixo do peso ideal (se nenhum estiver, o de maior nota).
    Lotes inteiros (B3) entram um por vez, para não concentrar; ativos fracionários
    (CDI, Tesouro, cripto) recebem de uma vez o que couber no troco e na falta da classe.

    Returns:
        Classes com as compras extras e o troco final (menor que qualquer lote possível).
    """
    gaps = dict(class_gaps)
    result = list(classes)
    while leftover > 0:
        best: tuple[int, int, AssetDecision, Decimal] | None = None
        for ci, cls in enumerate(result):
            if gaps.get(cls.asset_class, ZERO) <= 0:
                continue
            for di, d in enumerate(cls.decisions):
                if d.decision not in _SPENDABLE or not d.price:
                    continue
                lot_cost = lot_size(d.ticker, cls.asset_class) * d.price
                if lot_cost > leftover:
                    continue
                key = (gaps[cls.asset_class], d.gap > 0, d.final_score or 0.0)
                if best is None or key > (
                    gaps[result[best[0]].asset_class],
                    best[2].gap > 0,
                    best[2].final_score or 0.0,
                ):
                    best = (ci, di, d, lot_cost)
        if best is None:
            break
        ci, di, d, lot_cost = best
        cls = result[ci]
        step = lot_size(d.ticker, cls.asset_class)
        if step < 1:
            # Fracionário: o que couber no troco e na falta da classe, de uma vez.
            room = min(leftover, gaps[cls.asset_class])
            lots = max((room / lot_cost).to_integral_value(rounding=ROUND_DOWN), Decimal(1))
        else:
            lots = Decimal(1)
        cost = lots * lot_cost
        updated = replace(
            d,
            quantity=d.quantity + lots * step,
            amount=d.amount + cost,
            decision=Decision.BUY,
            reason="",
        )
        decisions = list(cls.decisions)
        decisions[di] = updated
        result[ci] = replace(cls, decisions=decisions, leftover=cls.leftover)
        gaps[cls.asset_class] = gaps[cls.asset_class] - cost
        leftover -= cost
    return result, leftover
