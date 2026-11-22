"""Testes de otimização com soluções analíticas conhecidas.

Dois ativos não correlacionados, σ1 = 10% e σ2 = 20%:
    mínima variância: w1 = σ2² / (σ1² + σ2²) = 0.04 / 0.05 = 0.8
    risk parity: w_i ∝ 1/σ_i -> w1 = 10 / (10 + 5) = 2/3
    máximo Sharpe com μ = [10%, 15%], rf = 5%: w ∝ Σ⁻¹(μ - rf) = [5, 2.5] -> [2/3, 1/3]
"""

from datetime import date, timedelta

import numpy as np
import pytest

from domain.exceptions import DomainError
from domain.services.optimization import (
    AssetUniverse,
    efficient_frontier,
    evaluate,
    max_sharpe,
    min_variance,
    risk_contributions,
    risk_parity,
)
from domain.value_objects.price_history import PriceHistory

UNIVERSE = AssetUniverse(
    tickers=("A", "B"),
    expected_returns=np.array([0.10, 0.15]),
    covariance=np.diag([0.01, 0.04]),
)
RF = 0.05


def test_minima_variancia() -> None:
    point = min_variance(UNIVERSE, RF)
    assert point.weights == pytest.approx([0.8, 0.2], abs=1e-5)
    # σ_p² = 0.64 x 0.01 + 0.04 x 0.04 = 0.008
    assert point.volatility == pytest.approx(0.008**0.5, abs=1e-6)


def test_maximo_sharpe() -> None:
    point = max_sharpe(UNIVERSE, RF)
    assert point.weights == pytest.approx([2 / 3, 1 / 3], abs=1e-4)
    # Para não correlacionados, Sharpe² da tangente = Σ (excesso_i / σ_i)² = 0.25 + 0.25.
    assert point.sharpe == pytest.approx(0.5**0.5, abs=1e-5)


def test_risk_parity_iguala_contribuicoes() -> None:
    point = risk_parity(UNIVERSE, RF)
    assert point.weights == pytest.approx([2 / 3, 1 / 3], abs=1e-6)
    assert risk_contributions(UNIVERSE, point.weights) == pytest.approx([0.5, 0.5], abs=1e-6)


def test_risk_parity_com_correlacao() -> None:
    cov = np.array([[0.04, 0.006, 0.0], [0.006, 0.09, 0.01], [0.0, 0.01, 0.0225]])
    universe = AssetUniverse(("A", "B", "C"), np.array([0.1, 0.12, 0.08]), cov)
    point = risk_parity(universe, RF)
    assert point.weights.sum() == pytest.approx(1.0)
    assert risk_contributions(universe, point.weights) == pytest.approx([1 / 3] * 3, abs=1e-6)


def test_sem_venda_a_descoberto_zera_ativo_ruim() -> None:
    universe = AssetUniverse(
        ("A", "B"), np.array([0.10, -0.20]), np.array([[0.02, 0.0], [0.0, 0.02]])
    )
    point = max_sharpe(universe, RF)
    assert point.weights == pytest.approx([1.0, 0.0], abs=1e-6)
    assert (point.weights >= 0).all()


def test_fronteira_eficiente_e_crescente() -> None:
    frontier = efficient_frontier(UNIVERSE, RF, points=10)
    assert len(frontier) == 10
    returns = [p.expected_return for p in frontier]
    vols = [p.volatility for p in frontier]
    assert returns == sorted(returns)
    assert vols == sorted(vols)
    assert frontier[0].weights == pytest.approx([0.8, 0.2], abs=1e-4)
    assert frontier[-1].weights == pytest.approx([0.0, 1.0], abs=1e-4)
    for point in frontier:
        assert point.weights.sum() == pytest.approx(1.0)


def test_universo_a_partir_do_historico() -> None:
    dates = tuple(date(2026, 1, 1) + timedelta(days=i) for i in range(4))
    prices = np.array([[10.0, 20.0], [11.0, 20.0], [11.0, 22.0], [12.1, 22.0]])
    universe = AssetUniverse.from_history(PriceHistory(dates, ("A", "B"), prices), 252)
    returns = np.array([[0.1, 0.0], [0.0, 0.1], [0.1, 0.0]])
    assert universe.expected_returns == pytest.approx(returns.mean(axis=0) * 252)
    assert universe.covariance == pytest.approx(np.cov(returns, rowvar=False) * 252)
    assert universe.correlation()[0, 1] == pytest.approx(-1.0)


def test_avaliacao_e_sharpe_sem_risco() -> None:
    riskless = AssetUniverse(("CDI",), np.array([0.13]), np.array([[0.0]]))
    point = evaluate(riskless, np.array([1.0]), 0.13)
    assert point.volatility == 0.0
    assert point.sharpe is None


def test_risk_parity_exige_volatilidade() -> None:
    universe = AssetUniverse(("A", "CDI"), np.array([0.1, 0.13]), np.diag([0.04, 0.0]))
    with pytest.raises(DomainError):
        risk_parity(universe, RF)


def test_dimensoes_invalidas() -> None:
    with pytest.raises(DomainError):
        AssetUniverse(("A",), np.array([0.1, 0.2]), np.eye(2))


# --- Otimização com teto por ativo e peso fixo por grupo (simulação quant) ---------------

TWO = AssetUniverse(("A", "B"), np.array([0.10, 0.15]), np.diag([0.01, 0.04]))
THREE = AssetUniverse(("A", "B", "C"), np.array([0.10, 0.15, 0.12]), np.diag([0.01, 0.04, 0.0225]))


def test_sem_restricoes_extras_reproduz_markowitz() -> None:
    from domain.services.optimization import optimize_constrained

    sharpe = optimize_constrained(TWO, 0.05)
    assert sharpe.weights == pytest.approx([2 / 3, 1 / 3], abs=1e-4)
    variance = optimize_constrained(TWO, 0.05, objective="min_variance")
    assert variance.weights == pytest.approx([0.8, 0.2], abs=1e-4)


def test_teto_por_ativo_limita_concentracao() -> None:
    from domain.services.optimization import optimize_constrained

    # Mínima variância queria 80% em A; com teto de 60% o resto vai para B.
    point = optimize_constrained(TWO, 0.05, objective="min_variance", max_weight=0.6)
    assert point.weights == pytest.approx([0.6, 0.4], abs=1e-4)
    # Teto inviável (2 x 30% < 100%) é relaxado para 1/n = 50%.
    relaxed = optimize_constrained(TWO, 0.05, max_weight=0.3)
    assert relaxed.weights == pytest.approx([0.5, 0.5], abs=1e-4)


def test_grupos_fixam_o_peso_de_cada_classe() -> None:
    from domain.services.optimization import optimize_constrained

    # X = {A, B} com 70%, Y = {C} com 30%. Sem correlação, a mínima variância dentro
    # de X divide 0,7 na proporção 1/σ² (80/20): A 56%, B 14%.
    point = optimize_constrained(
        THREE,
        0.05,
        objective="min_variance",
        groups=["X", "X", "Y"],
        group_targets={"X": 0.7, "Y": 0.3},
    )
    assert point.weights == pytest.approx([0.56, 0.14, 0.30], abs=1e-4)
    # Teto de 10% é inviável: dentro de X vira 35% (0,7 / 2) e em Y vira 30%.
    capped = optimize_constrained(
        THREE,
        0.05,
        max_weight=0.1,
        groups=["X", "X", "Y"],
        group_targets={"X": 0.7, "Y": 0.3},
    )
    assert capped.weights == pytest.approx([0.35, 0.35, 0.30], abs=1e-4)


def test_restricoes_invalidas() -> None:
    from domain.services.optimization import optimize_constrained

    with pytest.raises(DomainError):
        optimize_constrained(TWO, 0.05, objective="max_return")
    with pytest.raises(DomainError):
        optimize_constrained(TWO, 0.05, max_weight=0)
    with pytest.raises(DomainError):
        optimize_constrained(TWO, 0.05, groups=["X", "Y"], group_targets={"X": 1.0})
    with pytest.raises(DomainError):
        optimize_constrained(TWO, 0.05, groups=["X", "Y"], group_targets={"X": 0.5, "Y": 0.4})


def test_curva_de_crescimento_com_pesos_constantes() -> None:
    from domain.services.optimization import growth_curve

    returns = np.array([[0.10, 0.0], [-0.10, 0.10]])
    # 1 x (1 + 0,05) = 1,05; 1,05 x (1 + 0) = 1,05.
    assert growth_curve(returns, np.array([0.5, 0.5])) == pytest.approx([1.0, 1.05, 1.05])
