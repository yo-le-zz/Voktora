"""Changelog Builder — logique pure : Conventional Commits → sections, rendu Markdown, insertion dans CHANGELOG.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

SEP, END = "\x1f", "\x1e"
SECTIONS = [("breaking", "⚠️ Changements incompatibles"), ("feat", "✨ Nouveautés"), ("fix", "🐛 Corrections"),
            ("perf", "⚡ Performances"), ("refactor", "♻️ Refactorisation"), ("docs", "📚 Documentation"),
            ("test", "✅ Tests"), ("build", "📦 Construction"), ("ci", "🤖 Intégration continue"), ("style", "🎨 Style"),
            ("chore", "🧹 Divers"), ("other", "Autres changements")]
PATTERN = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<desc>.+)$")


@dataclass(frozen=True)
class Commit:
    hash: str
    subject: str
    body: str = ""
    author: str = ""


def log_args(since: str | None, until: str = "HEAD") -> list[str]:
    rng = f"{since}..{until}" if since else until
    return ["git", "log", rng, "--no-merges", f"--format=%h{SEP}%s{SEP}%an{SEP}%b{END}"]


def parse_log(text: str) -> list[Commit]:
    out = []
    for chunk in text.split(END):
        chunk = chunk.strip("\n")
        parts = chunk.split(SEP)
        if len(parts) >= 3 and parts[0].strip():
            out.append(Commit(parts[0].strip(), parts[1].strip(), (parts[3] if len(parts) > 3 else "").strip(), parts[2].strip()))
    return out


def classify(c: Commit) -> tuple[str, str, str]:
    """(section, portée, description). Un « ! » ou « BREAKING CHANGE » dans le corps classe en changement incompatible."""
    m = PATTERN.match(c.subject)
    if not m:
        return ("breaking" if "BREAKING CHANGE" in c.body else "other"), "", c.subject
    kind = m["type"].lower()
    kind = {"feature": "feat", "bugfix": "fix", "perfs": "perf", "doc": "docs", "tests": "test"}.get(kind, kind)
    known = {k for k, _ in SECTIONS}
    section = kind if kind in known and kind not in ("breaking", "other") else "other"
    if m["bang"] or "BREAKING CHANGE" in c.body:
        section = "breaking"
    return section, (m["scope"] or "").strip(), m["desc"].strip()


def group(commits: list[Commit]) -> dict[str, list[tuple[str, str, Commit]]]:
    groups: dict[str, list] = {}
    for c in commits:
        section, scope, desc = classify(c)
        groups.setdefault(section, []).append((scope, desc, c))
    return groups


def render(commits: list[Commit], version: str = "Non publié", day: date | None = None, skip: tuple[str, ...] = ()) -> str:
    """Bloc de changelog pour une version. `skip` : sections à omettre (ex. « chore », « ci »)."""
    groups = group(commits)
    lines = [f"## [{version}] — {(day or date.today()).isoformat()}", ""]
    empty = True
    for key, title in SECTIONS:
        if key in skip or key not in groups:
            continue
        empty = False
        lines += [f"### {title}", ""]
        for scope, desc, c in groups[key]:
            lines.append(f"- {f'**{scope}** : ' if scope else ''}{desc} (`{c.hash}`)")
        lines.append("")
    if empty:
        lines += ["_Aucun changement._", ""]
    return "\n".join(lines)


def insert(existing: str, block: str) -> str:
    """Place `block` avant la première version déjà présente (ou après le titre). N'efface rien."""
    block = block.rstrip("\n") + "\n\n"
    if not existing.strip():
        return "# Changelog\n\n" + block
    m = re.search(r"^## ", existing, flags=re.M)
    if m:
        return existing[:m.start()] + block + existing[m.start():]
    return existing.rstrip("\n") + "\n\n" + block


def next_version(current: str, commits: list[Commit]) -> str:
    """Proposition SemVer : majeur si changement incompatible, mineur si nouveauté, sinon correctif."""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", current or "")
    major, minor, patch = (int(x) for x in m.groups()) if m else (0, 0, 0)
    sections = {classify(c)[0] for c in commits}
    if "breaking" in sections:
        return f"{major + 1}.0.0" if major else f"0.{minor + 1}.0"
    if "feat" in sections:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"
