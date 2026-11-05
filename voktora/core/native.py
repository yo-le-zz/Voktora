"""
Voktora — core.native
Passerelle vers l'extension Rust optionnelle `voktora_native` (dossier `native/`).

Chaque fonction a un équivalent en Python pur, utilisé quand l'extension n'est pas installée
(développement sans Rust, plateforme non prévue…) ou désactivée avec `VOKTORA_NO_NATIVE=1`.
Les deux implémentations doivent rester équivalentes : voir tests/test_native.py, qui les compare.

Pourquoi Rust ici : parcourir et copier de gros dossiers (des dizaines de milliers de petits
fichiers) est dominé par les appels système ; l'extension les parallélise sur plusieurs threads
sans GIL, ce que Python ne sait pas faire.
"""

from __future__ import annotations

import os
import zlib
from collections.abc import Callable, Sequence
from pathlib import Path

from . import constants

try:                                    # pragma: no cover - dépend de l'environnement de build
    if os.environ.get("VOKTORA_NO_NATIVE") == "1":
        raise ImportError("extension native désactivée par VOKTORA_NO_NATIVE=1")
    import voktora_native as _native
except ImportError:                     # pragma: no cover
    _native = None

BytesCallback = Callable[[int, str], None]
CancelCheck = Callable[[], bool]


def native_available() -> bool:
    return _native is not None


def native_backend() -> str:
    """« rust » si l'extension est chargée, sinon « python »."""
    return "rust" if _native is not None else "python"


def native_version() -> str:
    return _native.version() if _native is not None else ""


# ──────────────────────────────────────────────
# PARCOURS
# ──────────────────────────────────────────────

def tree_size_python(folder: Path | str) -> tuple[int, int]:
    """(nombre de fichiers, taille totale en octets) d'un dossier, liens non suivis."""
    count = total = 0
    stack = [os.fspath(folder)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            # Lien vers un dossier : ignoré ; lien vers un fichier : compté, taille 0.
                            if not entry.is_dir():
                                count += 1
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            count += 1
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        count += 1
        except OSError:
            continue
    return count, total


def tree_size(folder: Path | str) -> tuple[int, int]:
    if _native is not None:
        return _native.scan_tree(os.fspath(folder))
    return tree_size_python(folder)


# ──────────────────────────────────────────────
# COPIE
# ──────────────────────────────────────────────

def copy_tree_native(src: Path, dst: Path, on_bytes: BytesCallback | None = None,
                     cancel: CancelCheck | None = None, threads: int = 0) -> tuple[int, int] | None:
    """Copie parallèle (Rust). Retourne None si l'extension est absente : l'appelant copie alors en Python.

    `on_bytes(octets_ajoutés, nom)` est appelé depuis le thread appelant ; si `cancel()` est vrai,
    OperationCancelled est levée (l'extension arrête proprement ses threads).
    """
    if _native is None:
        return None
    done = 0

    def callback(total: int, name: str) -> bool:
        nonlocal done
        if on_bytes is not None and total > done:
            on_bytes(total - done, name)
        done = total
        if cancel is not None and cancel():
            raise constants.OperationCancelled("Opération annulée.")
        return True

    result = _native.copy_tree(os.fspath(src), os.fspath(dst), callback, threads)
    if result is None:                  # pragma: no cover - le callback lève déjà OperationCancelled
        raise constants.OperationCancelled("Opération annulée.")
    return result


# ──────────────────────────────────────────────
# HACHAGE
# ──────────────────────────────────────────────

def _crc32_one(path: str) -> int | None:
    try:
        crc = 0
        with open(path, "rb") as handle:
            while block := handle.read(1024 * 1024):
                crc = zlib.crc32(block, crc)
        return crc
    except OSError:
        return None


def crc32_files(paths: Sequence[Path | str], threads: int = 0) -> list[int | None]:
    """CRC32 (identique à `zlib.crc32`) de chaque fichier ; None pour un fichier illisible.

    Sans l'extension, les gros lots sont répartis sur plusieurs processus (voir core.parallel).
    """
    names = [os.fspath(p) for p in paths]
    if _native is not None:
        return _native.crc32_files(names, threads)
    from . import parallel
    return parallel.process_map(_crc32_one, names, workers=threads or None, min_items=64)

