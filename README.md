# Otimização de Portfólio

Plataforma local de engenharia de dados financeiros, otimização de carteira e métricas
de performance segregadas por estratégia. Dados de mercado em arquitetura medalhão
(Parquet + polars), usuários e carteiras no Supabase (com RLS) e interface em Streamlit.

## Requisitos

- Python 3.12+ e [uv](https://docs.astral.sh/uv/)
- Um projeto Supabase com as migrations de `supabase/migrations/` aplicadas

## Instalação

```bash
uv sync
cp .env.example .env   # preencha SUPABASE_URL e SUPABASE_ANON_KEY
```

## Uso

| Ação | Comando |
|---|---|
| Interface | `uv run streamlit run src/presentation/app.py` |
| Pipeline de dados | `uv run python -m infrastructure.data_engineering.pipeline --tickers EGIE3 BTC CDI` |
| Pipeline a partir de um arquivo de carteira | `uv run python -m infrastructure.data_engineering.pipeline --portfolio-file carteira.txt` |
| Testes | `uv run pytest` |
| Lint e formatação | `uv run ruff check . --fix && uv run ruff format .` |
| Tipagem | `uv run mypy src` |

O pipeline também roda pela interface (botão **Atualizar dados de mercado** na página
Carteira) e é disparado sozinho quando uma importação precisa de cotação. Os fundamentos
do checklist (balanços no Yahoo, cadastro e informes de FII na CVM) são atualizados pelo
botão **Atualizar fundamentos** na Alocação Alvo.

## Importando a carteira

Cole na página **Carteira → Importar posições**, uma posição por linha
(vírgula ou ponto decimal):

```text
# TICKER QUANTIDADE PRECO_MEDIO
EGIE3 2 29,30
MXRF11 35 9,28
# TICKER R$ VALOR_ATUAL [VALOR_INVESTIDO]   (renda fixa, cripto ou qualquer ativo por valor)
CDI R$ 652,46
NTNB-2060 R$ 182,86
BTC R$ 158,00 175,20
# TICKER 0 0   (lista de desejos: ativo que quer ter)
VALE3 0 0
```

Tickers suportados:

| Tipo | Exemplo | Fonte |
|---|---|---|
| Ações, units, ETFs e BDRs da B3 | `PETR4`, `TAEE11`, `AAPL34` | Yahoo Finance (`.SA`) |
| Fundos imobiliários (FII) | `MXRF11`, `HGLG11` | Yahoo Finance (`.SA`); cadastro e informes na CVM |
| REITs americanos e ETFs de REITs | `O`, `PLD`, `VNQ` | Yahoo Finance (USD → BRL pela PTAX) |
| Ações e ETFs americanos | `AAPL`, `IVV`, `AGG` | Yahoo Finance (USD → BRL pela PTAX) |
| Cripto | `BTC`, `ETH` | Yahoo Finance (`-USD` → BRL pela PTAX) |
| CDI | `CDI` | Banco Central (SGS 12), como índice acumulado |
| Tesouro Direto | `NTNB-2060`, `IPCA-2035`, `PRE-2029`, `SELIC-2029` | CSV oficial do Tesouro |

Linhas por valor viram quantidade com a última cotação: `quantidade = valor / preço`.

FIIs e REITs têm classes próprias (**Fundos Imobiliários (FII)**, benchmark IFIX pelo ETF
XFIX11, e **REITs (Internacional)**, benchmark VNQ). Um ticker com final 11 é FII quando
está na lista de FIIs da CVM (baixada em **Atualizar fundamentos**); antes disso, vale o
formato, com exceção das units e ETFs conhecidos. Posições antigas de FII/REIT em renda
variável aparecem com o botão **Mover para a classe imobiliária** na página Carteira.

## Páginas

- **Carteira**: posições valorizadas a mercado, importação, edição de preço médio e, em
  **Editar ou remover posição**, o questionário de importância de cada ativo (inclusive
  os da lista de desejos) e o peso das respostas.
- **Operações**: registro de compras e vendas por estratégia; o preço médio é recalculado.
- **Alocação Alvo**: perfil por classe (soma 100%), atual × alvo e sugestão de aporte.
- **Métricas por Estratégia**: retorno, risco (VaR/CVaR), Sharpe, Sortino, Calmar, Beta,
  curva de patrimônio e drawdown; win rate, payoff e profit factor por estratégia.
- **Otimização**: fronteira eficiente (Markowitz), máximo Sharpe, mínima variância,
  Risk Parity e correlação. A aba **Simulando melhor carteira quant** combina carteira e
  lista de desejos na composição de maior Sharpe (ou menor volatilidade), com teto por
  ativo e, se quiser, o peso de cada classe igual ao perfil alvo; mostra pesos, valores,
  diferença em lotes e como a composição teria se saído na janela.
- **Decisão de aporte** (na Alocação Alvo): por ativo, combinando nota quant (Sharpe,
  Sortino, Calmar) e checklist de perguntas (11 para ações, 6 para FIIs). Respostas
  automáticas por dados abertos (Yahoo Finance e CVM), editáveis; botão **Aportar**
  registra as compras. Ativos com 0 cotas formam a lista de desejos. O **peso das
  respostas** permite uma postura conservadora: cada "Não" desconta pontos
  (`nota = max(0, (Sim × p_sim − Não × p_não) / (perguntas × p_sim))`).
- **Objetivos**: metas de poupança com foco em constância (desafio 1, 2, 3... ou valor
  fixo), com sequência, constância e calendário de depósitos.
- **Guia de Métricas**: fórmula, explicação, exemplo numérico e uso na decisão de cada
  métrica; o "?" de cada KPI leva até ele.

## Arquitetura

Clean Architecture (`Presentation → Application → Domain ← Infrastructure`):

```text
src/
├── domain/          regras puras: entidades, value objects, métricas, otimização
├── application/     use cases e DTOs (pydantic)
├── infrastructure/  Supabase, Parquet, clients de mercado, pipeline medalhão
└── presentation/    Streamlit (app.py = composition root), páginas e gráficos
```

Camadas de dados em `data/` (fora do git):

- **Bronze**: dado bruto por fonte, dia de ingestão e código (somente append).
- **Silver**: preços ajustados e taxas limpos, um snapshot por código.
- **Gold**: preços em BRL, índices de CDI e T-Bill, retornos, volatilidade, drawdowns,
  covariância.

## Limitações conhecidas

- Retornos esperados da otimização são médias históricas da janela, não previsões.
- Títulos do Tesouro com cupom semestral (NTN-B) entram pelo PU; o cupom pago não é
  reinvestido na série, então o retorno é subestimado nas datas de pagamento.
- A métrica da carteira atual usa as quantidades de hoje ao longo da janela inteira,
  limitada pelo ativo com histórico mais curto.
- Métricas por estratégia dependem de operações registradas; posições importadas sem
  operações aparecem só na visão de carteira e por classe.
