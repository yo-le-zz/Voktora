"""Project Counter — calculs purs (sans Qt) : libellé, répartition, résumé Markdown, commande cd."""

from __future__ import annotations

import shlex
import sys
from collections import Counter


def plural(n: int, word: str = "projet") -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"


def label(projects: list[dict], fmt: str = "count") -> str:
    n = len(projects)
    if fmt == "short":
        return str(n)
    if fmt == "category":
        cats = {(p.get("category") or "").strip() for p in projects if (p.get("category") or "").strip()}
        return f"{plural(n)} · {plural(len(cats), 'catégorie')}"
    return plural(n)


def breakdown(projects: list[dict], key: str) -> list[tuple[str, int]]:
    counts = Counter((p.get(key) or "").strip() or "—" for p in projects)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))


def tooltip(projects: list[dict]) -> str:
    if not projects:
        return "Aucun projet"
    parts = [f"{name} : {n}" for name, n in breakdown(projects, "category")[:6]]
    return "Par catégorie\n" + "\n".join(parts)


def to_markdown(projects: list[dict]) -> str:
    lines = [f"# Projets ({len(projects)})", ""]
    for title, key in (("Par catégorie", "category"), ("Par statut", "status")):
        rows = breakdown(projects, key)
        if rows:
            lines += [f"## {title}", "", "| Valeur | Projets |", "|---|---:|", *[f"| {n} | {c} |" for n, c in rows], ""]
    lines += ["## Liste", "", *[f"- **{p.get('name', '?')}** — `{p.get('path', '')}`" for p in sorted(projects, key=lambda p: str(p.get('name', '')).lower())]]
    return "\n".join(lines) + "\n"


def cd_command(path: str, platform: str | None = None) -> str:
    """`cd` correctement protégé pour le shell de la plateforme."""
    if (platform or sys.platform) == "win32":
        return 'cd /d "' + str(path).replace('"', "") + '"'
    return "cd " + shlex.quote(str(path))
