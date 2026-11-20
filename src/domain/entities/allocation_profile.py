"""Perfil de alocação alvo por classe de ativo."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from domain.exceptions import InvalidAllocationError
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.percentage import HUNDRED

# Tolerância da soma em pontos percentuais (CLAUDE.md 5.1).
ALLOCATION_TOLERANCE_PP = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class AllocationProfile:
    """Percentual alvo por classe de ativo, somando 100% (± 0.01 p.p.).

    A regra fica aqui, e não só na interface, para que nenhum caminho (UI, script,
    teste) consiga persistir um perfil que não feche. Classes ausentes valem 0%.

    Attributes:
        targets: Percentual (0-100) por classe de ativo.
    """

    targets: Mapping[AssetClass, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for asset_class, pct in self.targets.items():
            if not Decimal("0") <= pct <= HUNDRED:
                raise InvalidAllocationError(
                    f"{asset_class.label_pt}: percentual {pct} fora de 0-100."
                )
        total = self.total
        if abs(total - HUNDRED) > ALLOCATION_TOLERANCE_PP:
            raise InvalidAllocationError(
                f"A soma dos alvos é {total}%; precisa fechar em 100% "
                f"(tolerância de {ALLOCATION_TOLERANCE_PP} p.p.)."
            )
        # Cópia somente leitura: o dict de quem chamou não altera a entidade depois.
        object.__setattr__(self, "targets", MappingProxyType(dict(self.targets)))

    @property
    def total(self) -> Decimal:
        return sum(self.targets.values(), Decimal("0"))

    def target_for(self, asset_class: AssetClass) -> Decimal:
        """Percentual alvo da classe; 0 quando a classe não está no perfil."""
        return self.targets.get(asset_class, Decimal("0"))
