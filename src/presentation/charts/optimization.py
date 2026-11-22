"""Dispersão risco x retorno com fronteira eficiente, e heatmap de correlação."""

import plotly.graph_objects as go

from application.dtos.optimization import (
    OptimizationResult,
    PortfolioPointDTO,
    QuantSimulationResult,
)
from presentation.charts.theme import (
    DIVERGING,
    NEUTRAL,
    OPTIMIZED_COLOR,
    PORTFOLIO_COLOR,
    base_layout,
)
from presentation.charts.theme import ORANGE as CURRENT_COLOR

_HOVER = "%{text}<br>Retorno: %{y:.2%}<br>Volatilidade: %{x:.2%}<extra></extra>"


def _highlight(
    point: PortfolioPointDTO,
    color: str,
    symbol: str,
    size: int = 14,
    labeled: bool = True,
) -> go.Scatter:
    return go.Scatter(
        x=[point.volatility],
        y=[point.expected_return],
        mode="markers+text" if labeled else "markers",
        name=point.label,
        text=[point.label],
        textposition="top center",
        # Anel na cor da superfície separa o marcador da linha da fronteira.
        marker={
            "color": color,
            "size": size,
            "symbol": symbol,
            "line": {"color": "white", "width": 2},
        },
        hovertemplate=_HOVER,
    )


def frontier_scatter(result: OptimizationResult) -> go.Figure:
    """Fronteira eficiente (linha), ativos individuais (cinza) e carteiras destacadas.

    Carteira atual (laranja) e máximo Sharpe (aqua) têm rótulo direto: são as duas que
    o gráfico destaca. Mínima variância e Risk Parity ficam em neutro, identificadas
    por símbolo (losango, quadrado), legenda e hover; sem rótulo, porque costumam cair
    perto da carteira atual e dos ativos de baixa volatilidade e os textos colidiriam.
    """
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[p.volatility for p in result.frontier],
            y=[p.expected_return for p in result.frontier],
            mode="lines",
            name="Fronteira eficiente",
            line={"color": PORTFOLIO_COLOR, "width": 2},
            hovertemplate="Retorno: %{y:.2%}<br>Volatilidade: %{x:.2%}<extra>Fronteira</extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[a.volatility for a in result.assets],
            y=[a.expected_return for a in result.assets],
            mode="markers+text",
            name="Ativos",
            text=[a.ticker for a in result.assets],
            textposition="bottom center",
            marker={"color": NEUTRAL, "size": 9},
            hovertemplate=_HOVER,
        )
    )
    fig.add_trace(_highlight(result.current, CURRENT_COLOR, "circle"))
    fig.add_trace(_highlight(result.max_sharpe, OPTIMIZED_COLOR, "star", 16))
    fig.add_trace(_highlight(result.min_variance, NEUTRAL, "diamond", labeled=False))
    if result.risk_parity is not None:
        fig.add_trace(_highlight(result.risk_parity, NEUTRAL, "square", labeled=False))
    fig = base_layout(fig, height=520)
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(title="Volatilidade anual", tickformat=".0%", showgrid=True)
    fig.update_yaxes(title="Retorno anual esperado", tickformat=".0%")
    return fig


def correlation_heatmap(result: OptimizationResult) -> go.Figure:
    """Correlação entre os ativos: azul = positiva, vermelho = negativa, cinza = zero."""
    tickers = result.tickers
    fig = go.Figure(
        go.Heatmap(
            z=result.correlation,
            x=tickers,
            y=tickers,
            zmin=-1,
            zmax=1,
            colorscale=DIVERGING,
            text=[[f"{v:.2f}".replace(".", ",") for v in row] for row in result.correlation],
            texttemplate="%{text}",
            hovertemplate="%{y} × %{x}<br>Correlação: %{z:.2f}<extra></extra>",
            xgap=2,
            ygap=2,
            colorbar={"title": "ρ"},
        )
    )
    fig = base_layout(fig, height=max(360, 40 * len(tickers) + 120))
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    return fig


def simulation_weights(result: QuantSimulationResult) -> go.Figure:
    """Peso de cada ativo: carteira atual (laranja) x carteira simulada (aqua).

    Barras horizontais lado a lado, do maior peso simulado para o menor, com o valor
    escrito na ponta de cada barra (leitura direta, sem depender só do hover).
    """
    rows = sorted(result.rows, key=lambda r: r.weight)
    tickers = [r.ticker for r in rows]
    fig = go.Figure()
    if result.current is not None:
        fig.add_trace(
            go.Bar(
                y=tickers,
                x=[r.current_weight for r in rows],
                name="Atual",
                orientation="h",
                marker={"color": CURRENT_COLOR},
                text=[f"{r.current_weight:.1%}".replace(".", ",") for r in rows],
                textposition="outside",
                hovertemplate="%{y}<br>Atual: %{x:.2%}<extra></extra>",
            )
        )
    fig.add_trace(
        go.Bar(
            y=tickers,
            x=[r.weight for r in rows],
            name="Simulada",
            orientation="h",
            marker={"color": OPTIMIZED_COLOR},
            text=[f"{r.weight:.1%}".replace(".", ",") for r in rows],
            textposition="outside",
            hovertemplate="%{y}<br>Simulada: %{x:.2%}<extra></extra>",
        )
    )
    fig = base_layout(fig, height=max(300, 46 * len(rows) + 100))
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08, hovermode="closest")
    top = max([r.weight for r in rows] + [r.current_weight for r in rows] + [0.01])
    fig.update_xaxes(tickformat=".0%", range=[0, top * 1.18], showgrid=True)
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)")
    return fig


def simulation_growth(result: QuantSimulationResult) -> go.Figure:
    """R$ 1 aplicado no início da janela: carteira simulada x atual (pesos constantes)."""
    fig = go.Figure()
    if result.current_growth is not None:
        fig.add_trace(
            go.Scatter(
                x=result.dates,
                y=result.current_growth,
                name="Atual",
                mode="lines",
                line={"color": CURRENT_COLOR, "width": 2},
                hovertemplate="R$ %{y:.3f}<extra>Atual</extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=result.dates,
            y=result.simulated_growth,
            name="Simulada",
            mode="lines",
            line={"color": OPTIMIZED_COLOR, "width": 2.5},
            hovertemplate="R$ %{y:.3f}<extra>Simulada</extra>",
        )
    )
    fig = base_layout(fig, height=360)
    fig.update_yaxes(title="Valor de R$ 1,00", tickprefix="R$ ")
    return fig
