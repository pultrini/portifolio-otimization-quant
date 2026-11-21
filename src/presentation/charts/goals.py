"""Gráficos de constância dos objetivos: calendário de depósitos e grade de passos."""

from collections.abc import Iterable
from datetime import date, timedelta

import plotly.graph_objects as go

from presentation.charts.theme import BLUE, base_layout

EMPTY = "rgba(128, 128, 128, 0.18)"  # dia/passo sem depósito (neutro, funciona no escuro)
_WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
GRID_COLUMNS = 20


def consistency_calendar(active: Iterable[date], start: date, end: date, today: date) -> go.Figure:
    """Calendário estilo GitHub: uma coluna por semana, uma linha por dia da semana.

    Azul = dia com depósito; cinza = sem depósito; vazio = dia futuro ou fora do prazo.
    As colunas cobrem o prazo inteiro do objetivo.
    A leitura é de constância: quanto mais contínua a faixa azul, melhor.
    """
    active_days = set(active)
    first_monday = start - timedelta(days=start.weekday())
    # Colunas cobrem o prazo inteiro (formato estável desde o 1º dia); só os dias até
    # hoje recebem cor, os futuros ficam vazios.
    last = min(end, today)
    weeks = (end - first_monday).days // 7 + 1
    z: list[list[float | None]] = [[None] * weeks for _ in range(7)]
    text: list[list[str]] = [[""] * weeks for _ in range(7)]
    for offset in range((last - start).days + 1):
        day = start + timedelta(days=offset)
        week = (day - first_monday).days // 7
        z[day.weekday()][week] = 1.0 if day in active_days else 0.0
        text[day.weekday()][week] = f"{day:%d/%m/%Y}: " + (
            "depositou" if day in active_days else "sem depósito"
        )
    x = [(first_monday + timedelta(weeks=w)).strftime("%d/%m") for w in range(weeks)]
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=x,
            y=_WEEKDAYS,
            text=text,
            hovertemplate="%{text}<extra></extra>",
            colorscale=[[0.0, EMPTY], [1.0, BLUE]],
            zmin=0,
            zmax=1,
            showscale=False,
            xgap=3,
            ygap=3,
        )
    )
    fig = base_layout(fig, height=230)
    fig.update_layout(hovermode="closest", margin={"l": 8, "r": 8, "t": 10, "b": 8})
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(showgrid=False, tickangle=0, nticks=12)
    return fig


def steps_grid(step_count: int, done: Iterable[int], step_amounts: list[str]) -> go.Figure:
    """Grade dos passos 1..N (20 por linha): azul = depositado, cinza = pendente.

    Mostra o desafio inteiro de uma vez; cada quadrado tem o número do passo.
    """
    done_steps = set(done)
    rows = (step_count + GRID_COLUMNS - 1) // GRID_COLUMNS
    z: list[list[float | None]] = [[None] * GRID_COLUMNS for _ in range(rows)]
    labels: list[list[str]] = [[""] * GRID_COLUMNS for _ in range(rows)]
    hover: list[list[str]] = [[""] * GRID_COLUMNS for _ in range(rows)]
    for step in range(1, step_count + 1):
        row, col = divmod(step - 1, GRID_COLUMNS)
        z[row][col] = 1.0 if step in done_steps else 0.0
        labels[row][col] = str(step)
        hover[row][col] = f"Passo {step}: {step_amounts[step - 1]}" + (
            " (feito)" if step in done_steps else ""
        )
    fig = go.Figure(
        go.Heatmap(
            z=z,
            text=labels,
            customdata=hover,
            texttemplate="%{text}",
            textfont={"size": 9},
            hovertemplate="%{customdata}<extra></extra>",
            colorscale=[[0.0, EMPTY], [1.0, BLUE]],
            zmin=0,
            zmax=1,
            showscale=False,
            xgap=2,
            ygap=2,
        )
    )
    fig = base_layout(fig, height=max(160, 26 * rows + 30))
    fig.update_layout(hovermode="closest", margin={"l": 8, "r": 8, "t": 10, "b": 8})
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, autorange="reversed")
    return fig
