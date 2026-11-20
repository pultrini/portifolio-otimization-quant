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
