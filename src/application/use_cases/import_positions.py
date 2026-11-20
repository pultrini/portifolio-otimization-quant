"""Use case: importar posições a partir de texto colado (ex.: extrato da corretora)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from application.dtos.portfolio import ImportPositionsRequest, ImportPositionsResponse
from domain.entities.position import Position
from domain.exceptions import DomainError
from domain.repositories.market_data_repository import MarketDataRepository
from domain.repositories.position_repository import PositionRepository
from domain.services.asset_classification import infer_asset_class
from domain.value_objects.money import Money
from domain.value_objects.ticker import Ticker

# Precisão das colunas numeric(20, 8) no banco.
QUANTITY_STEP = Decimal("0.00000001")

# "R$" separa as linhas por valor das linhas por quantidade.
_VALUE_MARKER = re.compile(r"\s+R\$\s*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedLine:
    """Linha interpretada, ainda sem cotação.

    Exatamente um dos pares é preenchido:
        - `quantity` + `average_price`: ativo com quantidade conhecida;
        - `current_value` (+ `invested_value` opcional): renda fixa, cripto ou qualquer
          ativo informado por valor. A quantidade é derivada do último preço.
    """

    line_number: int
    ticker: Ticker
    quantity: Decimal | None = None
    average_price: Decimal | None = None
    current_value: Decimal | None = None
    invested_value: Decimal | None = None


def parse_decimal(raw: str) -> Decimal:
    """Converte número em formato brasileiro ou internacional.

    Com vírgula, a vírgula é o separador decimal e pontos são milhar
    (`1.234,56` -> 1234.56). Sem vírgula, o ponto é decimal (`29.30` -> 29.30).
    """
    text = raw.strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise DomainError(f"Número inválido: {raw!r}.") from error
    if not value.is_finite() or value < 0:
        raise DomainError(f"Número inválido: {raw!r}.")
    return value


def parse_positions_text(text: str) -> tuple[list[ParsedLine], list[str]]:
    """Interpreta o texto linha a linha, sem interromper no primeiro erro.

    Linhas vazias e que começam com `#` são ignoradas. Ticker repetido é erro, para não
    somar duas linhas do extrato sem o usuário perceber.

    Returns:
        Linhas válidas e mensagens de erro (com o número da linha).
    """
    parsed: list[ParsedLine] = []
    errors: list[str] = []
    seen: set[Ticker] = set()

    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item = _parse_line(number, line)
        except DomainError as error:
            errors.append(f"Linha {number} ({line}): {error}")
            continue
        if item.ticker in seen:
            errors.append(f"Linha {number}: {item.ticker} aparece mais de uma vez.")
            continue
        seen.add(item.ticker)
        parsed.append(item)
    return parsed, errors


def _parse_line(number: int, line: str) -> ParsedLine:
    parts = _VALUE_MARKER.split(line, maxsplit=1)
    if len(parts) == 2:
        # Formato por valor: "TICKER R$ VALOR_ATUAL [VALOR_INVESTIDO]".
        ticker = Ticker.parse(parts[0])
        values = parts[1].split()
        if len(values) not in (1, 2):
            raise DomainError("use 'TICKER R$ VALOR_ATUAL [VALOR_INVESTIDO]'.")
        current = parse_decimal(values[0])
        if current == 0:
            raise DomainError("valor atual precisa ser maior que zero.")
        invested = parse_decimal(values[1]) if len(values) == 2 else None
        return ParsedLine(number, ticker, current_value=current, invested_value=invested)

    # Formato por quantidade: "TICKER QUANTIDADE PRECO_MEDIO".
    tokens = line.split()
    if len(tokens) != 3:
        raise DomainError("use 'TICKER QUANTIDADE PRECO_MEDIO' ou 'TICKER R$ VALOR'.")
    quantity = parse_decimal(tokens[1])
    if quantity == 0:
        raise DomainError("quantidade precisa ser maior que zero.")
    return ParsedLine(
        number,
        Ticker.parse(tokens[0]),
        quantity=quantity,
        average_price=parse_decimal(tokens[2]),
    )


class ImportPositions:
    """Cria ou substitui posições a partir do texto colado pelo usuário."""

    def __init__(self, positions: PositionRepository, market_data: MarketDataRepository) -> None:
        self._positions = positions
        self._market_data = market_data

    def execute(self, request: ImportPositionsRequest) -> ImportPositionsResponse:
        """Converte cada linha em posição e grava as válidas.

        Linhas por valor viram quantidade com o último preço:
            quantidade = valor atual / último preço
            preço médio = valor investido / quantidade (sem investido: = último preço)

        As posições importadas ficam com `manual_override = True`, porque o preço médio
        veio do usuário e não de operações registradas.

        Returns:
            Tickers importados e erros por linha. Linhas com erro não são gravadas.
        """
        parsed, errors = parse_positions_text(request.text)
        by_value = [item.ticker for item in parsed if item.current_value is not None]
        prices = self._market_data.latest_prices(by_value) if by_value else {}

        positions: list[Position] = []
        for item in parsed:
            try:
                positions.append(self._to_position(item, prices))
            except DomainError as error:
                errors.append(f"Linha {item.line_number} ({item.ticker}): {error}")

        if positions:
            self._positions.save_positions(request.user_id, request.portfolio_id, positions)
        if request.replace_existing and positions:
            imported = {p.ticker for p in positions}
            for existing in self._positions.list_positions(request.portfolio_id):
                if existing.ticker not in imported:
                    self._positions.delete_position(request.portfolio_id, existing.ticker)

        return ImportPositionsResponse(imported=[p.ticker.symbol for p in positions], errors=errors)

    @staticmethod
    def _to_position(item: ParsedLine, prices: dict[Ticker, Money]) -> Position:
        asset_class = infer_asset_class(item.ticker)
        if item.quantity is not None and item.average_price is not None:
            return Position(
                item.ticker, asset_class, item.quantity, Money.brl(item.average_price), True
            )

        assert item.current_value is not None  # garantido pelo parser
        price = prices.get(item.ticker)
        if price is None or price.amount <= 0:
            raise DomainError("sem cotação na camada Gold; atualize os dados de mercado.")
        quantity = (item.current_value / price.amount).quantize(QUANTITY_STEP)
        if quantity == 0:
            raise DomainError("valor pequeno demais para a cotação atual.")
        invested = item.invested_value if item.invested_value is not None else item.current_value
        return Position(item.ticker, asset_class, quantity, Money.brl(invested / quantity), True)
