"""Perguntas qualitativas (checklist) usadas na decisão de aporte.

Por padrão cada "Sim" vale um ponto e "Não" vale zero: a nota é a fração de "Sim".
O usuário pode ser mais conservador dando peso negativo ao "Não" (ver ChecklistWeights).
As perguntas são as definidas pelo usuário; o texto fica aqui para que regra e
interface usem exatamente a mesma definição.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from domain.exceptions import DomainError

MAX_YES_WEIGHT = 3.0
MAX_NO_WEIGHT = 5.0


class ChecklistKind(StrEnum):
    STOCK = "STOCK"
    REIT = "REIT"  # fundo imobiliário (FII)


class AnswerSource(StrEnum):
    AUTO = "AUTO"  # calculada a partir de dados abertos
    MANUAL = "MANUAL"  # informada pelo usuário (prevalece sobre a automática)


@dataclass(frozen=True, slots=True)
class Question:
    key: str
    title: str
    text: str


STOCK_QUESTIONS: tuple[Question, ...] = (
    Question("roe", "ROE", "ROE historicamente maior que 5%? (Considere anos anteriores)."),
    Question(
        "cagr", "CAGR", "Tem crescimento de receitas (ou lucro) superior a 5% nos últimos 5 anos?"
    ),
    Question("dividends", "Dividendos", "A empresa tem um histórico de pagamento de dividendos?"),
    Question(
        "research",
        "Tecnologia e pesquisa",
        "A empresa investe amplamente em pesquisa e inovação? Setor obsoleto = sempre não.",
    ),
    Question("age", "Tempo de mercado", "Tem mais de 30 anos de mercado? (Fundação)"),
    Question(
        "leadership",
        "Vantagens competitivas",
        "É líder nacional ou mundial no setor em que atua? (Só conta se for a primeira colocada)",
    ),
    Question("perennial", "Perenidade", "O setor em que a empresa atua tem mais de 100 anos?"),
    Question("blue_chip", "Tamanho", "A empresa é uma Blue Chip?"),
    Question(
        "governance",
        "Governança",
        "A empresa tem uma boa gestão? Histórico de corrupção = sempre não.",
    ),
    Question(
        "independence",
        "Independência",
        "É livre de controle estatal ou de concentração em cliente único?",
    ),
    Question(
        "low_debt", "Pouco endividada", "Dívida líquida/EBITDA é menor que 2 nos últimos 5 anos?"
    ),
)

REIT_QUESTIONS: tuple[Question, ...] = (
    Question("location", "Localização", "Os imóveis do fundo estão localizados em regiões nobres?"),
    Question(
        "properties",
        "Propriedades",
        "As propriedades são novas e não consomem manutenção excessiva?",
    ),
    Question(
        "price_to_book",
        "P/VP",
        "O fundo está negociado abaixo de P/VP 1? (Acima de 1,5 é descartado em qualquer hipótese)",
    ),
    Question(
        "reit_dividends", "Dividendos", "Distribui dividendos há mais de 4 anos consistentemente?"
    ),
    Question("dependency", "Dependência", "Não é dependente de um único inquilino ou imóvel?"),
    Question(
        "sector_yield",
        "Setor",
        "O yield está dentro ou acima da média para fundos do mesmo tipo?",
    ),
)

QUESTIONS: dict[ChecklistKind, tuple[Question, ...]] = {
    ChecklistKind.STOCK: STOCK_QUESTIONS,
    ChecklistKind.REIT: REIT_QUESTIONS,
}


@dataclass(frozen=True, slots=True)
class ChecklistAnswer:
    """Resposta de uma pergunta.

    Attributes:
        value: True = Sim, False = Não, None = sem resposta (conta como "não ponto").
        source: Automática (dados abertos) ou manual (usuário).
        evidence: Dado que sustentou a resposta automática, para o usuário conferir.
    """

    value: bool | None
    source: AnswerSource | None = None
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class ChecklistWeights:
    """Quanto vale cada resposta na nota do checklist (postura do usuário).

    Fórmula:
        nota = max(0, (Sim x peso_sim − Não x peso_não) / (total x peso_sim))

    O denominador é a nota máxima possível (tudo Sim), então a nota fica entre 0 e 1.
    "Sem resposta" vale 0 nos dois casos. Com o padrão (peso_sim 1, peso_não 0), a nota
    é a fração de "Sim". Com peso_não > 0, cada "Não" desconta pontos: um investidor
    conservador pune os pontos fracos mais do que premia os fortes. Só a razão
    peso_não / peso_sim muda a nota (Sim 0,5 e Não 1 é o mesmo que Sim 1 e Não 2).

    Exemplo (11 perguntas, 7 Sim, 3 Não, 1 sem resposta):
        padrão (1; 0):        7 / 11            = 63,6%
        conservador (1; 2):   (7 − 6) / 11      = 9,1%
    """

    yes: float = 1.0
    no: float = 0.0

    def __post_init__(self) -> None:
        if not 0 < self.yes <= MAX_YES_WEIGHT:
            raise DomainError(f"Peso do Sim deve estar entre 0 (exclusive) e {MAX_YES_WEIGHT:g}.")
        if not 0 <= self.no <= MAX_NO_WEIGHT:
            raise DomainError(f"Peso do Não deve estar entre 0 e {MAX_NO_WEIGHT:g}.")

    @property
    def penalty_ratio(self) -> float:
        """Quantos "Sim" um "Não" anula."""
        return self.no / self.yes

    def score(self, yes: int, no: int, total: int) -> float:
        """Nota de 0 a 1; checklist sem perguntas vale 0."""
        if total <= 0:
            return 0.0
        return max(0.0, (yes * self.yes - no * self.no) / (total * self.yes))
