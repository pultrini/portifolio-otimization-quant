"""Gráficos de alocação: atual vs. alvo por classe de ativo."""

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from application.dtos.optimization import ContributionPlan
from presentation.charts.theme import ASSET_CLASS_COLORS, BLUE, RED, base_layout


def allocation_donuts(plan: ContributionPlan) -> go.Figure:
    """Duas roscas lado a lado: alocação atual e alvo, com as mesmas cores por classe.

    Rótulos diretos (classe e %) em cada fatia: a identidade não depende só da cor.
    """
    rows = [r for r in plan.rows if r.current_value > 0 or r.target_pct > 0]
    labels = [r.asset_class.label_pt for r in rows]
    colors = [ASSET_CLASS_COLORS[r.asset_class] for r in rows]
    fig = make_subplots(
        rows=1,
        cols=2,
        specs=[[{"type": "domain"}, {"type": "domain"}]],
        subplot_titles=("Atual", "Alvo"),
    )
    for col, values in (
        (1, [float(r.current_value) for r in rows]),
        (2, [r.target_pct for r in rows]),
    ):
        fig.add_trace(
            go.Pie(
                labels=labels,
                values=values,
                hole=0.6,
                sort=False,  # mantém a ordem fixa das classes
                marker={"colors": colors, "line": {"color": "white", "width": 2}},
                textinfo="percent",
                hovertemplate="%{label}<br>%{percent}<extra></extra>",
                showlegend=col == 1,
            ),
            row=1,
            col=col,
        )
    fig = base_layout(fig, height=380)
    # Legenda embaixo: em cima ela cobre o título "Atual" e encolhe a primeira rosca.
    fig.update_layout(
        hovermode="closest",
        legend={"orientation": "h", "yanchor": "top", "y": -0.05, "x": 0.5, "xanchor": "center"},
    )
    return fig


def allocation_delta_bars(plan: ContributionPlan) -> go.Figure:
    """Diferença alvo - atual por classe, em pontos percentuais.

    Azul = abaixo do alvo (falta comprar); vermelho = acima do alvo. Rótulo em cada barra.
    """
    rows = plan.rows
    deltas = [r.target_pct - r.current_pct for r in rows]
    fig = go.Figure(
        go.Bar(
            x=[r.asset_class.label_pt for r in rows],
            y=deltas,
            marker={"color": [BLUE if d >= 0 else RED for d in deltas], "cornerradius": 4},
            # Só o número troca ponto por vírgula; o "p.p." fica como está.
            text=[f"{d:+.2f}".replace(".", ",") + " p.p." for d in deltas],
            textposition="outside",
            hovertemplate="%{x}<br>%{y:+.2f} p.p.<extra></extra>",
        )
    )
    fig = base_layout(fig, height=320)
    fig.update_layout(hovermode="closest", showlegend=False)
    fig.update_yaxes(title="Alvo − atual (p.p.)", zeroline=True, zerolinecolor="#8a8984")
    return fig
