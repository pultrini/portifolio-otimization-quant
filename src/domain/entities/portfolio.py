"""Entidade de carteira."""

from dataclasses import dataclass

# Mesmo limite do check constraint `char_length(name) between 1 and 80` no banco.
MAX_NAME_LENGTH = 80


@dataclass(frozen=True, slots=True)
class Portfolio:
    """Carteira de um usuário, identificada pelo id persistido.

    Imutável (`frozen`): uma alteração gera uma nova instância, nunca muda a existente.

    Attributes:
        id: Identificador único (UUID em texto).
        name: Nome exibido ao usuário.
    """

    id: str
    name: str

    def __post_init__(self) -> None:
        # Nome só com espaços conta como vazio.
        if not 1 <= len(self.name.strip()) <= MAX_NAME_LENGTH:
            raise ValueError(f"Nome da carteira deve ter entre 1 e {MAX_NAME_LENGTH} caracteres.")
