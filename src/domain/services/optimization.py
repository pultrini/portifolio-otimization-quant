"""Otimização de carteira: Markowitz (fronteira eficiente) e Risk Parity.

Entradas e saídas em numpy; otimização numérica com scipy. Sem I/O.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import Bounds, LinearConstraint, minimize

from domain.exceptions import DomainError
from domain.value_objects.price_history import PriceHistory

FloatArray = NDArray[np.float64]

# Pesos abaixo disso são ruído numérico do otimizador e viram zero.
_WEIGHT_EPSILON = 1e-6


@dataclass(frozen=True, slots=True, eq=False)
class AssetUniverse:
    """Retornos esperados e covariâncias anualizados de um conjunto de ativos.

    Attributes:
        tickers: Ativos, na ordem das linhas/colunas.
        expected_returns: μ anual de cada ativo.
        covariance: Σ anual (simétrica, semidefinida positiva).
    """

    tickers: tuple[str, ...]
    expected_returns: FloatArray
    covariance: FloatArray

    def __post_init__(self) -> None:
        n = len(self.tickers)
        if n == 0:
            raise DomainError("Otimização precisa de ao menos um ativo.")
        if self.expected_returns.shape != (n,) or self.covariance.shape != (n, n):
            raise DomainError("Dimensões de retornos e covariância não batem com os ativos.")

    @classmethod
    def from_history(cls, history: PriceHistory, periods_per_year: int) -> AssetUniverse:
        """Estima μ e Σ a partir de preços históricos.

        Fórmulas (r = retornos simples por período):
            μ_anual = média(r) x periodos_por_ano
            Σ_anual = cov_amostral(r) x periodos_por_ano

        Média histórica é um estimador ruidoso do retorno futuro; o resultado deve ser
        lido como "o que teria sido ótimo no período", não como previsão.
        """
        returns = history.simple_returns()
        if returns.shape[0] < 2:
            raise DomainError("Histórico curto demais para estimar retornos e covariância.")
        covariance = np.atleast_2d(np.cov(returns, rowvar=False, ddof=1)) * periods_per_year
        return cls(
            tickers=history.tickers,
            expected_returns=returns.mean(axis=0) * periods_per_year,
            covariance=covariance,
        )

    @property
    def volatilities(self) -> FloatArray:
        return np.sqrt(np.clip(np.diag(self.covariance), 0.0, None))

    def correlation(self) -> FloatArray:
        """Matriz de correlação; ativos sem variância têm correlação 0 com os demais."""
        vol = self.volatilities
        outer = np.outer(vol, vol)
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = np.where(outer > 0, self.covariance / outer, 0.0)
        np.fill_diagonal(corr, 1.0)
        return corr


@dataclass(frozen=True, slots=True, eq=False)
class PortfolioPoint:
    """Uma carteira: pesos e seu par risco x retorno anual."""

    weights: FloatArray
    expected_return: float
    volatility: float
    sharpe: float | None


def evaluate(universe: AssetUniverse, weights: FloatArray, risk_free: float) -> PortfolioPoint:
    """Retorno e risco de uma carteira.

    Fórmulas: μ_p = w·μ ; σ_p = sqrt(wᵀ Σ w) ; Sharpe = (μ_p - rf) / σ_p
    """
    w = np.asarray(weights, dtype=np.float64)
    w = np.where(np.abs(w) < _WEIGHT_EPSILON, 0.0, w)
    expected = float(w @ universe.expected_returns)
    volatility = math.sqrt(max(float(w @ universe.covariance @ w), 0.0))
    sharpe = (expected - risk_free) / volatility if volatility > 0 else None
    return PortfolioPoint(w, expected, volatility, sharpe)


def _bounds(n: int, allow_short: bool) -> Bounds:
    # Sem venda a descoberto: 0 <= w_i <= 1. Com short, limita a ±1 por ativo.
    return Bounds(-1.0 if allow_short else 0.0, 1.0)


def _budget(n: int) -> LinearConstraint:
    return LinearConstraint(np.ones((1, n)), 1.0, 1.0)  # Σ w = 1


def _solve(
    objective: Callable[[FloatArray], float],
    universe: AssetUniverse,
    allow_short: bool,
    extra: list[LinearConstraint] | None = None,
) -> FloatArray:
    """Minimiza `objective` sob Σ w = 1, limites de peso e restrições extras (SLSQP)."""
    n = len(universe.tickers)
    start = np.full(n, 1.0 / n)
    result = minimize(
        objective,
        start,
        method="SLSQP",
        bounds=_bounds(n, allow_short),
        constraints=[_budget(n), *(extra or [])],
        options={"maxiter": 500, "ftol": 1e-12},
    )
    if not result.success:
        raise DomainError(f"Otimização não convergiu: {result.message}")
    weights: FloatArray = np.asarray(result.x, dtype=np.float64)
    return weights


def min_variance(
    universe: AssetUniverse, risk_free: float, allow_short: bool = False
) -> PortfolioPoint:
    """Carteira de mínima variância: min wᵀ Σ w sujeito a Σ w = 1."""
    weights = _solve(lambda w: float(w @ universe.covariance @ w), universe, allow_short)
    return evaluate(universe, weights, risk_free)


def max_sharpe(
    universe: AssetUniverse, risk_free: float, allow_short: bool = False
) -> PortfolioPoint:
    """Carteira tangente: max (w·μ - rf) / sqrt(wᵀ Σ w) sujeito a Σ w = 1."""

    def negative_sharpe(w: FloatArray) -> float:
        volatility = math.sqrt(max(float(w @ universe.covariance @ w), 1e-18))
        return -(float(w @ universe.expected_returns) - risk_free) / volatility

    weights = _solve(negative_sharpe, universe, allow_short)
    return evaluate(universe, weights, risk_free)


def efficient_frontier(
    universe: AssetUniverse, risk_free: float, points: int = 25, allow_short: bool = False
) -> list[PortfolioPoint]:
    """Fronteira eficiente de Markowitz.

    Para cada retorno alvo entre o da mínima variância e o maior retorno atingível,
    resolve: min wᵀ Σ w sujeito a Σ w = 1 e w·μ = alvo. Só a parte superior da
    curva (eficiente) é devolvida.
    """
    if points < 2:
        raise DomainError("A fronteira precisa de ao menos 2 pontos.")
    low = min_variance(universe, risk_free, allow_short).expected_return
    high = float(universe.expected_returns.max())
    if high <= low:
        return [min_variance(universe, risk_free, allow_short)]
    frontier: list[PortfolioPoint] = []
    for target in np.linspace(low, high, points):
        target_constraint = LinearConstraint(
            universe.expected_returns.reshape(1, -1), target, target
        )
        try:
            weights = _solve(
                lambda w: float(w @ universe.covariance @ w),
                universe,
                allow_short,
                [target_constraint],
            )
        except DomainError:
            # Alvo inviável por arredondamento no extremo: ignora o ponto.
            continue
        frontier.append(evaluate(universe, weights, risk_free))
    return frontier


def risk_contributions(universe: AssetUniverse, weights: FloatArray) -> FloatArray:
    """Contribuição de cada ativo para o risco total (frações que somam 1).

    Fórmula: RC_i = w_i x (Σ w)_i / (wᵀ Σ w)
    """
    marginal = universe.covariance @ weights
    total = float(weights @ marginal)
    if total <= 0:
        raise DomainError("Carteira sem risco: contribuições indefinidas.")
    contributions: FloatArray = weights * marginal / total
    return contributions


# Critério de parada da descida por coordenadas: variação máxima relativa de y.
_RISK_PARITY_TOLERANCE = 1e-12
_RISK_PARITY_MAX_SWEEPS = 10_000


def risk_parity(universe: AssetUniverse, risk_free: float) -> PortfolioPoint:
    """Carteira de paridade de risco (cada ativo contribui igualmente para o risco).

    Formulação convexa (Spinu, 2013): min ½ yᵀ Σ y - (1/n) Σ ln y_i, com y > 0.
    No ótimo, y_i (Σ y)_i = 1/n para todo i, isto é, contribuições iguais; os pesos
    são y normalizado (w = y / Σ y). A convexidade garante solução única.

    Resolve por descida por coordenadas cíclica (Griveau-Billion et al., 2013): fixando
    os outros ativos, a condição de ótimo para y_i é a quadrática
        Σ_ii y_i² + b_i y_i - 1/n = 0,  com b_i = Σ_{j≠i} Σ_ij y_j,
    cuja raiz positiva é y_i = (-b_i + sqrt(b_i² + 4 Σ_ii / n)) / (2 Σ_ii).
    Cada passo tem fórmula fechada, então o método é determinístico e sempre converge
    para covariância positiva definida.

    Ativos com variância quase zero (CDI) recebem peso enorme, porque contribuem
    pouquíssimo para o risco: é o resultado correto, mas costuma ser útil rodar sem
    a renda fixa.
    """
    n = len(universe.tickers)
    if np.any(universe.volatilities <= 0):
        raise DomainError("Risk Parity exige que todos os ativos tenham volatilidade.")
    covariance = universe.covariance
    diagonal = np.diag(covariance)
    budget = 1.0 / n
    y = 1.0 / universe.volatilities  # chute inicial: inverso da volatilidade

    for _ in range(_RISK_PARITY_MAX_SWEEPS):
        previous = y.copy()
        for i in range(n):
            b = float(covariance[i] @ y - diagonal[i] * y[i])
            y[i] = (-b + math.sqrt(b * b + 4.0 * diagonal[i] * budget)) / (2.0 * diagonal[i])
        if np.max(np.abs(y - previous) / previous) < _RISK_PARITY_TOLERANCE:
            break
    else:
        raise DomainError("Risk Parity não convergiu.")
    return evaluate(universe, y / y.sum(), risk_free)
