"""Focus Timer — machine à états Pomodoro et statistiques (sans Qt, testables)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

WORK, SHORT, LONG = "work", "short", "long"
LABELS = {WORK: "Travail", SHORT: "Pause", LONG: "Longue pause"}


def fmt(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class Pomodoro:
    """work → short … → (après `cycles` travaux) long. `tick()` renvoie la phase terminée (ou None)."""

    def __init__(self, work=25, short=5, long=15, cycles=4):
        self.phase, self.done, self.running = WORK, 0, False
        self.configure(work, short, long, cycles)
        self.left = self.work * 60

    def configure(self, work=25, short=5, long=15, cycles=4) -> None:
        self.work, self.short, self.long = max(1, int(work)), max(1, int(short)), max(1, int(long))
        self.cycles = max(1, int(cycles))
        if not self.running:
            self.left = self.duration(self.phase)

    def duration(self, phase: str) -> int:
        return {WORK: self.work, SHORT: self.short, LONG: self.long}[phase] * 60

    def toggle(self) -> bool:
        self.running = not self.running
        return self.running

    def reset(self) -> None:
        self.running = False
        self.left = self.duration(self.phase)

    def _next(self) -> str:
        if self.phase == WORK:
            self.done += 1
            return LONG if self.done % self.cycles == 0 else SHORT
        return WORK

    def skip(self) -> str:
        """Passe à la phase suivante sans compter de session terminée (un travail sauté ne compte pas)."""
        nxt = (SHORT if (self.done + 1) % self.cycles else LONG) if self.phase == WORK else WORK
        self.phase, self.left = nxt, self.duration(nxt)
        return nxt

    def tick(self, seconds: int = 1) -> str | None:
        if not self.running:
            return None
        self.left -= seconds
        if self.left > 0:
            return None
        finished = self.phase
        self.phase = self._next()
        self.left = self.duration(self.phase)
        return finished

    @property
    def position(self) -> int:
        """Numéro du travail en cours dans le cycle (1…cycles)."""
        return self.done % self.cycles + 1 if self.phase == WORK else (self.done - 1) % self.cycles + 1


class Stats:
    """Minutes de travail terminées par jour, dans un petit fichier JSON."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def add(self, minutes: int, day: date | None = None) -> None:
        data = self._load()
        key = (day or date.today()).isoformat()
        row = data.get(key) if isinstance(data.get(key), dict) else {"sessions": 0, "minutes": 0}
        row["sessions"] = int(row.get("sessions", 0)) + 1
        row["minutes"] = int(row.get("minutes", 0)) + int(minutes)
        data[key] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def today(self, day: date | None = None) -> dict:
        row = self._load().get((day or date.today()).isoformat())
        return row if isinstance(row, dict) else {"sessions": 0, "minutes": 0}

    def last_days(self, n: int = 7, today: date | None = None) -> list[tuple[str, int, int]]:
        data, today = self._load(), today or date.today()
        out = []
        for i in range(n - 1, -1, -1):
            d = today - timedelta(days=i)
            row = data.get(d.isoformat()) or {}
            out.append((d.isoformat(), int(row.get("sessions", 0)), int(row.get("minutes", 0))))
        return out

    def to_markdown(self, n: int = 7, today: date | None = None) -> str:
        rows = self.last_days(n, today)
        lines = [f"# Focus — {n} derniers jours", "", "| Jour | Sessions | Minutes |", "|---|---:|---:|"]
        lines += [f"| {d} | {s} | {m} |" for d, s, m in rows]
        total_s, total_m = sum(r[1] for r in rows), sum(r[2] for r in rows)
        lines += ["", f"**Total : {total_s} session(s), {total_m // 60} h {total_m % 60:02d} min.**"]
        return "\n".join(lines) + "\n"
