"""Cache das leituras pesadas da camada Gold (métricas e otimização).

`st.cache_data` guarda o resultado por argumentos. Parâmetros com `_` na frente não
entram na chave (o container não é "hasheável"); `user_id` entra para que o resultado
de um usuário nunca seja servido a outro.

O cache é invalidado por `invalidate()` sempre que os dados mudam: pipeline rodado,
posições importadas/editadas ou operação registrada.
"""

import streamlit as st

from application.dtos.metrics import MetricsReport, MetricsRequest
from application.dtos.optimization import OptimizationRequest, OptimizationResult
from presentation.container import Container

CACHE_TTL_SECONDS = 600


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def metrics_report(
    _container: Container,
    user_id: str,
    portfolio_id: str,
    lookback_years: int,
    include_parametric: bool,
) -> MetricsReport:
    del user_id  # só compõe a chave do cache
    return _container.calculate_metrics.execute(
        MetricsRequest(
            portfolio_id=portfolio_id,
            lookback_years=lookback_years,
            include_parametric=include_parametric,
        )
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def optimization_result(
    _container: Container,
    user_id: str,
    portfolio_id: str,
    lookback_years: int,
    include_fixed_income: bool,
) -> OptimizationResult:
    del user_id
    return _container.optimize_portfolio.execute(
        OptimizationRequest(
            portfolio_id=portfolio_id,
            lookback_years=lookback_years,
            include_fixed_income=include_fixed_income,
        )
    )


def invalidate() -> None:
    """Descarta resultados em cache depois de qualquer mudança nos dados."""
    st.cache_data.clear()
