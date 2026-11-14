"""TODO Scanner — analyse pure (sans Qt) : marqueurs dans les commentaires, filtres, exports."""

from __future__ import annotations

import csv
import io
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MARKERS = ("TODO", "FIXME", "HACK", "XXX", "BUG", "OPTIMIZE", "NOTE")
DEFAULT_SKIP = (".git", "node_modules", ".venv", "venv", "__pycache__", "target", "dist", "build", ".idea", ".vscode")
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".xz", ".7z", ".woff", ".woff2", ".ttf",
              ".so", ".dll", ".exe", ".pyc", ".class", ".jar", ".bin", ".sqlite", ".db", ".lock", ".svg", ".mp3", ".mp4"}
# Priorité d'affichage : plus bas = plus urgent.
RANK = {"BUG": 0, "FIXME": 1, "HACK": 2, "XXX": 3, "TODO": 4, "OPTIMIZE": 5, "NOTE": 6}


@dataclass(frozen=True)
class Item:
    kind: str
    path: str          # relatif au projet, séparateurs « / »
    line: int
    text: str
    author: str = ""


def build_pattern(markers) -> re.Pattern:
    """Un marqueur n'est reconnu qu'APRÈS un début de commentaire (#, //, /*, *, --, ;, %, <!--) ou une case Markdown."""
    names = "|".join(re.escape(m) for m in sorted({m.strip().upper() for m in markers if m.strip()}, key=len, reverse=True))
    if not names:
        names = "TODO"
    return re.compile(rf"(?:#+|//+|/\*+|\*+|--|;+|%+|<!--|\"\"\"|'''|[-*]\s*\[[ xX]?\])\s*@?\b({names})\b(?:\(([^)]*)\))?\s*[:\-–]?\s*(.*)$")


def parse_list(text: str, upper: bool = False) -> list[str]:
    parts = [p.strip() for p in re.split(r"[,\s;]+", text or "") if p.strip()]
    return [p.upper() for p in parts] if upper else parts


def scan_file(path: Path, rel: str, pattern: re.Pattern, max_bytes: int = 400_000) -> list[Item]:
    try:
        if path.stat().st_size > max_bytes:
            return []
        data = path.read_bytes()
    except OSError:
        return []
    if b"\x00" in data[:2048]:
        return []
    out = []
    for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), start=1):
        if len(line) > 2000:
            continue
        m = pattern.search(line)
        if m:
            text = re.sub(r"(\*/|-->|\"\"\"|''')\s*$", "", m.group(3)).strip()[:200]
            out.append(Item(m.group(1), rel, number, text, (m.group(2) or "").strip()))
    return out


def scan(root: Path, markers=DEFAULT_MARKERS, skip=DEFAULT_SKIP, max_files: int = 4000, max_bytes: int = 400_000) -> tuple[list[Item], bool]:
    """(éléments, tronqué). Parcours sans suivre les liens, dossiers ignorés élagués d'emblée."""
    pattern, skipped = build_pattern(markers), set(skip)
    items: list[Item] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in skipped)
        for name in sorted(filenames):
            if Path(name).suffix.lower() in BINARY_EXT:
                continue
            seen += 1
            if seen > max_files:
                return sort_items(items), True
            full = Path(dirpath) / name
            if full.is_symlink():
                continue
            items.extend(scan_file(full, full.relative_to(root).as_posix(), pattern, max_bytes))
    return sort_items(items), False


def sort_items(items: list[Item]) -> list[Item]:
    return sorted(items, key=lambda i: (RANK.get(i.kind, 99), i.path, i.line))


def summarize(items: list[Item]) -> dict[str, int]:
    counts = Counter(i.kind for i in items)
    return {k: counts[k] for k in sorted(counts, key=lambda k: RANK.get(k, 99))}


def filter_items(items: list[Item], kind: str = "", query: str = "") -> list[Item]:
    q = query.strip().lower()
    return [i for i in items if (not kind or i.kind == kind)
            and (not q or q in i.text.lower() or q in i.path.lower() or q in i.author.lower())]


def to_markdown(items: list[Item], project: str = "") -> str:
    lines = [f"# Marqueurs à traiter{f' — {project}' if project else ''}", ""]
    if not items:
        return "\n".join([*lines, "_Aucun marqueur._"]) + "\n"
    lines += [f"{len(items)} élément(s) : " + ", ".join(f"{k} {n}" for k, n in summarize(items).items()), ""]
    for kind in summarize(items):
        lines += [f"## {kind}", ""]
        lines += [f"- [ ] `{i.path}:{i.line}` {i.text}" + (f" _({i.author})_" if i.author else "") for i in items if i.kind == kind]
        lines.append("")
    return "\n".join(lines)


def to_csv(items: list[Item]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["type", "fichier", "ligne", "auteur", "texte"])
    for i in items:
        w.writerow([i.kind, i.path, i.line, i.author, i.text])
    return buf.getvalue()
