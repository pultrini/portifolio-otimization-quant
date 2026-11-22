"""Testes da classificação automática de tickers."""

import pytest

from domain.services.asset_classification import infer_asset_class
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.ticker import Ticker


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("EGIE3", AssetClass.BR_EQUITY),
        ("KLBN4", AssetClass.BR_EQUITY),
        ("MXRF11", AssetClass.BR_REAL_ESTATE),
        ("HGLG11F", AssetClass.BR_REAL_ESTATE),
        ("TAEE11", AssetClass.BR_EQUITY),  # unit
        ("BOVA11", AssetClass.BR_EQUITY),  # ETF
        ("O", AssetClass.INTL_REAL_ESTATE),
        ("VNQ", AssetClass.INTL_REAL_ESTATE),
        ("PETR4F", AssetClass.BR_EQUITY),
        ("AAPL34", AssetClass.INTL_EQUITY),
        ("CDI", AssetClass.BR_FIXED_INCOME),
        ("NTNB-2060", AssetClass.BR_FIXED_INCOME),
        ("SELIC-2029", AssetClass.BR_FIXED_INCOME),
        ("BTC", AssetClass.CRYPTO),
        ("AGG", AssetClass.INTL_FIXED_INCOME),
        ("IVV", AssetClass.INTL_EQUITY),
    ],
)
def test_infere_classe(symbol: str, expected: AssetClass) -> None:
    assert infer_asset_class(Ticker(symbol)) is expected


def test_lista_da_cvm_prevalece_sobre_o_formato() -> None:
    from domain.services.asset_classification import is_brazilian_reit

    listed = {"MXRF11", "XPTO11"}
    # Com a lista, só é FII quem está nela, mesmo se o formato sugerir outra coisa.
    assert infer_asset_class(Ticker("XPTO11"), listed) is AssetClass.BR_REAL_ESTATE
    assert infer_asset_class(Ticker("ABCD11"), listed) is AssetClass.BR_EQUITY
    assert is_brazilian_reit(Ticker("MXRF11F"), listed)
    assert not is_brazilian_reit(Ticker("PETR4"), listed)
