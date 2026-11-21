"""Página: objetivos de poupança com foco em constância."""

from datetime import date
from decimal import Decimal

import streamlit as st

from application.dtos.goals import GoalDashboard, GoalPlanRequest, RegisterDepositRequest
from domain.entities.savings_goal import GoalFrequency, GoalMode
from domain.exceptions import DomainError
from domain.services.savings_plan import default_end
from presentation.charts.goals import consistency_calendar, steps_grid
from presentation.components.formatting import format_brl, format_pct
from presentation.components.session import PageContext

FLASH_KEY = "goal_flash"


def _period_word(frequency: GoalFrequency, count: int) -> str:
    if frequency is GoalFrequency.DAILY:
        return "dia" if count == 1 else "dias"
    return "semana" if count == 1 else "semanas"


def _new_goal(ctx: PageContext) -> None:
    st.caption(
        "Exemplo do desafio progressivo: depósitos de R$ 1, R$ 2, R$ 3 ... R$ 282 somam "
        "R$ 39.903. Cada passo pode ser feito em qualquer ordem; o que conta é não falhar dias."
    )
    col1, col2 = st.columns(2)
    name = col1.text_input("Nome do objetivo", value="Reserva anual", max_chars=80)
    target = col2.number_input("Meta (R$)", min_value=1.0, value=40000.0, step=1000.0)
    col3, col4, col5 = st.columns(3)
    mode = col3.radio("Tipo", list(GoalMode), format_func=lambda m: m.label_pt)
    frequency = col4.radio("Constância", list(GoalFrequency), format_func=lambda f: f.label_pt)
    unit = col5.number_input(
        "Passo (R$)",
        min_value=0.01,
        value=1.0,
        step=0.5,
        disabled=mode is not GoalMode.PROGRESSIVE,
        help="No progressivo, o passo k vale k x este valor.",
    )
    col6, col7 = st.columns(2)
    start = col6.date_input("Início", value=date.today(), format="DD/MM/YYYY")
    end = col7.date_input("Fim", value=default_end(date.today()), format="DD/MM/YYYY")
    if mode is None or frequency is None:
        return
    request = GoalPlanRequest(
        name=name or "Objetivo",
        target=Decimal(str(target)),
        mode=mode,
        frequency=frequency,
        start_date=start,
        end_date=end,
        unit=Decimal(str(unit)),
    )
    try:
        preview = ctx.container.preview_goal.execute(request)
    except DomainError as error:
        st.error(str(error))
        return
    word = _period_word(frequency, preview.period_count)
    if mode is GoalMode.PROGRESSIVE:
        st.info(
            f"{preview.step_count} depósitos de {format_brl(preview.first_step_amount)} a "
            f"{format_brl(preview.last_step_amount)} = **{format_brl(preview.total)}** em "
            f"{preview.period_count} {word} (sobram {preview.period_count - preview.step_count} "
            f"{_period_word(frequency, preview.period_count - preview.step_count)} de folga)."
        )
    else:
        st.info(
            f"{preview.step_count} depósitos de {format_brl(preview.unit_amount)} = "
            f"**{format_brl(preview.total)}**, um por {_period_word(frequency, 1)}."
        )
    if st.button("Criar objetivo", type="primary"):
        created = ctx.container.create_goal.execute(ctx.user_id, request)
        st.session_state[FLASH_KEY] = f"Objetivo '{created.name}' criado."
        st.rerun()


def _kpis(board: GoalDashboard) -> None:
    goal = board.goal
    word = _period_word(goal.frequency, board.current_streak)
    cols = st.columns(5)
    cols[0].metric(
        "Guardado",
        format_brl(board.saved),
        help=f"Soma dos passos depositados. Meta do plano: {format_brl(goal.total)}.",
    )
    cols[1].metric(
        "Progresso",
        format_pct(board.progress * 100),
        f"{board.completed_steps}/{goal.step_count} passos",
        delta_color="off",
    )
    cols[2].metric(
        "Sequência atual",
        f"{board.current_streak} {word}",
        f"recorde {board.longest_streak}",
        delta_color="off",
        help="Períodos seguidos com depósito. O período atual sem depósito ainda não quebra.",
    )
    cols[3].metric(
        "Constância",
        format_pct((board.consistency_rate or 0) * 100),
        f"{board.active_periods} de {board.elapsed_periods}",
        delta_color="off",
        help="Períodos com ao menos um depósito / períodos decorridos desde o início.",
    )
    pace = board.required_per_period
    cols[4].metric(
        "Ritmo",
        "No ritmo" if board.on_track else "Atrasado",
        None if pace is None else f"{pace:.2f} passo/{_period_word(goal.frequency, 1)}",
        delta_color="normal" if board.on_track else "inverse",
        help="Passos restantes / períodos restantes. Até 1 por período, você está no ritmo.",
    )
    st.progress(min(board.progress, 1.0))


def _deposit_form(ctx: PageContext, board: GoalDashboard) -> None:
    goal = board.goal
    if not board.pending_steps or goal.id is None:
        st.success("Todos os passos concluídos. Parabéns pela constância!")
        return
    amounts = {
        step: (goal.unit_amount * step if goal.mode is GoalMode.PROGRESSIVE else goal.unit_amount)
        for step in board.pending_steps
    }
    with st.form("deposit"):
        col1, col2, col3 = st.columns([2, 1, 1])
        step = col1.selectbox(
            "Passo depositado",
            board.pending_steps,
            index=0,
            format_func=lambda s: f"Passo {s} — {format_brl(amounts[s])}",
            help="Sugestão: o menor passo pendente, para manter a sequência sem esforço.",
        )
        day = col2.date_input("Data", value=date.today(), format="DD/MM/YYYY")
        col3.write("")
        submitted = col3.form_submit_button("Registrar", type="primary", width="stretch")
    if submitted and step is not None:
        try:
            row = ctx.container.register_deposit.execute(
                RegisterDepositRequest(
                    user_id=ctx.user_id, goal_id=goal.id, step=step, deposited_on=day
                )
            )
        except DomainError as error:
            st.error(str(error))
            return
        st.session_state[FLASH_KEY] = f"Passo {row.step} ({format_brl(row.amount)}) registrado."
        st.rerun()


def _history(ctx: PageContext, board: GoalDashboard) -> None:
    goal = board.goal
    if not board.deposits or goal.id is None:
        return
    with st.expander(f"Depósitos ({len(board.deposits)})"):
        st.dataframe(
            [
                {
                    "Data": d.deposited_on.strftime("%d/%m/%Y"),
                    "Passo": d.step,
                    "Valor": format_brl(d.amount),
                }
                for d in board.deposits
            ],
            hide_index=True,
            width="stretch",
        )
        col1, col2 = st.columns([2, 1])
        step = col1.selectbox("Desfazer passo", [d.step for d in board.deposits])
        col2.write("")
        if col2.button("Desfazer", width="stretch") and step is not None:
            ctx.container.undo_deposit.execute(goal.id, step)
            st.rerun()


def _dashboard(ctx: PageContext, goal_id: str) -> None:
    board = ctx.container.goal_dashboard.execute(goal_id)
    goal = board.goal
    st.caption(
        f"{goal.mode.label_pt} · constância {goal.frequency.label_pt.lower()} · "
        f"{goal.start_date:%d/%m/%Y} a {goal.end_date:%d/%m/%Y} · meta {format_brl(goal.total)}"
    )
    _kpis(board)
    if board.next_step is not None:
        st.info(f"Sugestão de hoje: passo {board.next_step}. O importante é não pular o dia.")
    _deposit_form(ctx, board)

    st.markdown("**Calendário de constância**")
    st.plotly_chart(
        consistency_calendar(board.active_dates, goal.start_date, goal.end_date, date.today()),
        width="stretch",
    )
    st.markdown("**Passos do desafio**")
    step_labels = [
        format_brl(goal.unit_amount * k if goal.mode is GoalMode.PROGRESSIVE else goal.unit_amount)
        for k in range(1, goal.step_count + 1)
    ]
    done = {d.step for d in board.deposits}
    st.plotly_chart(steps_grid(goal.step_count, done, step_labels), width="stretch")
    _history(ctx, board)

    with st.expander("Excluir objetivo"):
        confirm = st.checkbox("Confirmo que quero excluir este objetivo e seus depósitos")
        if st.button("Excluir", disabled=not confirm) and goal.id is not None:
            ctx.container.delete_goal.execute(goal.id)
            st.rerun()


def render(ctx: PageContext) -> None:
    st.header("Objetivos")
    st.caption("Guardar dinheiro com foco em constância, não em valor: um passo por período.")
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash)

    goals = ctx.container.list_goals.execute()
    tab_goals, tab_new = st.tabs(["Meus objetivos", "Novo objetivo"])
    with tab_new:
        _new_goal(ctx)
    with tab_goals:
        if not goals:
            st.info("Nenhum objetivo ainda. Crie o primeiro na aba Novo objetivo.")
            return
        names = {g.id: g.name for g in goals if g.id is not None}
        goal_id = st.selectbox("Objetivo", list(names), format_func=lambda gid: names[gid])
        if goal_id is not None:
            _dashboard(ctx, goal_id)
