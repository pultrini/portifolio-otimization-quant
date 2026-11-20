"""Curva de patrimônio e gráfico underwater (drawdown)."""

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from application.dtos.metrics import ScopeReport
from presentation.charts.theme import BENCHMARK_COLOR, PORTFOLIO_COLOR, base_layout


def equity_and_underwater(scope: ScopeReport) -> go.Figure:
    """Dois painéis com o mesmo eixo de datas (nunca dois eixos y no mesmo painel):

    - em cima, patrimônio normalizado (base 100) do escopo e do benchmark;
    - embaixo, drawdown do escopo (queda em relação ao pico anterior).
    """
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.68, 0.32],
        vertical_spacing=0.06,
    )
    fig.add_trace(
        go.Scatter(
            x=scope.equity.dates,
            y=[v * 100 for v in scope.equity.values],
            name=scope.label,
            line={"color": PORTFOLIO_COLOR, "width": 2},
            hovertemplate="%{y:.2f}",
        ),
        row=1,
        col=1,
    )
    if scope.benchmark_equity.dates:
        fig.add_trace(
            go.Scatter(
                x=scope.benchmark_equity.dates,
                y=[v * 100 for v in scope.benchmark_equity.values],
                name=f"Benchmark ({scope.benchmark})",
                line={"color": BENCHMARK_COLOR, "width": 2},
                hovertemplate="%{y:.2f}",
            ),
            row=1,
            col=1,
        )
    fig.add_trace(
        go.Scatter(
            x=scope.drawdown.dates,
            y=scope.drawdown.values,
            name="Drawdown",
            fill="tozeroy",
            line={"color": PORTFOLIO_COLOR, "width": 1},
            fillcolor="rgba(42, 120, 214, 0.25)",
            hovertemplate="%{y:.2%}",
            showlegend=False,
        ),
        row=2,
        col=1,
    )
    fig = base_layout(fig, height=480)
    # Datas no formato brasileiro (o Plotly usa meses em inglês por padrão).
    fig.update_xaxes(tickformat="%m/%Y", hoverformat="%d/%m/%Y")
    fig.update_yaxes(title="Base 100", row=1, col=1)
    fig.update_yaxes(title="Drawdown", tickformat=".0%", row=2, col=1)
    return fig
