"""Tradução de tickers canônicos para a fonte de dados de cada um.

O usuário e o domínio falam `EGIE3`, `BTC`, `CDI`, `NTNB-2060`. Cada fonte usa outro
código (`EGIE3.SA`, `BTC-USD`, série 12 do SGS, linha do CSV do Tesouro). Este módulo
concentra essa tradução, nos dois sentidos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from domain.value_objects.asset_class import (
    BITCOIN,
    CDI,
    IBOV,
    SP500,
    US_AGGREGATE_BOND,
    US_TREASURY_3M,
)


class Source(StrEnum):
    YAHOO = "yahoo"
    BCB = "bcb_sgs"
    TESOURO = "tesouro_direto"


class PriceCurrency(StrEnum):
    """Moeda em que a fonte cota o ativo.

    `INDEX` marca séries de taxa transformadas em índice (CDI, T-Bill): não passam por
    conversão cambial, porque representam a taxa livre de risco da própria moeda.
    """

    BRL = "BRL"
    USD = "USD"
    INDEX = "INDEX"


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """Onde e como buscar um ticker canônico."""

    ticker: str
    source: Source
    source_symbol: str
    currency: PriceCurrency


# Séries do SGS (Banco Central).
SGS_CDI = "12"  # CDI diário, % ao dia
SGS_SELIC = "11"  # Selic diária, % ao dia
SGS_PTAX_SELL = "1"  # PTAX venda, R$ por US$

# Tickers que o pipeline sempre baixa: benchmarks da tabela 5.1, taxas livres de risco
# e o câmbio (via SGS, fora desta lista).
REFERENCE_TICKERS: tuple[str, ...] = (IBOV, SP500, US_AGGREGATE_BOND, BITCOIN, CDI, US_TREASURY_3M)

_CRYPTO = {"BTC", "ETH", "SOL", "XRP", "ADA", "BNB", "DOGE"}
_B3 = re.compile(r"^([A-Z]{4}\d{1,2})F?$")  # "F" do fracionário cai fora
_TESOURO = re.compile(r"^(NTNB|IPCA|PRE|SELIC)-(\d{4})$")

# Prefixo canônico <-> "Tipo Titulo" no CSV do Tesouro Transparente.
TESOURO_TYPES: dict[str, str] = {
    "NTNB": "Tesouro IPCA+ com Juros Semestrais",
    "IPCA": "Tesouro IPCA+",
    "PRE": "Tesouro Prefixado",
    "SELIC": "Tesouro Selic",
}
_TESOURO_PREFIX_BY_TYPE = {name: prefix for prefix, name in TESOURO_TYPES.items()}


def resolve(ticker: str) -> InstrumentSpec:
    """Descobre fonte, código na fonte e moeda de um ticker canônico.

    Regras:
        CDI -> SGS 12 (vira índice); TBILL3M -> ^IRX no Yahoo (vira índice);
        NTNB/IPCA/PRE/SELIC-AAAA -> CSV do Tesouro Direto;
        cripto -> <TICKER>-USD; padrão B3 -> <TICKER>.SA em BRL;
        ^BVSP em BRL; qualquer outro -> Yahoo em USD (ações, ETFs e índices americanos).
    """
    if ticker == CDI:
        return InstrumentSpec(ticker, Source.BCB, SGS_CDI, PriceCurrency.INDEX)
    if ticker == US_TREASURY_3M:
        return InstrumentSpec(ticker, Source.YAHOO, "^IRX", PriceCurrency.INDEX)
    if _TESOURO.match(ticker):
        return InstrumentSpec(ticker, Source.TESOURO, ticker, PriceCurrency.BRL)
    if ticker in _CRYPTO:
        return InstrumentSpec(ticker, Source.YAHOO, f"{ticker}-USD", PriceCurrency.USD)
    b3 = _B3.match(ticker)
    if b3:
        return InstrumentSpec(ticker, Source.YAHOO, f"{b3.group(1)}.SA", PriceCurrency.BRL)
    if ticker == IBOV:
        return InstrumentSpec(ticker, Source.YAHOO, ticker, PriceCurrency.BRL)
    return InstrumentSpec(ticker, Source.YAHOO, ticker, PriceCurrency.USD)


def canonical_from_yahoo(symbol: str) -> str:
    """Inverso de `resolve` para códigos do Yahoo (usado ao montar a Silver)."""
    if symbol == "^IRX":
        return US_TREASURY_3M
    if symbol.endswith(".SA"):
        return symbol.removesuffix(".SA")
    if symbol.endswith("-USD"):
        return symbol.removesuffix("-USD")
    return symbol


def canonical_from_tesouro(title_type: str, maturity_year: int) -> str | None:
    """Ticker canônico de um título do Tesouro; None para tipos não suportados."""
    prefix = _TESOURO_PREFIX_BY_TYPE.get(title_type)
    return f"{prefix}-{maturity_year}" if prefix else None


def yahoo_currency(symbol: str) -> PriceCurrency:
    """Moeda de cotação de um código do Yahoo."""
    return resolve(canonical_from_yahoo(symbol)).currency
