"""Formatação brasileira para exibição: `R$ 1.234,56`, `12,34%`."""

from decimal import ROUND_HALF_UP, Decimal

PLACEHOLDER = "—"


def _group_br(value: Decimal, decimals: int) -> str:
    """Formata com milhar em ponto e decimal em vírgula, sem sinal."""
    # Arredonda antes: o format do Python usa "meio para o par" (12.345 -> 12.34),
    # e a exibição financeira usa "meio para cima" (12.345 -> 12.35).
    step = Decimal(1).scaleb(-decimals)
    rounded = abs(value).quantize(step, rounding=ROUND_HALF_UP)
    # O formato do Python usa "," para milhar e "." para decimal; depois troca os dois.
    text = f"{rounded:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def format_brl(value: Decimal | float | None) -> str:
    """Valor em reais com 2 casas: `R$ 1.234,56` / `-R$ 10,00`."""
    if value is None:
        return PLACEHOLDER
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    return f"{sign}R$ {_group_br(amount, 2)}"


def format_pct(value: Decimal | float | None, decimals: int = 2) -> str:
    """Percentual já em pontos percentuais: 12.345 -> `12,35%`."""
    if value is None:
        return PLACEHOLDER
    amount = Decimal(str(value))
    sign = "-" if amount < 0 else ""
    return f"{sign}{_group_br(amount, decimals)}%"


def format_ratio_as_pct(value: float | None, decimals: int = 2) -> str:
    """Fração em percentual: 0.1234 -> `12,34%` (métricas vêm como fração)."""
    return format_pct(None if value is None else value * 100, decimals)


def format_number(value: Decimal | float | None, decimals: int = 2) -> str:
    """Número com separadores brasileiros: 1234.5 -> `1.234,50`."""
    if value is None:
        return PLACEHOLDER
    amount = Decimal(str(value))
    sign = "-" if amount < 0 else ""
    return f"{sign}{_group_br(amount, decimals)}"


def format_quantity(value: Decimal) -> str:
    """Quantidade sem zeros à direita: 2 -> `2`, 0.00267000 -> `0,00267`."""
    normalized = value.normalize()
    decimals = max(0, -normalized.as_tuple().exponent)  # type: ignore[operator]
    return format_number(value, int(decimals))
