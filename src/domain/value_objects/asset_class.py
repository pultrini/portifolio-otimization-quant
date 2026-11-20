"""Classes de ativo suportadas pela plataforma (CLAUDE.md, seção 5.1)."""

from enum import StrEnum


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


# Fica fora da classe porque qualquer atributo dentro de um Enum vira um membro.
_LABELS_PT: dict[AssetClass, str] = {
    AssetClass.BR_EQUITY: "Renda Variável Brasil",
    AssetClass.INTL_EQUITY: "Renda Variável Internacional",
    AssetClass.BR_FIXED_INCOME: "Renda Fixa Brasil",
    AssetClass.INTL_FIXED_INCOME: "Renda Fixa Internacional",
    AssetClass.CRYPTO: "Criptoativos",
}
