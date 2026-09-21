"""
Voktora — ui_main.workers
Fragment de ui_main.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import html
import threading
from pathlib import Path

import core
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
)


class Worker(QThread):
    """Worker générique — émet le résultat final en une seule fois."""
    finished = Signal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self._fn, self._args = fn, args

    def run(self):
        try:
            self.finished.emit(self._fn(*self._args))
        except Exception as e:
            self.finished.emit(f"[ERREUR] {e}")


class GitWorker(QThread):
    """Worker spécialisé pour les opérations git avancées."""
    log_line = Signal(str)
    finished = Signal(bool)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs

    def run(self):
        try:
            self._fn(*self._args, on_step=self._on_step, **self._kwargs)
            self.finished.emit(True)
        except Exception as e:
            safe = html.escape(str(e))
            self.log_line.emit(
                f'<span style="color:#f38ba8; font-weight:600">[ERREUR] {safe}</span>'
            )
            self.finished.emit(False)

    def _on_step(self, cmd: str, output: str) -> None:
        self.log_line.emit(
            f'<span style="color:#89b4fa; font-family:Consolas,monospace">'
            f'$ git {html.escape(cmd)}</span>'
        )
        if output.strip():
            self.log_line.emit(
                f'<pre style="color:#cdd6f4; margin:1px 0 6px 12px; '
                f'white-space:pre-wrap; font-size:11px">'
                f'{html.escape(output.strip())}</pre>'
            )


class DeleteWorker(QThread):
    """Worker non bloquant pour la suppression de gros dossiers."""
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    def run(self):
        try:
            if not self._path.exists():
                self.finished.emit(True, "")
                return

            paths = [p for p in self._path.rglob("*")]
            total = len(paths) + 1
            removed = 0

            for child in sorted(paths, key=lambda p: p.is_dir(), reverse=True):
                try:
                    if child.is_file() or child.is_symlink():
                        child.unlink()
                    elif child.is_dir():
                        child.rmdir()
                except Exception:
                    pass
                removed += 1
                self.progress.emit(int(removed / total * 100))

            try:
                self._path.rmdir()
            except Exception:
                pass
            removed += 1
            self.progress.emit(100)
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class UpdateCheckWorker(QThread):
    """Vérifie en arrière-plan si une mise à jour Voktora est disponible."""
    result = Signal(bool, str, str)   # available, latest_version, url

    def run(self):
        available, latest, url = core.check_for_update()
        self.result.emit(available, latest, url)


class OAuthPollWorker(QThread):
    """
    Worker qui sonde l'API GitHub toutes les N secondes jusqu'à obtenir le token.
    Émet success(token) ou error(message).
    """
    success = Signal(str)   # token OAuth en clair
    error   = Signal(str)   # message d'erreur

    def __init__(self, pending: core.DeviceFlowPending):
        super().__init__()
        self._pending    = pending
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        core.poll_device_flow(
            self._pending,
            on_success = lambda token: self.success.emit(token),
            on_error   = lambda msg:   self.error.emit(msg),
            stop_event = self._stop_event,
        )


# ══════════════════════════════════════════════════════
#  HELPERS COMMUNS
# ══════════════════════════════════════════════════════

def _make_sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    return f


# ══════════════════════════════════════════════════════
#  DIALOG — CONNEXION GITHUB OAUTH (Device Flow) — v1.0.1
# ══════════════════════════════════════════════════════

