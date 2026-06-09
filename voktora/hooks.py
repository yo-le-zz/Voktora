"""
hooks.py — Système de hooks Voktora
Chaque hook peut lancer un script Python ou une commande shell.
Hooks disponibles : on_create, on_open, on_delete, on_clone,
                    on_git_push, on_git_commit, on_git_pull
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

import core

HOOK_NAMES = (
    "on_create",
    "on_open",
    "on_delete",
    "on_clone",
    "on_git_push",
    "on_git_commit",
    "on_git_pull",
)


# ── Stockage ──────────────────────────────────────────────────────────────────

def _hooks_path() -> Path:
    return core.get_data_dir() / "hooks.json"


def load_hooks() -> dict:
    """Retourne {hook_name: [{"type": "shell"|"python", "cmd": "..."}]}"""
    p = _hooks_path()
    if not p.exists():
        return {name: [] for name in HOOK_NAMES}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # Garantir que tous les hooks connus existent
        for name in HOOK_NAMES:
            data.setdefault(name, [])
        return data
    except Exception:
        return {name: [] for name in HOOK_NAMES}


def save_hooks(hooks: dict) -> None:
    p = _hooks_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(hooks, indent=2, ensure_ascii=False), encoding="utf-8")


def add_hook(hook_name: str, kind: str, cmd: str,
             label: str = "", enabled: bool = True) -> None:
    if hook_name not in HOOK_NAMES:
        raise ValueError(f"Hook inconnu : {hook_name}")
    hooks = load_hooks()
    hooks[hook_name].append({
        "type": kind, "cmd": cmd, "label": label or cmd[:40], "enabled": enabled
    })
    save_hooks(hooks)


def remove_hook(hook_name: str, index: int) -> None:
    hooks = load_hooks()
    if 0 <= index < len(hooks.get(hook_name, [])):
        hooks[hook_name].pop(index)
        save_hooks(hooks)


# ── Exécution ─────────────────────────────────────────────────────────────────

def fire(hook_name: str, project_path: Path | None = None,
         extra_env: dict | None = None,
         log_cb: Callable[[str], None] | None = None) -> None:
    """
    Déclenche tous les handlers actifs d'un hook.
    `log_cb` reçoit les lignes de sortie des commandes.
    """
    hooks = load_hooks()
    for entry in hooks.get(hook_name, []):
        if not entry.get("enabled", True):
            continue
        kind = entry.get("type", "shell")
        cmd  = entry.get("cmd", "")
        if not cmd:
            continue
        try:
            _run_handler(kind, cmd, project_path, extra_env, log_cb)
        except Exception as exc:
            if log_cb:
                log_cb(f"[hook:{hook_name}] erreur : {exc}")


def _run_handler(kind: str, cmd: str, cwd: Path | None,
                 extra_env: dict | None, log_cb) -> None:
    import os
    env = {**os.environ, **(extra_env or {})}
    if cwd:
        env["MERIDIAN_PROJECT_PATH"] = str(cwd)

    if kind == "python":
        # Exécute un fichier .py ou un snippet inline
        script_path = Path(cmd)
        if script_path.is_file():
            result = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(cwd) if cwd else None,
                env=env, capture_output=True, text=True, timeout=60,
            )
        else:
            result = subprocess.run(
                [sys.executable, "-c", cmd],
                cwd=str(cwd) if cwd else None,
                env=env, capture_output=True, text=True, timeout=60,
            )
    else:  # shell
        result = subprocess.run(
            cmd, shell=True,
            cwd=str(cwd) if cwd else None,
            env=env, capture_output=True, text=True, timeout=60,
        )

    if log_cb:
        if result.stdout.strip():
            log_cb(result.stdout.strip())
        if result.returncode != 0 and result.stderr.strip():
            log_cb(f"[stderr] {result.stderr.strip()}")
