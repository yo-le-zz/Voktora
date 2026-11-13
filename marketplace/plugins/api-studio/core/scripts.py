"""Scripts avant/après (Python ou JavaScript) dans un processus isolé : délai, dossier temporaire vide, environnement minimal."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RES = Path(__file__).resolve().parent.parent / "resources"
MARK = "\x00RESULT\x00"


class ScriptError(Exception):
    pass


def available(lang: str) -> bool:
    return True if lang == "python" else bool(shutil.which("node")) if lang == "javascript" else False


def run_script(lang: str, code: str, variables: dict, request: dict, response: dict | None = None, timeout: float = 10.0) -> dict:
    """Retourne {"vars","request","logs","tests","error"}. Lève ScriptError si l'interpréteur manque ou si le délai est dépassé."""
    if not code.strip():
        return {"vars": dict(variables), "request": request, "logs": [], "tests": [], "error": ""}
    if lang == "python":
        cmd = [sys.executable, "-I", "{runner}"]
        runner_name = "py_runner.txt"
    elif lang == "javascript":
        node = shutil.which("node")
        if not node:
            raise ScriptError("Node.js est introuvable : installez-le pour utiliser les scripts JavaScript.")
        cmd = [node, "{runner}"]
        runner_name = "js_runner.txt"
    else:
        raise ScriptError(f"Langage de script inconnu : {lang}")
    payload = json.dumps({"code": code, "vars": variables, "request": request, "response": response, "timeout": int(timeout * 900)})
    with tempfile.TemporaryDirectory(prefix="voktora-script-") as tmp:
        runner = Path(tmp) / ("runner.py" if lang == "python" else "runner.js")
        runner.write_text((RES / runner_name).read_text(encoding="utf-8"), encoding="utf-8")
        cmd = [c.replace("{runner}", str(runner)) for c in cmd]
        env = {"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"}
        try:
            done = subprocess.run(cmd, input=payload, capture_output=True, text=True, timeout=timeout, cwd=tmp, env=env,   # noqa: S603
                                  encoding="utf-8", errors="replace", check=False)
        except subprocess.TimeoutExpired as exc:
            raise ScriptError(f"Script interrompu : délai de {timeout:g} s dépassé.") from exc
        except OSError as exc:
            raise ScriptError(str(exc)) from exc
    out = done.stdout or ""
    if MARK not in out:
        raise ScriptError((done.stderr or out or "Le script n'a rien renvoyé.").strip()[-400:])
    try:
        return json.loads(out.split(MARK, 1)[1])
    except ValueError as exc:
        raise ScriptError("Résultat du script illisible.") from exc
