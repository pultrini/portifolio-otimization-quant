"""Classificação automática de um ticker em classe de ativo.

É uma sugestão para a importação; o usuário pode trocar a classe depois.
"""

import re
from collections.abc import Collection

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

# Units e ETFs da B3 com final 11 que NÃO são FIIs. Só é usada quando ainda não há a
# lista de FIIs da CVM (antes de "Atualizar fundamentos"); com ela, vale a CVM.
_B3_NON_REIT_11 = {
    # units
    "ALUP11", "BPAC11", "BRBI11", "CPLE11", "ENGI11", "IGTI11", "KLBN11", "SANB11",
    "SAPR11", "TAEE11", "TIET11", "AESB11", "BIDI11", "INTR11", "PACT11", "RNEW11",
    # ETFs de índice
    "BOVA11", "BOVV11", "BOVB11", "SMAL11", "SMAC11", "IVVB11", "SPXI11", "HASH11",
    "QBTC11", "BITH11", "ETHE11", "GOLD11", "DIVO11", "FIND11", "MATB11", "ECOO11",
    "XFIX11", "IMAB11", "IRFM11", "FIXA11", "B5P211", "NASD11", "ACWI11", "EURP11",
    "XINA11", "WRLD11", "BBSD11", "PIBB11", "BRAX11", "GOVE11", "SPXB11", "TECK11",
}  # fmt: skip

# REITs americanos e ETFs de REITs mais negociados.
_US_REITS = {
    "O", "PLD", "AMT", "EQIX", "SPG", "PSA", "WELL", "DLR", "VICI", "CCI", "AVB", "EQR",
    "ARE", "MAA", "IRM", "EXR", "INVH", "KIM", "REG", "VTR", "ESS", "UDR", "CPT", "HST",
    "BXP", "SBAC", "STAG", "NNN", "ADC", "WPC", "MPW", "FRT", "CUBE", "AMH", "ELS", "SUI",
    "VNQ", "VNQI", "SCHH", "XLRE", "IYR", "RWR", "USRT", "REET", "REM", "MORT",
}  # fmt: skip

# ETFs americanos de renda fixa mais comuns.
_US_BOND_ETFS = {"AGG", "BND", "BNDX", "TLT", "IEF", "SHY", "LQD", "HYG", "TIP", "GOVT", "VGIT"}


def is_brazilian_reit(ticker: Ticker, listed_reits: Collection[str] = ()) -> bool:
    """FII da B3?

    Com a lista de FIIs da CVM (informes mensais), é FII quem está nela. Sem a lista,
    vale o formato: final 11 que não seja unit nem ETF conhecido. O final 11 sozinho não
    basta porque units (TAEE11) e ETFs (BOVA11) usam o mesmo sufixo.
    """
    match = _B3_TICKER.match(ticker.symbol)
    if not match or match.group(1) != "11":
        return False
    base = ticker.symbol.removesuffix("F")
    if listed_reits:
        return base in listed_reits
    return base not in _B3_NON_REIT_11


def infer_asset_class(ticker: Ticker, listed_reits: Collection[str] = ()) -> AssetClass:
    """Sugere a classe de ativo a partir do formato do ticker.

    Regras, na ordem:
        1. cripto conhecida -> CRYPTO;
        2. CDI ou título do Tesouro (NTNB-, IPCA-, PRE-, SELIC-) -> BR_FIXED_INCOME;
        3. padrão B3: BDR -> INTL_EQUITY; FII (ver `is_brazilian_reit`) -> BR_REAL_ESTATE;
           demais (ações, units, ETFs) -> BR_EQUITY;
        4. ETF americano de renda fixa -> INTL_FIXED_INCOME;
        5. REIT americano ou ETF de REITs conhecido -> INTL_REAL_ESTATE;
        6. qualquer outro (ações e ETFs americanos) -> INTL_EQUITY.

    Args:
        listed_reits: Tickers de FIIs segundo a CVM; vazio quando ainda não baixados.
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
        if is_brazilian_reit(ticker, listed_reits):
            return AssetClass.BR_REAL_ESTATE
        return AssetClass.BR_EQUITY
    if symbol in _US_BOND_ETFS:
        return AssetClass.INTL_FIXED_INCOME
    if symbol in _US_REITS:
        return AssetClass.INTL_REAL_ESTATE
    return AssetClass.INTL_EQUITY
