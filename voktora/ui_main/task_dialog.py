"""
Voktora — ui_main.task_dialog
Fenêtre de progression réutilisable pour toute opération longue (import,
export, clone…). L'opération tourne dans un TaskWorker : l'interface reste
réactive, affiche une progression réelle et permet d'annuler.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .workers import TaskContext, TaskWorker

OUTCOME_OK = "ok"
OUTCOME_ERROR = "error"
OUTCOME_CANCELLED = "cancelled"


def format_bytes(n: int) -> str:
    size = float(n)
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} o"


class TaskDialog(QDialog):
    """Fenêtre modale de progression. Après exec(), lire `outcome`, `result`, `error`."""

    def __init__(self, title: str, fn: Callable[[TaskContext], object],
                 parent: QWidget | None = None, *, show_log: bool = False,
                 cancellable: bool = True, headline: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)
        self.outcome: str = OUTCOME_ERROR
        self.result: object = None
        self.error: str = ""
        self._cancellable = cancellable
        self._finished = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        self._headline = QLabel(headline or title)
        self._headline.setObjectName("appTitle")
        layout.addWidget(self._headline)

        self._status = QLabel("Préparation…")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)          # indéterminé tant que le total est inconnu
        self._bar.setTextVisible(True)
        layout.addWidget(self._bar)

        self._detail = QLabel("")
        self._detail.setObjectName("pathLabel")
        self._detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._detail)

        self._log: QPlainTextEdit | None = None
        if show_log:
            self._log = QPlainTextEdit()
            self._log.setReadOnly(True)
            self._log.setMaximumBlockCount(500)
            self._log.setMinimumHeight(140)
            layout.addWidget(self._log)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self._cancel_btn = QPushButton("Annuler")
        self._cancel_btn.setVisible(cancellable)
        self._cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self._cancel_btn)
        layout.addLayout(buttons)

        self._worker = TaskWorker(fn)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._on_log)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)

    # ── cycle de vie ─────────────────────────────

    def exec(self) -> int:
        self._worker.start()
        try:
            return super().exec()
        finally:
            # Sécurité : ne jamais détruire la fenêtre pendant que le thread tourne.
            if self._worker.isRunning():
                self._worker.cancel()
                self._worker.wait(10_000)

    def reject(self) -> None:
        """Échap / croix / bouton Annuler : demande l'annulation sans fermer tout de suite."""
        if self._finished:
            super().reject()
        elif self._cancellable:
            self._cancel_btn.setEnabled(False)
            self._status.setText("Annulation en cours…")
            self._worker.cancel()

    def _finish(self, outcome: str) -> None:
        self._finished = True
        self.outcome = outcome
        if outcome == OUTCOME_OK:
            self.accept()
        else:
            super().reject()

    # ── signaux du worker ────────────────────────

    def _on_progress(self, done: int, total: int, current: str) -> None:
        if total > 0:
            if self._bar.maximum() != 1000:
                self._bar.setRange(0, 1000)
            self._bar.setValue(int(min(done, total) * 1000 / total))
            self._bar.setFormat(f"{min(done, total) * 100 // total} %")
            self._status.setText(f"{format_bytes(done)} / {format_bytes(total)}")
        if current:
            self._detail.setText(current)

    def _on_log(self, line: str) -> None:
        if self._log is not None:
            self._log.appendPlainText(line)
        self._detail.setText(line)

    def _on_succeeded(self, result: object) -> None:
        self.result = result
        self._finish(OUTCOME_OK)

    def _on_failed(self, message: str) -> None:
        self.error = message
        self._finish(OUTCOME_ERROR)

    def _on_cancelled(self) -> None:
        self._finish(OUTCOME_CANCELLED)


def run_task(parent: QWidget | None, title: str, fn: Callable[[TaskContext], object],
             **kwargs) -> TaskDialog:
    """Lance `fn` dans une fenêtre de progression modale et retourne le dialogue terminé."""
    dialog = TaskDialog(title, fn, parent, **kwargs)
    dialog.exec()
    return dialog
