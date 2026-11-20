"""Testes da entidade Portfolio (sem I/O)."""

import pytest

from domain.entities.portfolio import MAX_NAME_LENGTH, Portfolio


@pytest.mark.parametrize("name", ["", "   ", "x" * (MAX_NAME_LENGTH + 1)])
def test_rejeita_nome_invalido(name: str) -> None:
    with pytest.raises(ValueError):
        Portfolio(id="1", name=name)


def test_aceita_nome_no_limite() -> None:
    assert Portfolio(id="1", name="x" * MAX_NAME_LENGTH).name == "x" * MAX_NAME_LENGTH


def test_e_imutavel() -> None:
    portfolio = Portfolio(id="1", name="Principal")
    with pytest.raises(AttributeError):
        portfolio.name = "Outra"  # type: ignore[misc]
