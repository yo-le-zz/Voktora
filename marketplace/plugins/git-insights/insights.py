"""Git Insights — collecte et mise en forme (sans Qt). `run(args) -> (code, texte)` est injecté : testable avec un vrai dépôt."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

SEP = "\x1f"


def _out(run, *args, keep_indent: bool = False) -> str:
    code, text = run(["git", *args])
    if code != 0:
        return ""
    return text.rstrip() if keep_indent else text.strip()      # « status --porcelain » : l'espace de tête est significatif


def parse_porcelain(text: str) -> dict[str, int]:
    staged = modified = untracked = 0
    for line in text.splitlines():
        if line.startswith("??"):
            untracked += 1
            continue
        if line[:1] not in (" ", "?", ""):
            staged += 1
        if line[1:2] not in (" ", ""):
            modified += 1
    return {"staged": staged, "modified": modified, "untracked": untracked}


def parse_shortlog(text: str, limit: int = 8) -> list[tuple[str, int]]:
    rows = []
    for line in text.splitlines():
        parts = line.strip().split("\t", 1)
        if len(parts) == 2 and parts[0].isdigit():
            name = parts[1].split(" <")[0].strip()
            rows.append((name, int(parts[0])))
    return rows[:limit]


def parse_log(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        parts = line.split(SEP)
        if len(parts) >= 4:
            out.append({"hash": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]})
    return out


def weekly_activity(dates: list[str], weeks: int = 12, today: date | None = None) -> list[tuple[str, int]]:
    """Commits par semaine (lundi de la semaine) sur les `weeks` dernières semaines, de la plus ancienne à la plus récente."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    starts = [monday - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    counts = Counter()
    for raw in dates:
        try:
            d = date.fromisoformat(raw.strip())
        except ValueError:
            continue
        counts[d - timedelta(days=d.weekday())] += 1
    return [(s.strftime("%d/%m"), counts.get(s, 0)) for s in starts]


def hot_files(names: str, limit: int = 8) -> list[tuple[str, int]]:
    counts = Counter(line.strip() for line in names.splitlines() if line.strip())
    return counts.most_common(limit)


def bar(value: int, maximum: int, width: int = 20) -> str:
    if maximum <= 0 or value <= 0:
        return ""
    return "█" * max(1, round(width * value / maximum))


def collect(run) -> dict:
    if _out(run, "rev-parse", "--is-inside-work-tree") != "true":
        return {"repo": False}
    ahead = behind = None
    counts = _out(run, "rev-list", "--left-right", "--count", "@{u}...HEAD").split()
    if len(counts) == 2 and all(c.isdigit() for c in counts):
        behind, ahead = int(counts[0]), int(counts[1])
    data = {
        "repo": True,
        "branch": _out(run, "rev-parse", "--abbrev-ref", "HEAD") or "?",
        "commits": int(_out(run, "rev-list", "--count", "HEAD") or 0) if _out(run, "rev-parse", "--verify", "-q", "HEAD") else 0,
        "remote": _out(run, "config", "--get", "remote.origin.url"),
        "tag": _out(run, "describe", "--tags", "--abbrev=0"),
        "ahead": ahead, "behind": behind,
        "status": parse_porcelain(_out(run, "status", "--porcelain", keep_indent=True)),
        "authors": parse_shortlog(_out(run, "shortlog", "-sne", "--no-merges", "HEAD")),
        "recent": parse_log(_out(run, "log", "-n", "15", f"--format=%h{SEP}%an{SEP}%ad{SEP}%s", "--date=short")),
        "activity": weekly_activity(_out(run, "log", "--since=90.days", "--format=%ad", "--date=short").splitlines()),
        "hot": hot_files(_out(run, "log", "--since=90.days", "--name-only", "--format=")),
    }
    return data


def to_markdown(d: dict, name: str = "") -> str:
    if not d.get("repo"):
        return "Ce dossier n'est pas un dépôt Git."
    s = d["status"]
    lines = [f"# Git — {name}" if name else "# Git", "",
             f"- Branche : **{d['branch']}**" + (f" (↑{d['ahead']} ↓{d['behind']})" if d["ahead"] is not None else ""),
             f"- Commits : {d['commits']}" + (f" · dernière étiquette {d['tag']}" if d["tag"] else ""),
             f"- Modifications : {s['staged']} indexé(s), {s['modified']} modifié(s), {s['untracked']} non suivi(s)"]
    if d["remote"]:
        lines.append(f"- Distant : {d['remote']}")
    if d["authors"]:
        lines += ["", "## Auteurs", *[f"- {n} — {c}" for n, c in d["authors"]]]
    if d["hot"]:
        lines += ["", "## Fichiers les plus modifiés (90 jours)", *[f"- `{f}` — {c}" for f, c in d["hot"]]]
    if d["recent"]:
        lines += ["", "## Derniers commits", *[f"- `{c['hash']}` {c['date']} {c['subject']} ({c['author']})" for c in d["recent"]]]
    return "\n".join(lines) + "\n"
