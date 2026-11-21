"""Testes do planejamento e da constância dos objetivos de poupança."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from domain.entities.savings_goal import GoalDeposit, GoalFrequency, GoalMode, SavingsGoal
from domain.exceptions import DomainError
from domain.services.savings_plan import consistency, plan_goal, progressive_steps_for
from domain.value_objects.money import Money

D = Decimal
START = date(2026, 1, 1)


@pytest.mark.parametrize(
    ("target", "unit", "steps"),
    [
        ("40000", "1", 282),  # 282 x 283 / 2 = 39.903 (283 daria 40.186, mais longe)
        ("55", "1", 10),  # 1 + ... + 10 = 55 exato
        ("110", "2", 10),  # passo de R$ 2: 2 x 55 = 110
        ("1", "1", 1),
    ],
)
def test_passos_do_desafio_progressivo(target: str, unit: str, steps: int) -> None:
    assert progressive_steps_for(D(target), D(unit)) == steps


def test_plano_progressivo_de_40_mil_em_um_ano() -> None:
    goal = plan_goal(
        "Reserva",
        Money.brl("40000"),
        GoalMode.PROGRESSIVE,
        GoalFrequency.DAILY,
        START,
        START + timedelta(days=364),
    )
    assert goal.step_count == 282
    assert goal.total.amount == D("39903")
    assert goal.step_amount(1).amount == D("1")
    assert goal.step_amount(282).amount == D("282")
    assert goal.period_count == 365


def test_prazo_curto_demais() -> None:
    with pytest.raises(DomainError, match="282 depósitos para 100 dias"):
        plan_goal(
            "Reserva",
            Money.brl("40000"),
            GoalMode.PROGRESSIVE,
            GoalFrequency.DAILY,
            START,
            START + timedelta(days=99),
        )


def test_plano_fixo_semanal_arredonda_para_cima() -> None:
    # 52 semanas e 1 dia -> 53 períodos; 10.000 / 53 = 188,679... -> 188,68.
    goal = plan_goal(
        "Viagem",
        Money.brl("10000"),
        GoalMode.FIXED,
        GoalFrequency.WEEKLY,
        START,
        START + timedelta(days=364),
    )
    assert goal.step_count == 53
    assert goal.unit_amount.amount == D("188.68")
    assert goal.total.amount >= D("10000")


def _goal(steps: int = 10) -> SavingsGoal:
    return SavingsGoal(
        "Teste",
        GoalMode.PROGRESSIVE,
        GoalFrequency.DAILY,
        Money.brl("1"),
        steps,
        START,
        START + timedelta(days=19),
    )


def _dep(step: int, day: int) -> GoalDeposit:
    return GoalDeposit(step, Money.brl(str(step)), START + timedelta(days=day))


def test_constancia_e_sequencias() -> None:
    goal = _goal()
    # Depósitos nos dias 0, 1, 2 (sequência de 3), falha no 3, depois 4 e 5.
    deposits = [_dep(1, 0), _dep(5, 1), _dep(2, 2), _dep(3, 4), _dep(4, 5)]
    report = consistency(goal, deposits, START + timedelta(days=5))
    assert report.saved.amount == D("15")
    assert report.progress == pytest.approx(15 / 55)
    assert report.completed_steps == 5
    assert report.remaining_steps == 5
    assert report.elapsed_periods == 6
    assert report.active_periods == 5
    assert report.consistency_rate == pytest.approx(5 / 6)
    assert report.current_streak == 2
    assert report.longest_streak == 3
    # 20 dias de prazo, hoje é o 6º e já depositou: sobram 14 dias para 5 passos.
    assert report.remaining_periods == 14
    assert report.on_track
    assert report.next_step == 6


def test_dia_atual_sem_deposito_nao_quebra_a_sequencia() -> None:
    report = consistency(_goal(), [_dep(1, 0), _dep(2, 1)], START + timedelta(days=2))
    assert report.current_streak == 2
    # Hoje ainda pode depositar: 18 dias (incluindo hoje) para 8 passos.
    assert report.remaining_periods == 18


def test_fora_do_ritmo() -> None:
    goal = _goal(steps=10)
    report = consistency(goal, [], START + timedelta(days=15))
    # Sobram 5 dias para 10 passos.
    assert report.remaining_periods == 5
    assert not report.on_track
    assert report.required_per_period == pytest.approx(2.0)
    assert report.current_streak == 0
    assert report.consistency_rate == 0


def test_validacoes_da_entidade() -> None:
    with pytest.raises(DomainError):
        SavingsGoal("", GoalMode.FIXED, GoalFrequency.DAILY, Money.brl("1"), 1, START, START)
    with pytest.raises(DomainError):
        _goal().step_amount(11)
