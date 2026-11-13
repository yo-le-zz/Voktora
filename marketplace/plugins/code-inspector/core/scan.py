"""Parcours d'un projet : dossiers ignorés, .gitignore / .voktoraignore (motifs simples), fichiers texte analysables."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from ..analyzers import base

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "target", "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", "dist", "build", ".idea", ".vscode", ".next", ".nuxt", "vendor", "site-packages",
             ".cargo", "coverage", ".eggs", "htmlcov"}
MAX_SIZE = 2 * 1024 * 1024
MAX_FILES = 20000


def read_patterns(root: Path) -> list[str]:
    out = []
    for name in (".gitignore", ".voktoraignore", ".inspectorignore"):
        try:
            for line in (root / name).read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith(("#", "!")):
                    out.append(line)
        except OSError:
            continue
    return out


def ignored(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    for pat in patterns:
        p = pat.rstrip("/")
        if "/" in p.strip("/"):
            if fnmatch.fnmatch(rel, p.lstrip("/")) or fnmatch.fnmatch(rel, p.lstrip("/") + "/*"):
                return True
        elif any(fnmatch.fnmatch(part, p) for part in parts):
            return True
    return False


def scan(root: Path, extra_ignore: list[str] | None = None) -> list[tuple[str, int, int]]:
    """[(chemin relatif, taille, mtime_ns)] des fichiers pour lesquels un analyseur existe."""
    root = Path(root)
    patterns = [*read_patterns(root), *(extra_ignore or [])]
    out: list[tuple[str, int, int]] = []
    for cur, dirs, names in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(cur, root).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info")
                         and not ignored(f"{rel_dir}/{d}".lstrip("/"), patterns))
        for name in sorted(names):
            rel = f"{rel_dir}/{name}".lstrip("/")
            if base.for_file(rel) is None or ignored(rel, patterns):
                continue
            try:
                st = os.stat(os.path.join(cur, name))
            except OSError:
                continue
            if st.st_size > MAX_SIZE:
                continue
            out.append((rel, st.st_size, st.st_mtime_ns))
            if len(out) >= MAX_FILES:
                return out
    return out
