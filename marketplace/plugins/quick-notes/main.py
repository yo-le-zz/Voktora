"""Quick Notes 1.1 — un onglet « Notes » par projet : sauvegarde automatique, compteur, copie et export Markdown.

Montre : add_project_tab (widget avec set_project), api.settings, options, widgets Qt classiques.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from . import notes


class NotesTab(QWidget):
    def __init__(self, api):
        super().__init__()
        self._api, self._settings, self._path = api, api.settings, None
        self._copy_text = api.set_clipboard_text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        head = QHBoxLayout()
        self._title = QLabel("Sélectionnez un projet")
        self._title.setStyleSheet("font-weight: 600; font-size: 14px;")
        self._saved = QLabel("")
        self._saved.setStyleSheet("color: gray;")
        copy = QPushButton("Copier")
        copy.setToolTip("Copie la note en Markdown")
        copy.clicked.connect(self._copy)
        head.addWidget(self._title, 1)
        head.addWidget(self._saved)
        head.addWidget(copy)
        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText("Idées, rappels, liens… (sauvegardé automatiquement)")
        self._count = QLabel("")
        self._count.setStyleSheet("color: gray;")
        layout.addLayout(head)
        layout.addWidget(self._edit, stretch=1)
        layout.addWidget(self._count)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(200, int(api.options.get("delay_ms"))))
        self._timer.timeout.connect(self._save)
        self._edit.textChanged.connect(self._changed)
        self._edit.setTabChangesFocus(False)
        self._apply_font()

    def _apply_font(self):
        font = self._edit.font()
        font.setPointSize(int(self._api.options.get("font_size")))
        self._edit.setFont(font)

    def _key(self):
        return f"note:{self._path}"

    def _changed(self):
        self._saved.setText("Modification non enregistrée…")
        self._count.setText(notes.describe(self._edit.toPlainText()))
        self._timer.start()

    def _save(self):
        if self._path is not None:
            self._settings.set(self._key(), self._edit.toPlainText())
            self._saved.setText("Enregistré")

    def _copy(self):
        if self._path is not None:
            self._copy_text(notes.to_markdown(self._path.name, self._edit.toPlainText()))
            self._api.notify("Note copiée (Markdown)")

    def set_project(self, path):
        self._save()                                   # enregistre le projet qu'on quitte
        self._path = path
        self._edit.blockSignals(True)
        self._edit.setPlainText(self._settings.get(self._key(), "") if path else "")
        self._edit.blockSignals(False)
        self._edit.setEnabled(path is not None)
        self._title.setText(f"Notes — {path.name}" if path else "Sélectionnez un projet")
        self._saved.setText("")
        self._count.setText(notes.describe(self._edit.toPlainText()) if path else "")


def on_load(api):
    api.options.group("Éditeur")
    api.options.add_int("font_size", "Taille du texte (pt)", default=11, min=8, max=28)
    api.options.add_int("delay_ms", "Délai de sauvegarde automatique (ms)", default=600, min=200, max=5000, step=100)
    api.add_project_tab("Notes", lambda ctx: NotesTab(api), icon="mdi:note-text-outline")
