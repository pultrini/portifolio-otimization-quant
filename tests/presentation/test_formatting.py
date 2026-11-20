"""Testes da formatação brasileira."""

from decimal import Decimal

import pytest

from presentation.components.formatting import (
    format_brl,
    format_number,
    format_pct,
    format_quantity,
    format_ratio_as_pct,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1234.56"), "R$ 1.234,56"),
        (Decimal("652.46"), "R$ 652,46"),
        (Decimal("-10"), "-R$ 10,00"),
        (Decimal("1234567.891"), "R$ 1.234.567,89"),
        (0.005, "R$ 0,01"),
        (None, "—"),
    ],
)
def test_brl(value: Decimal | float | None, expected: str) -> None:
    assert format_brl(value) == expected


def test_percentuais() -> None:
    assert format_pct(12.345) == "12,35%"
    assert format_pct(-3.1) == "-3,10%"
    assert format_ratio_as_pct(0.1234) == "12,34%"
    assert format_ratio_as_pct(None) == "—"


def test_numero_e_quantidade() -> None:
    assert format_number(1234.5) == "1.234,50"
    assert format_quantity(Decimal("2.00000000")) == "2"
    assert format_quantity(Decimal("0.00267000")) == "0,00267"
