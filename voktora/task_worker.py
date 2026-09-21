"""
task_worker.py — Thread de travail générique Voktora.

Module autonome (aucune dépendance vers ui_main) pour pouvoir être importé
depuis n'importe quel widget sans cycle. Tout ce qui peut durer (import,
export, clone, réseau, push) doit s'exécuter ici pour ne jamais figer l'interface.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import core
from PySide6.QtCore import QThread, Signal


class TaskContext:
    """Passé à la fonction d'un TaskWorker : progression, annulation, journal."""

    def __init__(self, worker: TaskWorker):
        self._worker = worker

    def progress(self, done: int, total: int, current: str = "") -> None:
        self._worker._emit_progress(done, total, current)

    def is_cancelled(self) -> bool:
        return self._worker.is_cancelled()

    def log(self, line: str) -> None:
        self._worker.log.emit(line)


class TaskWorker(QThread):
    """Exécute `fn(ctx)` hors du thread d'interface.

    Signaux : progress(fait, total, libellé) — limité à ~12 émissions/s pour
    ne pas saturer la boucle d'événements — puis exactement un parmi
    succeeded(résultat), failed(message), cancelled().
    """
    progress  = Signal(object, object, str)
    log       = Signal(str)
    succeeded = Signal(object)
    failed    = Signal(str)
    cancelled = Signal()

    _MIN_INTERVAL = 0.08

    def __init__(self, fn: Callable[[TaskContext], object]):
        super().__init__()
        self._fn = fn
        self._cancel = threading.Event()
        self._last_emit = 0.0

    def cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def _emit_progress(self, done: int, total: int, current: str) -> None:
        now = time.monotonic()
        if now - self._last_emit >= self._MIN_INTERVAL or (total and done >= total):
            self._last_emit = now
            self.progress.emit(done, total, current)

    def run(self) -> None:
        try:
            result = self._fn(TaskContext(self))
        except core.OperationCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.succeeded.emit(result)
