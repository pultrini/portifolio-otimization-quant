"""Métricas de performance e risco (CLAUDE.md 5.5).

Todas as funções são puras: recebem arrays numpy de retornos simples por período e
devolvem `float` ou `None`. `None` é devolvido explicitamente nos casos degenerados
(série vazia ou curta demais, volatilidade zero, nenhuma perda); nunca `nan` ou `inf`.

Convenções:
    - `returns`: retornos simples por período, r_t = P_t / P_{t-1} - 1.
    - `periods_per_year`: 252 (B3 e exterior) ou 365 (cripto).
    - Perdas (VaR, CVaR) são reportadas como números POSITIVOS.
    - Drawdown é reportado como número negativo (-0.25 = queda de 25%).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.stats import norm

FloatArray = NDArray[np.float64]


def _as_array(values: ArrayLike) -> FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError("Série de retornos deve ser unidimensional.")
    if not np.isfinite(array).all():
        raise ValueError("Série de retornos contém nan ou infinito.")
    return array


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


# ======================================================================= Retorno


def cumulative_return(returns: ArrayLike) -> float | None:
    """Retorno acumulado composto.

    Fórmula: R = Π (1 + r_t) - 1
    """
    r = _as_array(returns)
    if r.size == 0:
        return None
    return float(np.prod(1.0 + r) - 1.0)


def cagr(returns: ArrayLike, periods_per_year: int) -> float | None:
    """Taxa de crescimento anual composta.

    Fórmula: CAGR = (1 + R)^(periodos_por_ano / n) - 1, com R o retorno acumulado e n
    o número de períodos.
    """
    r = _as_array(returns)
    total = cumulative_return(r)
    if total is None:
        return None
    growth = 1.0 + total
    if growth <= 0:
        # Perda total: o patrimônio chegou a zero.
        return -1.0
    return _finite_or_none(growth ** (periods_per_year / r.size) - 1.0)


def mean_return(values: ArrayLike) -> float | None:
    """Média aritmética (usada no retorno médio por operação)."""
    r = _as_array(values)
    return float(r.mean()) if r.size else None


# ========================================================================== Risco


def annualized_volatility(returns: ArrayLike, periods_per_year: int) -> float | None:
    """Volatilidade anualizada.

    Fórmula: σ_anual = desvio-padrão amostral(r) x sqrt(periodos_por_ano)
    Precisa de ao menos 2 observações (desvio amostral usa n - 1).
    """
    r = _as_array(returns)
    if r.size < 2:
        return None
    return float(r.std(ddof=1) * math.sqrt(periods_per_year))


def equity_curve(returns: ArrayLike) -> FloatArray:
    """Patrimônio normalizado começando em 1: [1, (1+r_1), (1+r_1)(1+r_2), ...]."""
    r = _as_array(returns)
    return np.concatenate(([1.0], np.cumprod(1.0 + r)))


def drawdown_series(returns: ArrayLike) -> FloatArray:
    """Queda em relação ao pico anterior em cada ponto da curva de patrimônio.

    Fórmula: DD_t = V_t / max(V_0..V_t) - 1   (<= 0)
    """
    curve = equity_curve(returns)
    return curve / np.maximum.accumulate(curve) - 1.0


def max_drawdown(returns: ArrayLike) -> float | None:
    """Maior queda pico-vale (número negativo; 0 se nunca caiu).

    A curva começa em 1, então uma perda já no primeiro período conta como drawdown.
    """
    r = _as_array(returns)
    if r.size == 0:
        return None
    return float(drawdown_series(r).min())


def historical_var(returns: ArrayLike, confidence: float) -> float | None:
    """Value at Risk histórico, como perda positiva.

    Fórmula: VaR_c = -Q_{1-c}(r), com Q o quantil empírico (método "lower": usa uma
    observação real, o que é conservador em amostras pequenas).
    Devolve None se não há perda nesse nível (quantil >= 0).
    """
    r = _as_array(returns)
    if r.size == 0:
        return None
    quantile = float(np.quantile(r, 1.0 - confidence, method="lower"))
    return -quantile if quantile < 0 else None


def historical_cvar(returns: ArrayLike, confidence: float) -> float | None:
    """Expected Shortfall (CVaR) histórico, como perda positiva.

    Fórmula: CVaR_c = -média(r | r <= Q_{1-c}(r)) — a perda média nos piores cenários.
    """
    r = _as_array(returns)
    if r.size == 0:
        return None
    quantile = float(np.quantile(r, 1.0 - confidence, method="lower"))
    if quantile >= 0:
        return None
    return float(-r[r <= quantile].mean())


def parametric_var(returns: ArrayLike, confidence: float) -> float | None:
    """VaR paramétrico (normal), como perda positiva.

    Fórmula: VaR_c = -(μ + z_{1-c} x σ), com z o quantil da normal padrão.
    """
    r = _as_array(returns)
    if r.size < 2:
        return None
    sigma = float(r.std(ddof=1))
    if sigma == 0:
        return None
    var = -(float(r.mean()) + float(norm.ppf(1.0 - confidence)) * sigma)
    return var if var > 0 else None


def parametric_cvar(returns: ArrayLike, confidence: float) -> float | None:
    """CVaR paramétrico (normal), como perda positiva.

    Fórmula: CVaR_c = -(μ - σ x φ(z_{1-c}) / (1 - c)), com φ a densidade normal.
    """
    r = _as_array(returns)
    if r.size < 2:
        return None
    sigma = float(r.std(ddof=1))
    if sigma == 0:
        return None
    z = float(norm.ppf(1.0 - confidence))
    cvar = -(float(r.mean()) - sigma * float(norm.pdf(z)) / (1.0 - confidence))
    return cvar if cvar > 0 else None


# ================================================================= Risco-retorno


def _excess(returns: ArrayLike, risk_free: ArrayLike) -> FloatArray:
    r = _as_array(returns)
    rf = _as_array(risk_free)
    if r.shape != rf.shape:
        raise ValueError("Retornos e taxa livre de risco precisam ter o mesmo tamanho.")
    return r - rf


def sharpe_ratio(returns: ArrayLike, risk_free: ArrayLike, periods_per_year: int) -> float | None:
    """Índice de Sharpe anualizado.

    Fórmula: Sharpe = média(r - rf) / desvio(r - rf) x sqrt(periodos_por_ano), com rf o
    retorno da taxa livre de risco no mesmo período (CDI ou T-Bill).
    """
    excess = _excess(returns, risk_free)
    if excess.size < 2:
        return None
    sigma = float(excess.std(ddof=1))
    if sigma == 0:
        return None
    return _finite_or_none(float(excess.mean()) / sigma * math.sqrt(periods_per_year))


def sortino_ratio(returns: ArrayLike, risk_free: ArrayLike, periods_per_year: int) -> float | None:
    """Índice de Sortino anualizado (downside em relação à taxa livre de risco).

    Fórmula: Sortino = média(r - rf) / DD x sqrt(periodos_por_ano), com
    DD = sqrt(média(min(r - rf, 0)^2)) sobre todas as observações.
    Sem nenhum período abaixo da taxa livre de risco, DD = 0 e devolve None.
    """
    excess = _excess(returns, risk_free)
    if excess.size < 2:
        return None
    downside = float(np.sqrt(np.mean(np.minimum(excess, 0.0) ** 2)))
    if downside == 0:
        return None
    return _finite_or_none(float(excess.mean()) / downside * math.sqrt(periods_per_year))


def calmar_ratio(returns: ArrayLike, periods_per_year: int) -> float | None:
    """Índice de Calmar.

    Fórmula: Calmar = CAGR / |MDD|. Sem drawdown (MDD = 0) devolve None.
    """
    growth = cagr(returns, periods_per_year)
    mdd = max_drawdown(returns)
    if growth is None or mdd is None or mdd == 0:
        return None
    return _finite_or_none(growth / abs(mdd))


def beta(returns: ArrayLike, benchmark_returns: ArrayLike) -> float | None:
    """Beta em relação ao benchmark da classe.

    Fórmula: β = cov(r, r_b) / var(r_b) (amostrais, n - 1).
    """
    r = _as_array(returns)
    b = _as_array(benchmark_returns)
    if r.shape != b.shape:
        raise ValueError("Retornos e benchmark precisam ter o mesmo tamanho.")
    if r.size < 2:
        return None
    variance = float(b.var(ddof=1))
    if variance == 0:
        return None
    covariance = float(np.cov(r, b, ddof=1)[0, 1])
    return _finite_or_none(covariance / variance)


# ==================================================== Eficiência operacional


@dataclass(frozen=True, slots=True)
class TradeStats:
    """Estatísticas de operações fechadas, líquidas de custos.

    Attributes:
        closed_trades: Quantidade de operações fechadas.
        win_rate: Fração de operações com lucro (0 a 1).
        payoff_ratio: Ganho médio / |perda média|.
        profit_factor: Soma dos ganhos / |soma das perdas|.
        expectancy: Resultado esperado por operação, em BRL.
        average_win: Ganho médio, em BRL.
        average_loss: Perda média (negativa), em BRL.
    """

    closed_trades: int
    win_rate: float | None
    payoff_ratio: float | None
    profit_factor: float | None
    expectancy: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None


def trade_statistics(pnls: Sequence[Decimal]) -> TradeStats:
    """Win rate, payoff, profit factor e expectativa matemática.

    Fórmulas (P&L líquido de custos por operação fechada):
        win_rate = ganhos / total
        payoff = média(ganhos) / |média(perdas)|
        profit_factor = Σ ganhos / |Σ perdas|
        expectativa = win_rate x média(ganhos) - (1 - win_rate) x |média(perdas)|
                    = média(P&L) quando não há operações no zero a zero
    Operações com resultado zero contam no total, mas não como ganho nem perda.
    Sem perdas, payoff e profit factor ficam None; sem operações, tudo None.
    """
    total = len(pnls)
    if total == 0:
        return TradeStats(0, None, None, None, None, None, None)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    zero = Decimal("0")
    average_win = sum(wins, zero) / len(wins) if wins else None
    average_loss = sum(losses, zero) / len(losses) if losses else None
    payoff = (
        float(average_win / abs(average_loss))
        if average_win is not None and average_loss is not None
        else None
    )
    profit_factor = float(sum(wins, zero) / abs(sum(losses, zero))) if losses else None
    return TradeStats(
        closed_trades=total,
        win_rate=len(wins) / total,
        payoff_ratio=payoff,
        profit_factor=profit_factor,
        expectancy=sum(pnls, zero) / total,
        average_win=average_win,
        average_loss=average_loss,
    )
