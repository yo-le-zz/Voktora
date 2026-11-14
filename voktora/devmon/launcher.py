"""devmon.launcher — lance le viewer dans un processus DÉTACHÉ (survit à Voktora, ne bloque pas la fenêtre principale)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import core

ENV_VIEWER = "VOKTORA_DEVMON_VIEWER"


def viewer_command(session: Path, frozen: bool | None = None, main_script: str | None = None) -> tuple[list[str], dict]:
    """(argv, variables d'environnement ajoutées). Version compilée : le même exécutable, relancé en mode viewer."""
    frozen = getattr(sys, "frozen", False) or "__compiled__" in globals() if frozen is None else frozen
    env = {ENV_VIEWER: str(session)}
    if frozen:
        return [sys.executable], env
    script = main_script or str(Path(__file__).resolve().parents[1] / "main.py")
    return [sys.executable, script], env


def launch_viewer(session: Path) -> subprocess.Popen | None:
    """Ouvre la fenêtre du moniteur. Renvoie None si le lancement échoue (jamais d'exception vers l'appelant)."""
    argv, extra = viewer_command(session)
    env = {**os.environ, **extra}
    env.pop("VOKTORA_JS_WORKER", None)
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "env": env, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000      # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(argv, **kwargs)  # noqa: S603
    except OSError:
        return None


def latest_session(directory: Path | None = None) -> Path | None:
    directory = directory or core.base_dir()
    files = sorted(directory.glob("session-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def parse_dev_arg(argv: list[str], environ: dict | None = None) -> str | None:
    """`--dev`, `--dev=verbose` ou VOKTORA_DEV=verbose → niveau ; None si le mode développeur n'est pas demandé."""
    environ = os.environ if environ is None else environ
    for arg in argv[1:]:
        if arg == "--dev":
            return "normal"
        if arg.startswith("--dev="):
            return core.valid_level(arg.split("=", 1)[1])
    value = (environ.get("VOKTORA_DEV") or "").strip().lower()
    if value in ("1", "true", "yes", "on"):
        return "normal"
    return value if value in core.RANK else None
