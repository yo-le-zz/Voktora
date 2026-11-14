"""Gitignore Generator — logique pure : modèles, détection, fusion sans doublons."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path

_DATA: dict | None = None
HEADER = "# Généré avec Gitignore Generator (Voktora)"


def data() -> dict:
    global _DATA
    if _DATA is None:
        _DATA = json.loads((Path(__file__).parent / "resources" / "templates.json").read_text(encoding="utf-8"))
    return _DATA


def names() -> list[str]:
    return list(data()["templates"])


def detect(files: list[str]) -> list[str]:
    """Modèles suggérés d'après les fichiers du projet (chemins relatifs ; seule la racine et le nom comptent)."""
    basenames = {Path(f).name for f in files}
    found = []
    for name, markers in data()["detect"].items():
        if any(fnmatch.filter(basenames, m) for m in markers):
            found.append(name)
    return found


def section(name: str) -> str:
    return f"# ── {name} ──\n" + "\n".join(data()["templates"][name]) + "\n"


def build(selected: list[str]) -> str:
    ordered = [n for n in names() if n in set(selected)]
    if not ordered:
        return ""
    return HEADER + "\n\n" + "\n".join(section(n) for n in ordered)


def existing_rules(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")}


def merge(existing: str, selected: list[str]) -> str:
    """Ajoute à la fin les sections choisies, sans répéter une règle déjà présente. Le contenu existant n'est jamais modifié."""
    known = existing_rules(existing)
    blocks = []
    for name in (n for n in names() if n in set(selected)):
        new = [r for r in data()["templates"][name] if r not in known]
        if new:
            blocks.append(f"# ── {name} ──\n" + "\n".join(new) + "\n")
            known.update(new)
    if not blocks:
        return existing
    base = existing.rstrip("\n")
    return (base + "\n\n" if base else HEADER + "\n\n") + "\n".join(blocks)
