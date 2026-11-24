"""Código de negociação de um ativo."""

from __future__ import annotations

import re
from dataclasses import dataclass

from domain.exceptions import DomainError

# Letras, dígitos, ponto, hífen e circunflexo (índices como ^BVSP). Até 20 caracteres,
# mesmo limite da coluna `ticker` no banco.
_TICKER_PATTERN = re.compile(r"^[A-Z0-9^][A-Z0-9.\-^]{0,19}$")


@dataclass(frozen=True, slots=True, order=True)
class Ticker:
    """Ticker canônico da plataforma, sempre em maiúsculas.

    É o código que o usuário conhece (EGIE3, BTC, CDI, NTNB-2060), não o da fonte de
    dados (EGIE3.SA, BTC-USD). A tradução para cada fonte fica na Infrastructure.
    """

    symbol: str

    def __post_init__(self) -> None:
        if not _TICKER_PATTERN.match(self.symbol):
            raise DomainError(f"Ticker inválido: {self.symbol!r}.")

    @classmethod
    def parse(cls, raw: str) -> Ticker:
        """Normaliza a entrada do usuário antes de validar.

        - espaços e minúsculas: " aapl " -> "AAPL";
        - sufixo do Yahoo para a B3: "PETR4.SA" -> "PETR4";
        - classe de ação americana com ponto: "BRK.B" -> "BRK-B" (o Yahoo usa hífen, e o
          ticker canônico precisa ser o mesmo da fonte para a cotação voltar a ele).
        """
        symbol = raw.strip().upper().removesuffix(".SA")
        if not symbol.startswith("^"):
            symbol = symbol.replace(".", "-")
        return cls(symbol)

    def __str__(self) -> str:
        return self.symbol
