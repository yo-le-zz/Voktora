"""Exécution de programmes : flux ligne à ligne, délai, annulation, jamais de shell."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field


@dataclass
class Result:
    code: int
    out: str = ""
    seconds: float = 0.0
    cancelled: bool = False
    timed_out: bool = False
    error: str = ""
    args: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.cancelled and not self.timed_out and not self.error


def run(args: list[str], cwd=None, timeout: float = 120.0, env: dict | None = None, cancel: threading.Event | None = None,
        on_line=None, input_text: str | None = None) -> Result:
    """Lance `args` (liste, jamais via un interpréteur). Fusionne stdout/stderr, appelle `on_line(ligne)` au fil de l'eau."""
    start = time.monotonic()
    if not args or not all(isinstance(a, str) for a in args):
        return Result(-1, error="Commande invalide : liste de chaînes attendue.", args=list(args or []))
    full_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.Popen(args, cwd=cwd, env=full_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,   # noqa: S603
                                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL, text=True,
                                encoding="utf-8", errors="replace")
    except (OSError, ValueError) as exc:
        return Result(-1, error=str(exc), seconds=time.monotonic() - start, args=list(args))
    lines: list[str] = []
    state = {"timed_out": False, "cancelled": False}

    def watchdog():
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                state["cancelled"] = True
                proc.kill()
                return
            if time.monotonic() - start > timeout:
                state["timed_out"] = True
                proc.kill()
                return
            time.sleep(0.05)

    threading.Thread(target=watchdog, daemon=True).start()
    if input_text is not None:
        try:
            proc.stdin.write(input_text)
            proc.stdin.close()
        except OSError:
            pass
    for line in proc.stdout:
        line = line.rstrip("\n")
        lines.append(line)
        if on_line:
            on_line(line)
    proc.wait()
    return Result(proc.returncode, "\n".join(lines), time.monotonic() - start, state["cancelled"], state["timed_out"], args=list(args))
