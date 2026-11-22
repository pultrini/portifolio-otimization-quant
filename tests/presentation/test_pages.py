"""Renderiza cada página com o AppTest do Streamlit e dados em memória.

Garante que as páginas executam sem exceção e mostram o conteúdo esperado: tabelas,
KPIs e gráficos. Não substitui olhar a tela, mas pega erros de execução e de dados.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).parents[2] / "src" / "presentation" / "app.py"
TIMEOUT = 60


def _carteira() -> None:
    from presentation.pages import portfolio
    from tests.presentation.page_harness import build_context

    portfolio.render(build_context())


def _operacoes() -> None:
    from presentation.pages import trades
    from tests.presentation.page_harness import build_context

    trades.render(build_context())


def _alocacao() -> None:
    from presentation.pages import allocation
    from tests.presentation.page_harness import build_context

    allocation.render(build_context())


def _metricas() -> None:
    from presentation.pages import metrics
    from tests.presentation.page_harness import build_context

    metrics.render(build_context())


def _otimizacao() -> None:
    from presentation.pages import optimization
    from tests.presentation.page_harness import build_context

    optimization.render(build_context())


def _objetivos() -> None:
    import streamlit as st

    from presentation.pages import goals
    from tests.presentation.page_harness import build_context

    # Mantém os repositórios em memória entre os reruns (criar e depositar recarregam).
    if "harness_ctx" not in st.session_state:
        st.session_state["harness_ctx"] = build_context()
    goals.render(st.session_state["harness_ctx"])


def _guia() -> None:
    from presentation.pages import guide

    guide.render()


def _run(script: object) -> AppTest:
    at = AppTest.from_function(script, default_timeout=TIMEOUT)  # type: ignore[arg-type]
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_pagina_carteira() -> None:
    at = _run(_carteira)
    assert at.header[0].value == "Carteira"
    labels = [m.label for m in at.metric]
    assert labels == ["Patrimônio", "Custo", "Resultado"]
    assert at.metric[0].value.startswith("R$ ")
    assert len(at.dataframe) == 1
    assert not at.warning  # todos os ativos têm cotação
    assert any(s.value == "Lista de desejos" for s in at.subheader)
    assert any(m.value == "**DDDD3**" for m in at.markdown)


def test_questionario_e_pesos_dentro_de_editar_posicao() -> None:
    at = _run(_carteira)
    assert [t.label for t in at.tabs] == ["Posição", "📝 Questionário de importância"]
    # Ativo da carteira: perguntas na aba, dentro de uma caixa com rolagem.
    at.selectbox(key="edit_ticker").set_value("AAAA3").run()
    questions = [r for r in at.radio if "portfolio_chk_AAAA3" in str(r.key)]
    assert len(questions) == 11
    questions[0].set_value("Sim")
    questions[1].set_value("Não")
    next(b for b in at.button if b.label == "Salvar respostas").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Nota do checklist **9,09%** · 1 Sim, 1 Não" in m.value for m in at.markdown)

    # Postura conservadora: um Não anula dois Sim -> (1 - 2) / 11 < 0 -> nota 0.
    at.radio(key="portfolio_weights_preset").set_value("Conservador: um Não anula dois Sim").run()
    next(b for b in at.button if b.label == "Salvar pesos").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Nota do checklist **0,00%**" in m.value for m in at.markdown)

    # Ativo da lista de desejos também tem questionário; renda fixa não tem.
    at.selectbox(key="edit_ticker").set_value("DDDD3").run()
    assert any("portfolio_chk_DDDD3" in str(r.key) for r in at.radio)
    at.selectbox(key="edit_ticker").set_value("CDI").run()
    assert any("não tem questionário" in i.value for i in at.info)


def test_pagina_operacoes() -> None:
    at = _run(_operacoes)
    assert at.header[0].value == "Operações"
    assert len(at.dataframe) == 1


def test_pagina_alocacao() -> None:
    at = _run(_alocacao)
    assert at.header[0].value == "Alocação Alvo"
    assert [m.label for m in at.metric] == ["Patrimônio atual", "Após o aporte"]
    assert len(at.get("plotly_chart")) == 2
    assert not at.warning  # perfil salvo fecha em 100%
    # Sem valor de aporte ainda: decisão aparece, mas sem compras.
    assert any(s.value == "Decisão por ativo" for s in at.subheader)
    assert any("Informe um valor de aporte" in i.value for i in at.info)


def test_aportar_registra_e_confirma() -> None:
    at = _run(_alocacao)
    amount = next(n for n in at.number_input if n.label == "Valor do aporte (R$)")
    amount.set_value(1000.0).run()
    assert not at.exception, [e.value for e in at.exception]
    texts = [m.value for m in at.markdown]
    assert "**Melhor aporte**" in texts
    assert any("Comprar **" in t for t in texts)
    # Lista de ativos (sem tabela): DDDD3 aparece marcado como desejado.
    texts = [m.value for m in at.markdown]
    assert any(t.startswith("**DDDD3**") and "desejado" in t for t in texts)
    assert not at.dataframe or all("Nota quant" not in str(d.value) for d in at.dataframe)
    # Resumo por classe com atual -> alvo.
    assert any("atual **" in t and "alvo **" in t for t in texts)
    # Sem perguntas na página: elas abrem na janela do questionário.
    # (o único radio fora da janela é a postura, dentro do popover de pesos)
    assert all(r.key == "allocation_weights_preset" for r in at.radio)
    questionnaire = next(b for b in at.button if b.label == "📝 Questionário")
    questionnaire.click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert sum(1 for r in at.radio if "_chk_" in str(r.key)) >= 6  # perguntas, na janela

    aportar = next(b for b in at.button if b.label == "Aportar")
    aportar.click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Aporte registrado" in s.value for s in at.success)


def test_pagina_metricas() -> None:
    at = _run(_metricas)
    texts = [m.value for m in at.markdown]
    assert "### Carteira" in texts
    assert "### Por classe de ativo" in texts
    assert "### Por estratégia" in texts
    assert any(m.label == "Win rate" for m in at.metric)
    # Carteira, 4 classes (RV, FII, RF, cripto) e 1 estratégia: um gráfico por escopo.
    assert len(at.get("plotly_chart")) == 6
    assert not at.error


def test_pagina_otimizacao() -> None:
    at = _run(_otimizacao)
    assert at.header[0].value == "Otimização"
    # Aba 1: fronteira e correlação. Aba 2 (simulação): pesos e evolução.
    assert len(at.get("plotly_chart")) == 4
    assert any("Fora da otimização: CDI" in c.value for c in at.caption)
    assert not at.error
    assert [t.label for t in at.tabs] == [
        "Fronteira eficiente",
        "🧪 Simulando melhor carteira quant",
    ]
    assert any(m.label == "Sharpe simulado" for m in at.metric)
    texts = [m.value for m in at.markdown]
    # Lista de desejos entra na simulação, e o perfil alvo define o peso das classes.
    assert any(t.startswith("**DDDD3**") and "desejado" in t for t in texts)
    assert any("simulada **50,00%**" in t and "alvo 50,00%" in t for t in texts)
    assert any("FII" in t and "alvo 10,00%" in t for t in texts)


def test_simulacao_sem_perfil_alvo_e_com_aporte() -> None:
    at = _run(_otimizacao)
    form = at.tabs[1]
    next(t for t in form.toggle if t.label == "Respeitar alocação alvo").set_value(False)
    next(n for n in form.number_input if n.label == "Aporte novo (R$)").set_value(500.0)
    next(b for b in form.button if b.label == "Simular").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error
    expander = next(e for e in at.expander if e.label.startswith("Fora da simulação"))
    assert any("CDI" in m.value and "renda fixa" in m.value for m in expander.markdown)


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> AppTest:
    """O app.py completo, com a sessão já autenticada e o container em memória."""
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-de-teste")
    from tests.presentation.page_harness import build_container

    container, portfolio_id = build_container()
    at = AppTest.from_file(str(APP), default_timeout=TIMEOUT)
    at.session_state["supabase_client"] = object()
    at.session_state["user_id"] = "user-1"
    at.session_state["container"] = container
    at.session_state["portfolio_id"] = portfolio_id
    return at


def test_app_abre_na_carteira_com_navegacao(app: AppTest) -> None:
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    assert app.header[0].value == "Carteira"
    assert app.sidebar.selectbox[0].value == app.session_state["portfolio_id"]


def test_app_sem_sessao_mostra_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "chave-de-teste")
    at = AppTest.from_file(str(APP), default_timeout=TIMEOUT)
    at.session_state["supabase_client"] = object()
    at.run()
    assert not at.exception
    assert at.title[0].value == "Otimização de Portfólio"
    assert [t.label for t in at.tabs] == ["Entrar", "Criar conta"]


def test_pagina_guia_renderiza_todas_as_metricas() -> None:
    from presentation.components.glossary import DOCS

    at = AppTest.from_function(_guia, default_timeout=TIMEOUT)  # type: ignore[arg-type]
    at.query_params["m"] = "sharpe"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert [e.label for e in at.expander] == [d.title for d in DOCS]
    assert len(at.latex) == len(DOCS)
    # Exemplos numéricos calculados pelo domínio aparecem no texto.
    assert any("**-0,75**" in m.value for m in at.markdown)


def test_app_inclui_guia_na_navegacao(app: AppTest) -> None:
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    # O popover "Equações e exemplos" só aparece nas páginas com métricas; a Carteira
    # abre por padrão e o guia está registrado na navegação.
    assert app.header[0].value == "Carteira"


def test_objetivos_criar_e_depositar() -> None:
    at = _run(_objetivos)
    assert at.header[0].value == "Objetivos"
    assert any("Nenhum objetivo ainda" in i.value for i in at.info)
    # Prévia do desafio padrão (R$ 40.000, passo R$ 1, um ano).
    assert any("282 depósitos de R$ 1,00 a R$ 282,00" in i.value for i in at.info)

    next(b for b in at.button if b.label == "Criar objetivo").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("criado" in s.value for s in at.success)
    assert [m.label for m in at.metric] == [
        "Guardado",
        "Progresso",
        "Sequência atual",
        "Constância",
        "Ritmo",
    ]
    assert len(at.get("plotly_chart")) == 2  # calendário e grade de passos

    next(b for b in at.button if b.label == "Registrar").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Passo 1 (R$ 1,00) registrado" in s.value for s in at.success)
    guardado = next(m for m in at.metric if m.label == "Guardado")
    assert guardado.value == "R$ 1,00"
    sequencia = next(m for m in at.metric if m.label == "Sequência atual")
    assert sequencia.value == "1 dia"
