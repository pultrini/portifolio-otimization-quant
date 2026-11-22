"""Glossário das métricas: ajuda curta ("?"), fórmula, explicação, exemplo e decisão.

Os exemplos numéricos são calculados pelas mesmas funções do domínio usadas no app,
então o guia nunca diverge do que as telas mostram.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import numpy as np

from domain.services import metrics as m
from domain.services.contribution_decision import Candidate, final_score, quant_scores
from domain.services.optimization import (
    AssetUniverse,
    max_sharpe,
    min_variance,
    optimize_constrained,
    risk_contributions,
    risk_parity,
)
from domain.value_objects.asset_class import AssetClass
from domain.value_objects.checklist import ChecklistWeights
from domain.value_objects.ticker import Ticker
from presentation.components.formatting import format_brl, format_number, format_ratio_as_pct

# Série de exemplo: 4 trimestres (4 períodos por ano), benchmark e CDI de 2,5% ao trimestre.
R = np.array([0.10, -0.05, 0.02, -0.10])
B = np.array([0.06, -0.02, 0.01, -0.04])
RF = np.full(4, 0.025)
PPY = 4
PNLS = [Decimal(v) for v in ("100", "-50", "0", "200", "-25")]
UNIVERSE = AssetUniverse(("A", "B"), np.array([0.10, 0.15]), np.diag([0.01, 0.04]))

_SERIES = "r = [+10%, −5%, +2%, −10%] (4 trimestres, 4 períodos por ano)"


def pct(value: float | None) -> str:
    return format_ratio_as_pct(value)


def num(value: float | None) -> str:
    return "—" if value is None else format_number(value, 2)


@dataclass(frozen=True, slots=True)
class MetricDoc:
    key: str
    group: str
    title: str
    short: str  # texto do "?" na tela
    formula: str  # LaTeX
    body: str  # o que é e como interpretar
    decision: str  # como usar em decisões
    example: Callable[[], str]


def _ex_cumulative() -> str:
    return (
        f"{_SERIES}.\n\n(1,10 × 0,95 × 1,02 × 0,90) − 1 = **{pct(m.cumulative_return(R))}**. "
        "Repare que a soma simples dos retornos (−3%) não é o resultado real."
    )


def _ex_cagr() -> str:
    return (
        f"{_SERIES}: acumulado {pct(m.cumulative_return(R))} em 1 ano, então "
        f"CAGR = **{pct(m.cagr(R, PPY))}**. Em 2 anos com +21% acumulado: "
        f"(1,21)^(1/2) − 1 = {pct(m.cagr([0.1, 0.1], 1))} a.a."
    )


def _ex_volatility() -> str:
    return (
        f"{_SERIES}: desvio-padrão por trimestre {pct(float(R.std(ddof=1)))}; "
        f"× √4 = **{pct(m.annualized_volatility(R, PPY))} ao ano**."
    )


def _ex_mdd() -> str:
    curve = m.equity_curve(R)
    path = " → ".join(format_number(v, 4) for v in curve)
    return (
        f"Patrimônio: {path}. Pico 1,1000; vale 0,9593. "
        f"MDD = 0,9593 / 1,1000 − 1 = **{pct(m.max_drawdown(R))}**."
    )


def _ex_var() -> str:
    return (
        f"{_SERIES}. Ordenado: −10%, −5%, +2%, +10%. Com 75% de confiança, o pior 25% é "
        f"a primeira observação: VaR 75% = **{pct(m.historical_var(R, 0.75))}**. Com 50%: "
        f"VaR = {pct(m.historical_var(R, 0.50))} e CVaR = média(−10%, −5%) = "
        f"**{pct(m.historical_cvar(R, 0.50))}**."
    )


def _ex_parametric() -> str:
    return (
        f"{_SERIES}: média −0,75%, desvio {pct(float(R.std(ddof=1)))}. "
        f"VaR 95% normal = −(−0,75% − 1,645 × desvio) = **{pct(m.parametric_var(R, 0.95))}**; "
        f"CVaR 95% = **{pct(m.parametric_cvar(R, 0.95))}**."
    )


def _ex_sharpe() -> str:
    return (
        f"{_SERIES}, CDI 2,5% por trimestre. Excesso médio −3,25%; desvio do excesso "
        f"{pct(float((R - RF).std(ddof=1)))}. Sharpe = −3,25% / desvio × √4 = "
        f"**{num(m.sharpe_ratio(R, RF, PPY))}**."
    )


def _ex_sortino() -> str:
    return (
        f"{_SERIES}, CDI 2,5%. Só os excessos negativos entram no denominador "
        "(−7,5%, −0,5%, −12,5% e o +7,5% vira 0). "
        f"Sortino = **{num(m.sortino_ratio(R, RF, PPY))}**."
    )


def _ex_calmar() -> str:
    return (
        f"CAGR {pct(m.cagr(R, PPY))} / |MDD {pct(m.max_drawdown(R))}| = "
        f"**{num(m.calmar_ratio(R, PPY))}**."
    )


def _ex_beta() -> str:
    return (
        f"{_SERIES}; benchmark b = [+6%, −2%, +1%, −4%]. "
        f"β = cov(r, b) / var(b) = **{num(m.beta(R, B))}**: o ativo amplificou os movimentos "
        "do benchmark."
    )


def _ex_trades() -> str:
    s = m.trade_statistics(PNLS)
    return (
        "Resultados de 5 operações: +R$ 100, −R$ 50, R$ 0, +R$ 200, −R$ 25.\n\n"
        f"- Win rate: 2 ganhos / 5 = **{pct(s.win_rate)}**\n"
        f"- Ganho médio {format_brl(s.average_win)}, perda média {format_brl(s.average_loss)} → "
        f"payoff **{num(s.payoff_ratio)}**\n"
        f"- Profit factor: 300 / 75 = **{num(s.profit_factor)}**\n"
        f"- Expectativa: 225 / 5 = **{format_brl(s.expectancy)}** por operação"
    )


def _ex_frontier() -> str:
    low = min_variance(UNIVERSE, 0.05)
    top = max_sharpe(UNIVERSE, 0.05)
    return (
        "Dois ativos não correlacionados: A (retorno 10%, volatilidade 10%) e B (15%, 20%), "
        "taxa livre de risco 5%.\n\n"
        f"- Mínima variância: {pct(float(low.weights[0]))} em A, volatilidade "
        f"**{pct(low.volatility)}** (menor que a de A sozinho: diversificação).\n"
        f"- Máximo Sharpe: {pct(float(top.weights[0]))} em A e {pct(float(top.weights[1]))} "
        f"em B; Sharpe **{num(top.sharpe)}**."
    )


def _ex_parity() -> str:
    parity = risk_parity(UNIVERSE, 0.05)
    rc = risk_contributions(UNIVERSE, parity.weights)
    return (
        "Mesmos ativos A (vol 10%) e B (vol 20%), sem correlação: pesos ∝ 1/σ → "
        f"{pct(float(parity.weights[0]))} em A e {pct(float(parity.weights[1]))} em B. "
        f"Contribuições de risco: {pct(float(rc[0]))} e {pct(float(rc[1]))}."
    )


def _ex_correlation() -> str:
    returns = np.array([[0.1, 0.0], [0.0, 0.1], [0.1, 0.0]])
    corr = float(np.corrcoef(returns, rowvar=False)[0, 1])
    return (
        "Dois ativos que sobem em dias alternados — A: +10%, 0%, +10%; B: 0%, +10%, 0% — "
        f"têm correlação **{num(corr)}**: um compensa o outro, e a carteira com os dois "
        "oscila menos que cada um."
    )


def _ex_quant() -> str:
    a = Candidate(Ticker("AAAA3"), AssetClass.BR_EQUITY, Decimal(0), Decimal(10), (1.0, 1.5, 2.0))
    b = Candidate(Ticker("BBBB3"), AssetClass.BR_EQUITY, Decimal(0), Decimal(10), (0.5, 2.0, None))
    c = Candidate(Ticker("CCCC3"), AssetClass.BR_EQUITY, Decimal(0), Decimal(10), (None, 1.0, 1.0))
    scores = quant_scores([a, b, c])
    return (
        "Três ações com (Sharpe, Sortino, Calmar): A (1,0; 1,5; 2,0), B (0,5; 2,0; —), "
        "C (—; 1,0; 1,0). Posições de 0 (pior) a 1 (melhor) em cada métrica:\n\n"
        f"- A: Sharpe 1, Sortino 0,5, Calmar 1 → **{num(scores[Ticker('AAAA3')])}**\n"
        f"- B: 0,5, 1, 0 → **{num(scores[Ticker('BBBB3')])}**\n"
        f"- C: 0, 0, 0,5 → **{num(scores[Ticker('CCCC3')])}**\n\n"
        f"Com checklist 8/11 (72,7) e peso quant 50%, a nota final de A é "
        f"**{num(final_score(scores[Ticker('AAAA3')], 800 / 11, 0.5))}**."
    )


def _ex_ideal_weight() -> str:
    return (
        "Notas finais 80 (A) e 20 (B): pesos ideais 80% e 20%. Classe com R$ 0 e aporte de "
        "R$ 100: alvos R$ 80 e R$ 20. Com A a R$ 10 e B a R$ 7: 8 cotas de A e 2 de B "
        "(R$ 94); sobram R$ 6, menos que uma cota de qualquer um."
    )


def _ex_checklist_weights() -> str:
    def score(yes_w: float, no_w: float) -> str:
        return num(ChecklistWeights(yes_w, no_w).score(7, 3, 11) * 100)

    return (
        "Ação com 11 perguntas: 7 Sim, 3 Não e 1 sem resposta.\n\n"
        f"- Padrão (Sim 1; Não 0): 7 / 11 → **{score(1, 0)}**\n"
        f"- Equilibrado (1; 1): (7 − 3) / 11 → **{score(1, 1)}**\n"
        f"- Conservador (1; 2): (7 − 6) / 11 → **{score(1, 2)}**\n"
        f"- Muito conservador (1; 3): (7 − 9) / 11 < 0 → **{score(1, 3)}**"
    )


def _ex_simulation() -> str:
    universe = AssetUniverse(
        ("A", "B", "C"), np.array([0.25, 0.12, 0.08]), np.diag([0.04, 0.0225, 0.01])
    )
    free = optimize_constrained(universe, 0.05)
    capped = optimize_constrained(universe, 0.05, max_weight=0.4)
    weights = ", ".join(pct(w) for w in capped.weights)
    return (
        "Três ativos com retornos 25%, 12% e 8% e volatilidades 20%, 15% e 10% "
        "(sem correlação), CDI 5%.\n\n"
        f"- Sem teto: pesos {', '.join(pct(w) for w in free.weights)}, Sharpe "
        f"**{num(free.sharpe)}**\n"
        f"- Teto de 40% por ativo: pesos {weights}, Sharpe **{num(capped.sharpe)}**\n\n"
        "O teto custa um pouco de Sharpe no passado em troca de uma carteira menos "
        "dependente das estimativas."
    )


DOCS: tuple[MetricDoc, ...] = (
    MetricDoc(
        "cumulative_return",
        "Retorno",
        "Retorno acumulado",
        "Quanto o patrimônio cresceu no período, com juros compostos. É o resultado final, "
        "sem considerar quanto risco foi corrido.",
        r"R = \prod_{t=1}^{n} (1 + r_t) - 1",
        "Multiplica os fatores de crescimento de cada período. A soma simples dos retornos "
        "erra porque ignora que o ganho de um período rende no seguinte.",
        "Use para saber o resultado; nunca sozinho para comparar ativos, porque não diz o "
        "risco nem o tempo. Compare sempre com o benchmark do mesmo período.",
        _ex_cumulative,
    ),
    MetricDoc(
        "cagr",
        "Retorno",
        "CAGR",
        "Taxa anual composta equivalente ao retorno do período. Permite comparar períodos "
        "de durações diferentes na mesma régua (% ao ano).",
        r"CAGR = (1 + R)^{\frac{p}{n}} - 1",
        "p é o número de períodos por ano (252 dias úteis, 365 para cripto) e n o número de "
        "períodos observados. É a taxa constante que levaria ao mesmo resultado.",
        "Compare o CAGR com o CDI e com o benchmark: um CAGR abaixo do CDI significa que a "
        "renda fixa sem risco teria rendido mais no período.",
        _ex_cagr,
    ),
    MetricDoc(
        "volatility",
        "Risco",
        "Volatilidade anualizada",
        "Quanto os retornos oscilam em torno da média, em % ao ano. Mede a incerteza do "
        "caminho, não a perda final.",
        r"\sigma_{anual} = \sigma(r) \cdot \sqrt{p}",
        "Desvio-padrão amostral dos retornos por período, multiplicado pela raiz do número de "
        "períodos por ano (a variância cresce linearmente com o tempo).",
        "Mais volatilidade exige mais estômago e mais prazo. Use para dimensionar a "
        "posição: ativos muito voláteis pedem peso menor na carteira.",
        _ex_volatility,
    ),
    MetricDoc(
        "max_drawdown",
        "Risco",
        "Maximum drawdown",
        "A maior queda do pico ao vale no período. Responde: quanto eu teria perdido se "
        "comprasse no pior momento e vendesse no fundo?",
        r"MDD = \min_t \left( \frac{V_t}{\max_{s \le t} V_s} - 1 \right)",
        "V é o patrimônio normalizado. O gráfico underwater mostra essa queda em cada data; "
        "zero significa estar no topo histórico.",
        "É a métrica mais próxima da dor real do investidor. Pergunte-se se aguentaria essa "
        "queda sem vender: se não, reduza o peso do ativo.",
        _ex_mdd,
    ),
    MetricDoc(
        "var",
        "Risco",
        "VaR histórico",
        "Perda de um período que só foi superada em (1 − c) dos casos. VaR 95% diário de 2% "
        "= em 95% dos dias a perda foi menor que 2%.",
        r"VaR_c = -Q_{1-c}(r)",
        "Q é o quantil empírico dos retornos (método conservador: usa uma observação real). "
        "Reportado como perda positiva. Sem perda no quantil, não há VaR.",
        "Use para limites de risco: quanto posso perder num dia ruim normal. Não diz nada "
        "sobre os dias além do quantil — para isso, veja o CVaR.",
        _ex_var,
    ),
    MetricDoc(
        "cvar",
        "Risco",
        "CVaR (Expected Shortfall)",
        "Perda média nos piores (1 − c) dos períodos. Mede a cauda que o VaR ignora.",
        r"CVaR_c = -\mathbb{E}\left[ r \mid r \le Q_{1-c}(r) \right]",
        "Média dos retornos iguais ou piores que o quantil do VaR, como perda positiva.",
        "Quando o CVaR é muito maior que o VaR, as perdas extremas são desproporcionais "
        "(cauda gorda): é o caso típico de cripto e de ações em crise.",
        _ex_var,
    ),
    MetricDoc(
        "parametric",
        "Risco",
        "VaR e CVaR paramétricos",
        "As mesmas medidas supondo retornos normais (sino). Mais estáveis, mas subestimam "
        "perdas extremas quando a cauda é gorda.",
        r"VaR_c = -(\mu + z_{1-c}\,\sigma),\quad "
        r"CVaR_c = -\left(\mu - \sigma\frac{\varphi(z_{1-c})}{1-c}\right)",
        "μ e σ são média e desvio dos retornos; z é o quantil da normal padrão (−1,645 para "
        "95%) e φ a densidade normal.",
        "Compare com o histórico: paramétrico bem menor que o histórico indica que a "
        "normal está escondendo risco de cauda.",
        _ex_parametric,
    ),
    MetricDoc(
        "sharpe",
        "Risco-retorno",
        "Índice de Sharpe",
        "Retorno acima da taxa livre de risco por unidade de volatilidade. Diz se o risco "
        "corrido foi pago.",
        r"Sharpe = \frac{\overline{r - r_f}}{\sigma(r - r_f)} \cdot \sqrt{p}",
        "r_f é o CDI (Brasil) ou o T-Bill 3M (exterior) no mesmo período. Negativo significa "
        "que a renda fixa sem risco rendeu mais.",
        "Para escolher entre ativos ou carteiras, prefira o maior Sharpe: mais retorno pelo "
        "mesmo risco. É a métrica que o otimizador maximiza.",
        _ex_sharpe,
    ),
    MetricDoc(
        "sortino",
        "Risco-retorno",
        "Índice de Sortino",
        "Como o Sharpe, mas só penaliza a volatilidade ruim (abaixo da taxa livre de risco). "
        "Oscilações para cima não contam como risco.",
        r"Sortino = \frac{\overline{r - r_f}}{\sqrt{\overline{\min(r - r_f, 0)^2}}} \cdot \sqrt{p}",
        "O denominador é o desvio negativo (downside deviation) em relação à taxa livre de "
        "risco, calculado sobre todas as observações.",
        "Útil para ativos assimétricos: Sortino muito maior que Sharpe indica que a "
        "volatilidade vem mais de altas do que de quedas.",
        _ex_sortino,
    ),
    MetricDoc(
        "calmar",
        "Risco-retorno",
        "Índice de Calmar",
        "Retorno anual por unidade de pior queda. Mede quanto o ativo paga pelo maior "
        "susto do período.",
        r"Calmar = \frac{CAGR}{|MDD|}",
        "Sem drawdown no período não há Calmar (divisão por zero).",
        "Calmar acima de 1 significa que um ano de retorno cobre a pior queda. Bom critério "
        "para quem tem baixa tolerância a perdas grandes.",
        _ex_calmar,
    ),
    MetricDoc(
        "beta",
        "Risco-retorno",
        "Beta",
        "Sensibilidade aos movimentos do benchmark da classe. Beta 1,2 = em média, sobe ou "
        "cai 1,2% quando o benchmark move 1%.",
        r"\beta = \frac{\mathrm{cov}(r, r_b)}{\mathrm{var}(r_b)}",
        "Benchmarks: IBOV, S&P 500, CDI, US Aggregate Bond, BTC (tabela 5.1). Contra a própria "
        "taxa livre de risco (renda fixa vs. CDI) o beta não tem sentido e não é exibido.",
        "Beta alto amplifica o mercado (bom na alta, ruim na queda). Para proteger a "
        "carteira, combine ativos de beta baixo ou negativo.",
        _ex_beta,
    ),
    MetricDoc(
        "trade_stats",
        "Eficiência operacional",
        "Win rate, payoff, profit factor e expectativa",
        "Qualidade das operações fechadas, líquidas de custos. Win rate alto não basta: "
        "o tamanho dos ganhos e das perdas importa tanto quanto a frequência.",
        r"E = WR \cdot \bar{G} - (1 - WR) \cdot |\bar{P}|, \quad PF = \frac{\sum G}{|\sum P|}",
        "Operações fechadas por FIFO dentro da mesma estratégia, com custos rateados. Day "
        "trade = compra e venda no mesmo pregão (horário de Brasília).",
        "Expectativa positiva é o requisito mínimo de uma estratégia. Profit factor abaixo "
        "de 1 = a estratégia perde dinheiro; acima de 1,5 é considerado robusto.",
        _ex_trades,
    ),
    MetricDoc(
        "frontier",
        "Otimização",
        "Fronteira eficiente, mínima variância e máximo Sharpe",
        "Conjunto de carteiras com o menor risco para cada retorno esperado. Abaixo dela, "
        "há carteiras melhores com o mesmo risco.",
        r"\min_w w^\top \Sigma w \;\; \text{s.a.} \;\; "
        r"\textstyle\sum w = 1,\; w^\top \mu = \mu^*,\; w \ge 0",
        "μ e Σ são estimados pela média e covariância históricas da janela. Mínima variância "
        "é a ponta esquerda; máximo Sharpe é onde a reta a partir do CDI toca a fronteira.",
        "Se a carteira atual está bem abaixo da fronteira, existe combinação dos mesmos "
        "ativos com mais retorno pelo mesmo risco. Lembre: é o ótimo do passado, não previsão.",
        _ex_frontier,
    ),
    MetricDoc(
        "risk_parity",
        "Otimização",
        "Risk Parity",
        "Carteira em que cada ativo contribui igualmente para o risco total. Não depende de "
        "retornos esperados, só de volatilidades e correlações.",
        r"RC_i = \frac{w_i (\Sigma w)_i}{w^\top \Sigma w} = \frac{1}{n}",
        "Resolvida pela formulação convexa de Spinu (solução única). Ativos menos voláteis "
        "recebem mais peso.",
        "Alternativa robusta quando não se confia nos retornos históricos. Renda fixa quase "
        "sem volatilidade domina a carteira — por isso ela fica fora por padrão.",
        _ex_parity,
    ),
    MetricDoc(
        "correlation",
        "Otimização",
        "Correlação",
        "Quanto dois ativos se movem juntos, de −1 (opostos) a +1 (iguais). Diversificar é "
        "combinar ativos com correlação baixa.",
        r"\rho_{ij} = \frac{\mathrm{cov}(r_i, r_j)}{\sigma_i \sigma_j}",
        "Calculada sobre os retornos nas datas em que os dois negociaram.",
        "Dois ativos com correlação perto de 1 são quase o mesmo risco: ter os dois "
        "pouco diversifica. Prefira adicionar ativos com correlação baixa com a carteira.",
        _ex_correlation,
    ),
    MetricDoc(
        "quant_simulation",
        "Otimização",
        "Simulação da melhor carteira quant",
        "Combina todos os ativos possíveis (carteira e lista de desejos) na composição de maior "
        "Sharpe (ou menor volatilidade) no período, com teto por ativo e, se quiser, o peso "
        "de cada classe igual ao seu perfil alvo.",
        r"\max_w \frac{w^\top \mu - r_f}{\sqrt{w^\top \Sigma w}}\ \text{s.a.}\ "
        r"\sum_i w_i = 1,\ 0 \le w_i \le teto,\ \sum_{i \in c} w_i = alvo_c",
        "μ e Σ são estimados com os retornos diários da janela. O teto por ativo evita "
        "concentrar tudo em um ou dois ativos (Markowitz puro é muito sensível a erros em "
        "μ); se o teto não deixar a soma fechar em 100%, ele é relaxado para o mínimo "
        "viável. Respeitando o perfil, a decisão entre classes é sua e a otimização só "
        "escolhe a composição dentro delas.",
        "É o que teria funcionado melhor no período, não uma previsão nem recomendação. "
        "Use para ver quais ativos desejados melhorariam a relação risco-retorno e onde a "
        "carteira está concentrada; confirme com o checklist antes de mudar algo.",
        _ex_simulation,
    ),
    MetricDoc(
        "quant_score",
        "Decisão de aporte",
        "Nota quant, checklist e nota final",
        "Nota quant (0-100): posição média do ativo em Sharpe, Sortino e Calmar entre os "
        "candidatos da classe. Checklist: nota das respostas com os seus pesos de Sim e Não. "
        "Nota final: média ponderada das duas.",
        r"Nota = w_q \cdot Q + (1 - w_q) \cdot C",
        "A nota quant é relativa: compara os candidatos entre si. Empates recebem a posição "
        "média. C é a nota do checklist (veja Peso das respostas do checklist).",
        "Ajuste o peso quant conforme sua confiança: mais peso no checklist favorece "
        "qualidade do negócio; mais peso no quant favorece o histórico de risco-retorno.",
        _ex_quant,
    ),
    MetricDoc(
        "ideal_weight",
        "Decisão de aporte",
        "Peso ideal e compras sugeridas",
        "Dentro de cada classe, cada ativo deve pesar proporcionalmente à sua nota final. O "
        "aporte vai para quem está mais abaixo desse peso.",
        r"w_i^* = \frac{Nota_i}{\sum_j Nota_j},\quad Alvo_i = w_i^* \cdot (V_{classe} + Aporte)",
        "O valor da classe vem do perfil alvo; dentro dela, o enchimento de nível reduz "
        "primeiro os maiores déficits. Quantidades são arredondadas para lotes negociáveis e "
        "o troco compra lotes extras de quem ficou mais longe do alvo.",
        "Ativos acima do peso ideal aguardam: não recebem aporte até os demais alcançarem. "
        "FII com P/VP acima de 1,5 é descartado em qualquer hipótese.",
        _ex_ideal_weight,
    ),
    MetricDoc(
        "checklist_weights",
        "Decisão de aporte",
        "Peso das respostas do checklist",
        "Quanto vale cada Sim e quanto desconta cada Não. Com o Não pesando mais que o Sim, "
        "um ponto fraco derruba mais a nota: postura conservadora.",
        r"C = \max\left(0,\ \frac{\#Sim \cdot p_{sim} - \#Não \cdot p_{não}}"
        r"{\#Perguntas \cdot p_{sim}}\right) \cdot 100",
        "O denominador é a nota máxima (tudo Sim), então C fica entre 0 e 100. Sem resposta "
        "não soma nem desconta. Só a razão p_não / p_sim importa: Sim 0,5 e Não 1 dá a "
        "mesma nota que Sim 1 e Não 2. O padrão (1; 0) é a fração de Sim.",
        "Use uma postura conservadora quando um defeito (dívida alta, governança ruim) pesa "
        "mais para você do que uma qualidade. Os pesos valem para todos os ativos e ficam "
        "salvos na sua conta.",
        _ex_checklist_weights,
    ),
)

DOCS_BY_KEY = {doc.key: doc for doc in DOCS}


def help_text(key: str) -> str:
    """Texto do "?" de uma métrica."""
    return DOCS_BY_KEY[key].short
