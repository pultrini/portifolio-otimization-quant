"""Classificação automática de um ticker em classe de ativo.

É uma sugestão para a importação; o usuário pode trocar a classe depois.
"""

import re

from domain.value_objects.asset_class import AssetClass
from domain.value_objects.ticker import Ticker

# Ticker da B3: 4 letras + número (3 = ON, 4 = PN, 11 = unit/FII/ETF...), opcional "F"
# do mercado fracionário.
_B3_TICKER = re.compile(r"^[A-Z]{4}(\d{1,2})F?$")

# BDRs (32 a 35 e 39) são negociados na B3 mas dão exposição a empresas estrangeiras.
_BDR_SUFFIXES = {"32", "33", "34", "35", "39"}

# Tickers canônicos de renda fixa brasileira: CDI e títulos do Tesouro Direto.
_BR_FIXED_INCOME_PREFIXES = ("NTNB-", "IPCA-", "PRE-", "SELIC-")

_CRYPTO = {"BTC", "ETH", "SOL", "USDT", "USDC", "XRP", "ADA", "BNB", "DOGE"}

# ETFs americanos de renda fixa mais comuns.
_US_BOND_ETFS = {"AGG", "BND", "BNDX", "TLT", "IEF", "SHY", "LQD", "HYG", "TIP", "GOVT", "VGIT"}


def infer_asset_class(ticker: Ticker) -> AssetClass:
    """Sugere a classe de ativo a partir do formato do ticker.

    Regras, na ordem:
        1. cripto conhecida -> CRYPTO;
        2. CDI ou título do Tesouro (NTNB-, IPCA-, PRE-, SELIC-) -> BR_FIXED_INCOME;
        3. padrão B3: BDR -> INTL_EQUITY; demais (ações, FIIs, units) -> BR_EQUITY;
        4. ETF americano de renda fixa -> INTL_FIXED_INCOME;
        5. qualquer outro (ações e ETFs americanos) -> INTL_EQUITY.

    FIIs entram em Renda Variável Brasil: são cotas negociadas em bolsa, com volatilidade
    de renda variável, e o CLAUDE.md não tem classe própria para eles.
    """
    symbol = ticker.symbol
    if symbol in _CRYPTO:
        return AssetClass.CRYPTO
    if symbol == "CDI" or symbol.startswith(_BR_FIXED_INCOME_PREFIXES):
        return AssetClass.BR_FIXED_INCOME
    match = _B3_TICKER.match(symbol)
    if match:
        if match.group(1) in _BDR_SUFFIXES:
            return AssetClass.INTL_EQUITY
        return AssetClass.BR_EQUITY
    if symbol in _US_BOND_ETFS:
        return AssetClass.INTL_FIXED_INCOME
    return AssetClass.INTL_EQUITY
