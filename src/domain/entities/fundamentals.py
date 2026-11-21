"""Fatos fundamentalistas usados nas respostas automáticas do checklist."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, slots=True)
class AnnualFigures:
    """Números anuais de demonstrações financeiras (em moeda da companhia).

    Valores ausentes na fonte ficam None; as regras ignoram anos incompletos.
    """

    year: int
    revenue: float | None = None
    net_income: float | None = None
    ebitda: float | None = None
    equity: float | None = None
    total_debt: float | None = None
    cash: float | None = None

    @property
    def roe(self) -> float | None:
        """ROE = lucro líquido / patrimônio líquido."""
        if self.net_income is None or not self.equity:
            return None
        return self.net_income / self.equity

    @property
    def net_debt_to_ebitda(self) -> float | None:
        """Dívida líquida / EBITDA, com dívida líquida = dívida bruta - caixa."""
        if self.total_debt is None or self.cash is None or not self.ebitda:
            return None
        return (self.total_debt - self.cash) / self.ebitda


@dataclass(frozen=True, slots=True)
class StockFundamentals:
    """Fundamentos de uma ação (Yahoo Finance + cadastro da CVM)."""

    ticker: str
    annual: tuple[AnnualFigures, ...] = ()
    dividend_years: frozenset[int] = field(default_factory=frozenset)
    constitution_date: date | None = None
    control: str | None = None  # ex.: "PRIVADO", "ESTATAL HOLDING" (CVM)
    market_cap_brl: float | None = None


@dataclass(frozen=True, slots=True)
class ReitFundamentals:
    """Fundamentos de um FII (informes mensais da CVM).

    Attributes:
        book_value_per_share: Valor patrimonial por cota (último informe).
        months_with_dividends: Meses com dividend yield > 0 entre os últimos `months_observed`.
        dividend_yield_12m: Soma do dividend yield mensal dos últimos 12 meses.
        segment_median_yield_12m: Mediana desse mesmo número entre os FIIs do segmento.
    """

    ticker: str
    segment: str | None = None
    book_value_per_share: float | None = None
    months_with_dividends: int = 0
    months_observed: int = 0
    dividend_yield_12m: float | None = None
    segment_median_yield_12m: float | None = None
    reference_month: date | None = None
