"""Quick Notes — un onglet « Notes » dans chaque projet.

Montre : add_project_tab (widget avec set_project), api.settings, widgets Qt classiques.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget


class NotesTab(QWidget):
    def __init__(self, settings):
        super().__init__()
        self._settings = settings
        self._path = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        self._title = QLabel("Sélectionnez un projet")
        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText("Idées, rappels, liens… (sauvegardé automatiquement)")
        layout.addWidget(self._title)
        layout.addWidget(self._edit, stretch=1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self._save)
        self._edit.textChanged.connect(self._timer.start)

    def _key(self):
        return f"note:{self._path}"

    def _save(self):
        if self._path is not None:
            self._settings.set(self._key(), self._edit.toPlainText())

    def set_project(self, path):
        self._save()                                   # enregistre le projet qu'on quitte
        self._path = path
        self._edit.blockSignals(True)
        self._edit.setPlainText(self._settings.get(self._key(), "") if path else "")
        self._edit.blockSignals(False)
        self._edit.setEnabled(path is not None)
        self._title.setText(f"Notes — {path.name}" if path else "Sélectionnez un projet")


def on_load(api):
    api.add_project_tab("Notes", lambda ctx: NotesTab(api.settings), icon="mdi:note-text-outline")
