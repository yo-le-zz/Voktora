"""
Voktora — plugins.lock
Verrou d'intégrité d'un plugin installé depuis le marketplace (`.source.json`).

À l'installation, l'empreinte SHA-256 de chaque fichier est enregistrée. À CHAQUE démarrage, avant
d'exécuter quoi que ce soit, les fichiers sont recomparés : un fichier modifié, ajouté ou supprimé
après coup (par vous, un autre programme, un malware) empêche le chargement du plugin.
Bibliothèque standard uniquement.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

LOCK_NAME = ".source.json"
_IGNORED_DIRS = {"__pycache__"}


def hash_tree(folder: Path) -> dict[str, str]:
    """{chemin relatif: sha256} de tous les fichiers du plugin (hors verrou, dossiers cachés, pycache)."""
    result: dict[str, str] = {}
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder)
        if not path.is_file() or rel.name == LOCK_NAME or path.suffix == ".pyc":
            continue
        if any(part in _IGNORED_DIRS or part.startswith(".") for part in rel.parts):
            continue
        result[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def read_lock(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / LOCK_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_lock(folder: Path, data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".lock-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, folder / LOCK_NAME)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def is_market_install(lock: dict | None) -> bool:
    return bool(lock) and lock.get("origin") == "market" and isinstance(lock.get("files"), dict)


def verify(folder: Path, lock: dict) -> list[str]:
    """Liste des écarts entre le dossier et le verrou (vide = intègre)."""
    expected: dict = lock.get("files", {})
    actual = hash_tree(folder)
    problems = [f"modifié : {name}" for name in sorted(expected) if name in actual and actual[name] != expected[name]]
    problems += [f"supprimé : {name}" for name in sorted(expected) if name not in actual]
    problems += [f"ajouté : {name}" for name in sorted(actual) if name not in expected]
    return problems
