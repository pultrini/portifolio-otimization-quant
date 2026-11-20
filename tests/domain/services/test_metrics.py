"""Testes das métricas com valores calculados à mão.

Série base: r = [0.10, -0.05, 0.02, -0.10]
    curva: 1 -> 1.1 -> 1.045 -> 1.0659 -> 0.95931
    acumulado: 0.95931 - 1 = -0.04069
    média: -0.0075; desvios: 0.1075, -0.0425, 0.0275, -0.0925
    soma dos quadrados: 0.022675 -> desvio amostral sqrt(0.022675 / 3)
    pico 1.1 e vale 0.95931 -> MDD = 0.95931 / 1.1 - 1 = -0.12790
"""

import math
from decimal import Decimal

import numpy as np
import pytest
from scipy.stats import norm

from domain.services import metrics as m

R = np.array([0.10, -0.05, 0.02, -0.10])
ZERO_RF = np.zeros(4)
STD = math.sqrt(0.022675 / 3)
MDD = 0.95931 / 1.1 - 1


class TestRetorno:
    def test_acumulado(self) -> None:
        assert m.cumulative_return(R) == pytest.approx(-0.04069)

    def test_cagr(self) -> None:
        # 4 períodos com 4 períodos por ano = 1 ano: CAGR = acumulado.
        assert m.cagr(R, 4) == pytest.approx(-0.04069)
        # 2 períodos de +10% com 1 período por ano: (1.21)^(1/2) - 1 = 10%.
        assert m.cagr([0.1, 0.1], 1) == pytest.approx(0.10)

    def test_perda_total(self) -> None:
        assert m.cagr([-1.0], 252) == -1.0

    def test_retorno_medio(self) -> None:
        assert m.mean_return([0.02, 0.04]) == pytest.approx(0.03)


class TestRisco:
    def test_volatilidade(self) -> None:
        assert m.annualized_volatility(R, 1) == pytest.approx(STD)
        assert m.annualized_volatility(R, 252) == pytest.approx(STD * math.sqrt(252))

    def test_volatilidade_zero_e_valida(self) -> None:
        assert m.annualized_volatility([0.01, 0.01], 252) == 0.0

    def test_max_drawdown(self) -> None:
        assert m.max_drawdown(R) == pytest.approx(MDD)
        assert m.max_drawdown([0.01, 0.02]) == 0.0

    def test_drawdown_conta_perda_no_primeiro_periodo(self) -> None:
        assert m.max_drawdown([-0.2, 0.1]) == pytest.approx(-0.2)

    def test_var_e_cvar_historicos(self) -> None:
        # Ordenado: [-0.10, -0.05, 0.02, 0.10]; quantil 25% "lower" = -0.10.
        assert m.historical_var(R, 0.75) == pytest.approx(0.10)
        assert m.historical_cvar(R, 0.75) == pytest.approx(0.10)
        # Quantil 50% "lower" = -0.05; piores cenários: -0.10 e -0.05.
        assert m.historical_var(R, 0.50) == pytest.approx(0.05)
        assert m.historical_cvar(R, 0.50) == pytest.approx(0.075)

    def test_var_parametrico(self) -> None:
        z = norm.ppf(0.05)
        assert m.parametric_var(R, 0.95) == pytest.approx(-(-0.0075 + z * STD))
        expected_cvar = -(-0.0075 - STD * norm.pdf(z) / 0.05)
        assert m.parametric_cvar(R, 0.95) == pytest.approx(expected_cvar)

    def test_sem_perda_devolve_none(self) -> None:
        gains = [0.01, 0.02, 0.03]
        assert m.historical_var(gains, 0.95) is None
        assert m.historical_cvar(gains, 0.95) is None


class TestRiscoRetorno:
    def test_sharpe(self) -> None:
        assert m.sharpe_ratio(R, ZERO_RF, 1) == pytest.approx(-0.0075 / STD)

    def test_sharpe_desconta_taxa_livre_de_risco(self) -> None:
        rf = np.full(4, 0.01)
        assert m.sharpe_ratio(R, rf, 1) == pytest.approx(-0.0175 / STD)

    def test_sortino(self) -> None:
        # Downside: sqrt((0.05² + 0.10²) / 4) = sqrt(0.003125)
        assert m.sortino_ratio(R, ZERO_RF, 1) == pytest.approx(-0.0075 / math.sqrt(0.003125))

    def test_calmar(self) -> None:
        assert m.calmar_ratio(R, 4) == pytest.approx(-0.04069 / abs(MDD))

    def test_beta(self) -> None:
        assert m.beta(R, R) == pytest.approx(1.0)
        assert m.beta(R, 2 * R) == pytest.approx(0.5)
        assert m.beta(-R, R) == pytest.approx(-1.0)


class TestCasosDegenerados:
    @pytest.mark.parametrize(
        "call",
        [
            lambda: m.cumulative_return([]),
            lambda: m.cagr([], 252),
            lambda: m.annualized_volatility([0.1], 252),
            lambda: m.max_drawdown([]),
            lambda: m.historical_var([], 0.95),
            lambda: m.parametric_var([0.01, 0.01], 0.95),
            lambda: m.sharpe_ratio([0.01, 0.01], [0.0, 0.0], 252),
            lambda: m.sortino_ratio([0.01, 0.02], [0.0, 0.0], 252),
            lambda: m.calmar_ratio([0.01, 0.02], 252),
            lambda: m.beta([0.01, 0.02], [0.01, 0.01]),
        ],
    )
    def test_devolve_none(self, call: object) -> None:
        assert call() is None  # type: ignore[operator]

    def test_recusa_nan(self) -> None:
        with pytest.raises(ValueError):
            m.cumulative_return([0.1, float("nan")])

    def test_tamanhos_diferentes(self) -> None:
        with pytest.raises(ValueError):
            m.sharpe_ratio([0.1, 0.2], [0.0], 252)


class TestEstatisticasDeOperacoes:
    def test_valores_conhecidos(self) -> None:
        stats = m.trade_statistics([Decimal(v) for v in ("100", "-50", "0", "200", "-25")])
        assert stats.closed_trades == 5
        assert stats.win_rate == pytest.approx(0.4)
        assert stats.average_win == Decimal("150")
        assert stats.average_loss == Decimal("-37.5")
        assert stats.payoff_ratio == pytest.approx(4.0)
        assert stats.profit_factor == pytest.approx(4.0)
        assert stats.expectancy == Decimal("45")

    def test_sem_perdas(self) -> None:
        stats = m.trade_statistics([Decimal("10"), Decimal("20")])
        assert stats.win_rate == 1.0
        assert stats.payoff_ratio is None
        assert stats.profit_factor is None

    def test_sem_operacoes(self) -> None:
        stats = m.trade_statistics([])
        assert stats.closed_trades == 0
        assert stats.win_rate is None
        assert stats.expectancy is None
