"""Testes dos value objects (sem I/O)."""

from decimal import Decimal

import pytest

from domain.exceptions import CurrencyMismatchError, DomainError
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.money import Currency, Money
from domain.value_objects.percentage import Percentage
from domain.value_objects.ticker import Ticker


class TestMoney:
    def test_soma_decimal_exata(self) -> None:
        # Em float, 0.1 + 0.2 = 0.30000000000000004.
        assert (Money.brl("0.1") + Money.brl("0.2")).amount == Decimal("0.3")

    def test_recusa_float(self) -> None:
        with pytest.raises(TypeError):
            Money(0.1)  # type: ignore[arg-type]

    def test_recusa_moedas_diferentes(self) -> None:
        with pytest.raises(CurrencyMismatchError):
            _ = Money.brl("1") + Money(Decimal("1"), Currency.USD)

    def test_multiplica_por_quantidade(self) -> None:
        assert (Money.brl("29.30") * Decimal("2")).amount == Decimal("58.60")

    def test_arredonda_meio_para_cima(self) -> None:
        assert Money.brl("1.005").rounded().amount == Decimal("1.01")

    def test_divisao_por_zero(self) -> None:
        with pytest.raises(DomainError):
            _ = Money.brl("10") / 0

    def test_recusa_infinito(self) -> None:
        with pytest.raises(DomainError):
            Money(Decimal("Infinity"))


class TestPercentage:
    def test_fracao(self) -> None:
        assert Percentage.of("60").as_fraction == Decimal("0.6")

    @pytest.mark.parametrize("value", ["-0.01", "100.01"])
    def test_fora_da_faixa(self, value: str) -> None:
        with pytest.raises(DomainError):
            Percentage.of(value)


class TestTicker:
    def test_normaliza(self) -> None:
        assert Ticker.parse("  egie3 ").symbol == "EGIE3"

    @pytest.mark.parametrize("raw", ["", "EG IE3", "A" * 21, "$BTC"])
    def test_invalido(self, raw: str) -> None:
        with pytest.raises(DomainError):
            Ticker.parse(raw)

    @pytest.mark.parametrize("raw", ["^BVSP", "NTNB-2060", "BTC", "KLBN4F"])
    def test_validos(self, raw: str) -> None:
        assert Ticker.parse(raw).symbol == raw


class TestAssetClass:
    def test_tabela_benchmark_e_taxa_livre_de_risco(self) -> None:
        assert AssetClass.BR_EQUITY.benchmark == "^BVSP"
        assert AssetClass.BR_EQUITY.risk_free == "CDI"
        assert AssetClass.INTL_EQUITY.benchmark == "^GSPC"
        assert AssetClass.INTL_EQUITY.risk_free == "TBILL3M"
        assert AssetClass.CRYPTO.benchmark == "BTC"

    def test_anualizacao(self) -> None:
        assert AssetClass.CRYPTO.periods_per_year == 365
        assert AssetClass.BR_EQUITY.periods_per_year == 252
