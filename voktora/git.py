"""
git.py — Git automation Voktora
Version : 1.0.1
Auto-commit, auto-push, smart commit messages (Conventional Commits sans IA).
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Callable


# ── Smart commit message ───────────────────────────────────────────────────────

_CONVENTIONAL_TYPES = {
    re.compile(r"\.(py|js|ts|rs|go|cpp|c|java|kt|rb)$"): "feat",
    re.compile(r"\.(md|rst|txt)$"):                       "docs",
    re.compile(r"\.(css|scss|less|html|svg)$"):           "style",
    re.compile(r"test_|_test\.|spec\.|\.spec\."):         "test",
    re.compile(r"requirements|package\.json|Cargo\.toml|go\.mod|CMake"): "build",
    re.compile(r"\.github|\.gitignore|\.env|Dockerfile"):               "ci",
    re.compile(r"fix|bug|patch|hotfix", re.I):                          "fix",
}


def smart_commit_message(project_path: Path) -> str:
    """
    Génère un message de commit Conventional Commits en analysant
    les fichiers stagés / modifiés (sans IA, 100% local).
    """
    staged  = _git_output(project_path, ["git", "diff", "--name-only", "--cached"])
    changed = _git_output(project_path, ["git", "diff", "--name-only"])
    files   = list({*staged.splitlines(), *changed.splitlines()})
    files   = [f.strip() for f in files if f.strip()]

    if not files:
        return "chore: update"

    # Détecter le type dominant
    commit_type = "chore"
    for pattern, ctype in _CONVENTIONAL_TYPES.items():
        if any(pattern.search(f) for f in files):
            commit_type = ctype
            break

    # Scope : nom du dossier commun ou du fichier principal
    scope = _detect_scope(files)

    # Description : liste les fichiers (max 3)
    desc_files = files[:3]
    if len(files) > 3:
        desc_files.append(f"+{len(files) - 3} more")
    description = ", ".join(Path(f).name for f in desc_files)

    if scope:
        return f"{commit_type}({scope}): update {description}"
    return f"{commit_type}: update {description}"


def _detect_scope(files: list[str]) -> str:
    if not files:
        return ""
    dirs = [Path(f).parent.name for f in files if Path(f).parent.name not in (".", "")]
    if dirs:
        from collections import Counter
        return Counter(dirs).most_common(1)[0][0]
    return Path(files[0]).stem


# ── Auto-commit ────────────────────────────────────────────────────────────────

def auto_commit(project_path: Path, message: str = "",
                add_all: bool = True, log_cb: Callable | None = None) -> bool:
    """
    Commit automatique. Retourne True si un commit a été fait.
    """
    if not (project_path / ".git").exists():
        return False

    # Vérifier s'il y a des changements
    status = _git_output(project_path, ["git", "status", "--porcelain"])
    if not status.strip():
        return False   # rien à committer

    if add_all:
        _run_git(project_path, ["git", "add", "-A"], log_cb)

    msg = message or smart_commit_message(project_path)
    ok  = _run_git(project_path, ["git", "commit", "-m", msg], log_cb)
    return ok


def auto_push(project_path: Path, log_cb: Callable | None = None,
              token: str = "") -> bool:
    """
    Push vers la remote origin.
    Injecte le token dans l'URL si fourni.
    """
    if not (project_path / ".git").exists():
        return False

    if token:
        # Récupérer l'URL remote et injecter le token
        remote = _git_output(project_path, ["git", "remote", "get-url", "origin"]).strip()
        if remote.startswith("https://"):
            # https://github.com/user/repo → https://token@github.com/user/repo
            authed = remote.replace("https://", f"https://{token}@")
            return _run_git(project_path, ["git", "push", authed], log_cb)

    return _run_git(project_path, ["git", "push"], log_cb)


# ── Git status helpers ─────────────────────────────────────────────────────────

def get_status(project_path: Path) -> str:
    return _git_output(project_path, ["git", "status", "--short"])


def get_log(project_path: Path, n: int = 20) -> str:
    return _git_output(
        project_path,
        ["git", "log", f"--max-count={n}", "--oneline", "--decorate"],
    )


def list_branches(project_path: Path) -> list[str]:
    out = _git_output(project_path, ["git", "branch", "-a"])
    return [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]


def checkout(project_path: Path, branch: str,
             log_cb: Callable | None = None) -> bool:
    return _run_git(project_path, ["git", "checkout", branch], log_cb)


def pull(project_path: Path, log_cb: Callable | None = None) -> bool:
    return _run_git(project_path, ["git", "pull", "--ff-only"], log_cb)


def push(project_path: Path, log_cb: Callable | None = None,
         token: str = "") -> bool:
    return auto_push(project_path, log_cb, token)


def clone(url: str, dest: Path, token: str = "",
          log_cb: Callable | None = None) -> bool:
    if token and url.startswith("https://"):
        url = url.replace("https://", f"https://{token}@")
    dest.parent.mkdir(parents=True, exist_ok=True)
    return _run_git(dest.parent, ["git", "clone", url, str(dest.name)], log_cb)


# ── Internals ─────────────────────────────────────────────────────────────────

def _run_git(cwd: Path, cmd: list[str],
             log_cb: Callable | None) -> bool:
    try:
        r = subprocess.run(
            cmd, cwd=str(cwd),
            capture_output=True, text=True, timeout=60,
        )
        if log_cb:
            out = (r.stdout + r.stderr).strip()
            if out:
                log_cb(out)
        return r.returncode == 0
    except Exception as e:
        if log_cb:
            log_cb(f"git error: {e}")
        return False


def _git_output(cwd: Path, cmd: list[str]) -> str:
    try:
        r = subprocess.run(
            cmd, cwd=str(cwd),
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout
    except Exception:
        return ""
