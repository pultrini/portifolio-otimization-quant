"""Perguntas qualitativas (checklist) usadas na decisão de aporte.

Cada "Sim" vale um ponto. A nota do checklist é a fração de respostas "Sim".
As perguntas são as definidas pelo usuário; o texto fica aqui para que regra e
interface usem exatamente a mesma definição.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
