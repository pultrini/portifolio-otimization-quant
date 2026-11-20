"""Paleta e layout comuns dos gráficos (paleta de referência validada).

Cores seguem a entidade, nunca a posição: cada classe de ativo tem sempre a mesma cor,
a carteira é sempre azul e o benchmark sempre laranja. A paleta foi checada com o
validador de daltonismo (CVD); as três cores com contraste abaixo de 3:1 (aqua,
amarelo, magenta) sempre aparecem com rótulo direto ou tabela ao lado.
"""

import plotly.graph_objects as go

from domain.value_objects.asset_class import AssetClass

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
MAGENTA = "#e87ba4"
RED = "#e34948"
NEUTRAL = "#8a8984"
MUTED_GRID = "rgba(128, 128, 128, 0.18)"

PORTFOLIO_COLOR = BLUE
BENCHMARK_COLOR = ORANGE
OPTIMIZED_COLOR = AQUA

# Ordem fixa por classe (mesma ordem do enum): a cor não muda se uma classe some.
ASSET_CLASS_COLORS: dict[AssetClass, str] = {
    AssetClass.BR_EQUITY: BLUE,
    AssetClass.INTL_EQUITY: ORANGE,
    AssetClass.BR_FIXED_INCOME: AQUA,
    AssetClass.INTL_FIXED_INCOME: YELLOW,
    AssetClass.CRYPTO: MAGENTA,
}

# Divergente azul <-> vermelho com cinza neutro no meio (correlação -1..1).
DIVERGING = [[0.0, RED], [0.5, "#f0efec"], [1.0, BLUE]]


def base_layout(fig: go.Figure, height: int = 420) -> go.Figure:
    """Layout recessivo: grade leve, legenda em cima, separadores brasileiros."""
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 40, "b": 8},
        # Plotly usa o 1º caractere como decimal e o 2º como milhar: 1.234,56.
        separators=",.",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor=MUTED_GRID, zeroline=False)
    return fig
