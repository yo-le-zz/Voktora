"""Planification cron à 5 champs (minute heure jour mois jour-de-semaine) ; listes, plages, pas ; horloge injectable."""

from __future__ import annotations

from datetime import datetime

RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]


def _field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
            if step < 1:
                raise ValueError("pas invalide")
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = int(part)
            b = hi if step > 1 else a
        if a < lo or b > hi or a > b:
            raise ValueError(f"valeur hors limites ({lo}-{hi}) : {part}")
        out |= set(range(a, b + 1, step))
    return out


def parse(expr: str) -> list[set[int]]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("Une expression cron comporte 5 champs.")
    fields = [_field(p.replace("7", "0") if i == 4 and p == "7" else p, *RANGES[i]) for i, p in enumerate(parts)]
    return fields


def matches(expr: str, when: datetime) -> bool:
    mi, h, d, mo, dow = parse(expr)
    return when.minute in mi and when.hour in h and when.day in d and when.month in mo and (when.isoweekday() % 7) in dow
