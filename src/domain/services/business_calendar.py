"""Calendário de dias úteis brasileiro (feriados nacionais, padrão ANBIMA).

O Tesouro Direto precifica os títulos em dias úteis na base 252: o expoente de
desconto é du / 252, com du contado entre a data de liquidação (inclusive) e o
vencimento (exclusive). Os feriados são os nacionais usados pela ANBIMA: datas fixas,
os móveis ligados à Páscoa (Carnaval, Sexta-feira Santa, Corpus Christi) e o Dia da
Consciência Negra, feriado nacional desde 2024.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import cache

import numpy as np

# (mês, dia) dos feriados nacionais de data fixa.
_FIXED: tuple[tuple[int, int], ...] = (
    (1, 1),  # Confraternização Universal
    (4, 21),  # Tiradentes
    (5, 1),  # Dia do Trabalho
    (9, 7),  # Independência
    (10, 12),  # Nossa Senhora Aparecida
    (11, 2),  # Finados
    (11, 15),  # Proclamação da República
    (12, 25),  # Natal
)
_BLACK_CONSCIOUSNESS_SINCE = 2024  # 20/11 (Lei 14.759/2023)


def easter(year: int) -> date:
    """Domingo de Páscoa pelo algoritmo de Meeus/Jones/Butcher (calendário gregoriano)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month, day = divmod(h + l_ - 7 * m + 114, 31)
    return date(year, month, day + 1)


@cache
def holidays(year: int) -> frozenset[date]:
    """Feriados nacionais do ano."""
    days = {date(year, month, day) for month, day in _FIXED}
    if year >= _BLACK_CONSCIOUSNESS_SINCE:
        days.add(date(year, 11, 20))
    sunday = easter(year)
    days.update(
        {
            sunday - timedelta(days=48),  # segunda de Carnaval
            sunday - timedelta(days=47),  # terça de Carnaval
            sunday - timedelta(days=2),  # Sexta-feira Santa
            sunday + timedelta(days=60),  # Corpus Christi
        }
    )
    return frozenset(days)


def business_days(start: date, end: date) -> int:
    """Dias úteis em [start, end): conta start e exclui end, como na convenção do Tesouro.

    Returns:
        0 quando end <= start.
    """
    if end <= start:
        return 0
    feriados = [d for year in range(start.year, end.year + 1) for d in holidays(year)]
    return int(np.busday_count(start, end, holidays=feriados))


def add_business_days(start: date, days: int) -> date:
    """Data `days` dias úteis depois de `start` (liquidação D+1 do Tesouro, por exemplo)."""
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5 and current not in holidays(current.year):
            remaining -= 1
    return current
