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
    assert not at.radio
    questionnaire = next(b for b in at.button if b.label == "📝 Questionário")
    questionnaire.click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.radio) >= 6  # perguntas do ativo, dentro da janela

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
    # Carteira, 3 classes (RV, RF, cripto) e 1 estratégia: um gráfico por escopo.
    assert len(at.get("plotly_chart")) == 5
    assert not at.error


def test_pagina_otimizacao() -> None:
    at = _run(_otimizacao)
    assert at.header[0].value == "Otimização"
    assert len(at.get("plotly_chart")) == 2  # fronteira e correlação
    assert any("Fora da otimização: CDI" in c.value for c in at.caption)
    assert not at.error


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
