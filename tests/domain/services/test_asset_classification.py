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
        ("MXRF11", AssetClass.BR_EQUITY),
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
