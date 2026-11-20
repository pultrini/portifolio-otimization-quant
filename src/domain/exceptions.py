"""Exceções de regra de negócio do domínio.

Herdam de `ValueError` para que quem não conhece o domínio ainda as trate como entrada
inválida. A interface captura `DomainError` e mostra a mensagem ao usuário.
"""


class DomainError(ValueError):
    """Violação de uma regra de negócio."""


class InvalidAllocationError(DomainError):
    """Perfil de alocação alvo não fecha em 100% ou tem percentual fora de 0-100."""


class InsufficientQuantityError(DomainError):
    """Venda maior que a quantidade em carteira (venda a descoberto não é suportada)."""


class CurrencyMismatchError(DomainError):
    """Operação aritmética entre valores monetários de moedas diferentes."""


class MissingMarketDataError(DomainError):
    """Não há preço ou série de mercado suficiente para o cálculo pedido."""
