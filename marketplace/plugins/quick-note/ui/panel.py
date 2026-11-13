"""Panneau d'édition : un QPlainTextEdit, enregistrement différé (anti-rebond d'API Plus)."""

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

GLOBAL = "__global__"


class NotePanel(QWidget):
    def __init__(self, api, plus, store):
        super().__init__()
        self.api, self.plus, self.store = api, plus, store
        self.key = GLOBAL
        self.title = QLabel("Note générale")
        self.edit = QPlainTextEdit()
        self.status = QLabel("")
        layout = QVBoxLayout(self)
        for w in (self.title, self.edit, self.status):
            layout.addWidget(w)
        self._save_later = plus.debounce(self._save_now, api.options.get("autosave"))
        self.edit.textChanged.connect(self._changed)
        self.apply_options()
        self.show_project(None)

    def apply_options(self):
        o = self.api.options
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont) if o.get("monospace") else QFont()
        font.setPointSize(o.get("font_size"))
        self.edit.setFont(font)
        self.edit.setLineWrapMode(QPlainTextEdit.WidgetWidth if o.get("wrap") else QPlainTextEdit.NoWrap)
        self._save_later = self.plus.debounce(self._save_now, o.get("autosave"))

    def show_project(self, path):
        self._save_now()
        use = self.api.options.get("per_project") and path
        self.key = str(path) if use else GLOBAL
        self.title.setText(f"Note : {path.name}" if use else "Note générale")
        self.edit.blockSignals(True)
        self.edit.setPlainText(self.store.get(self.key, ""))
        self.edit.blockSignals(False)
        self._count()

    def focus_new(self):
        self.show()
        self.edit.setFocus()

    def _changed(self):
        self.status.setText("…")
        self._save_later()

    def _count(self):
        text = self.edit.toPlainText()
        self.status.setText(f"{len(text.split())} mots · {len(text)} caractères")

    def _save_now(self):
        text = self.edit.toPlainText()
        if self.store.get(self.key, "") != text:
            self.store[self.key] = text
            self.store.save()
        self._count()
