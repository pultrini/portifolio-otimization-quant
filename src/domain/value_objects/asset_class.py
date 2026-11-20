"""Classes de ativo suportadas pela plataforma (CLAUDE.md, seção 5.1)."""

from enum import StrEnum

# Tickers canônicos das séries de referência. A Infrastructure traduz cada um para a
# fonte certa (^BVSP no Yahoo, CDI no Banco Central, TBILL3M a partir do ^IRX etc.).
IBOV = "^BVSP"
SP500 = "^GSPC"
US_AGGREGATE_BOND = "AGG"  # ETF iShares Core US Aggregate Bond, proxy do índice.
BITCOIN = "BTC"
CDI = "CDI"
US_TREASURY_3M = "TBILL3M"

# Dias por ano usados na anualização (CLAUDE.md 5.2).
TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365


class AssetClass(StrEnum):
    """Classe de ativo. Cada uma tem benchmark e taxa livre de risco próprios.

    É `StrEnum` para que o valor seja o próprio texto do enum `public.asset_class`
    no Postgres, sem tabela de conversão entre banco e código.
    """

    BR_EQUITY = "BR_EQUITY"
    INTL_EQUITY = "INTL_EQUITY"
    BR_FIXED_INCOME = "BR_FIXED_INCOME"
    INTL_FIXED_INCOME = "INTL_FIXED_INCOME"
    CRYPTO = "CRYPTO"

    @property
    def label_pt(self) -> str:
        """Rótulo em português para exibição na interface."""
        return _LABELS_PT[self]

    @property
    def benchmark(self) -> str:
        """Ticker canônico do benchmark da classe (usado no Beta e nos deltas de KPI)."""
        return _BENCHMARKS[self]

    @property
    def risk_free(self) -> str:
        """Ticker canônico da taxa livre de risco (usada em Sharpe e Sortino)."""
        return _RISK_FREE[self]

    @property
    def periods_per_year(self) -> int:
        """Base de anualização: cripto negocia todos os dias, o resto só em dias úteis."""
        if self is AssetClass.CRYPTO:
            return CALENDAR_DAYS_PER_YEAR
        return TRADING_DAYS_PER_YEAR


# Ficam fora da classe porque qualquer atributo dentro de um Enum vira um membro.
_LABELS_PT: dict[AssetClass, str] = {
    AssetClass.BR_EQUITY: "Renda Variável Brasil",
    AssetClass.INTL_EQUITY: "Renda Variável Internacional",
    AssetClass.BR_FIXED_INCOME: "Renda Fixa Brasil",
    AssetClass.INTL_FIXED_INCOME: "Renda Fixa Internacional",
    AssetClass.CRYPTO: "Criptoativos",
}

_BENCHMARKS: dict[AssetClass, str] = {
    AssetClass.BR_EQUITY: IBOV,
    AssetClass.INTL_EQUITY: SP500,
    AssetClass.BR_FIXED_INCOME: CDI,
    AssetClass.INTL_FIXED_INCOME: US_AGGREGATE_BOND,
    AssetClass.CRYPTO: BITCOIN,
}

_RISK_FREE: dict[AssetClass, str] = {
    AssetClass.BR_EQUITY: CDI,
    AssetClass.INTL_EQUITY: US_TREASURY_3M,
    AssetClass.BR_FIXED_INCOME: CDI,
    AssetClass.INTL_FIXED_INCOME: US_TREASURY_3M,
    AssetClass.CRYPTO: US_TREASURY_3M,
}
