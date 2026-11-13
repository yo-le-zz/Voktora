"""Console développeur (1.1.1) : tracebacks de Voktora et des plugins, validation, rechargement."""

from __future__ import annotations

from pathlib import Path

import plugins
from plugins import devtools
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class _Bridge(QObject):
    entry = Signal(dict)


class DevConsoleDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Console développeur")
        self.resize(900, 600)
        devtools.enable(True)
        self.source = QComboBox()
        self.source.addItem("Tout", None)
        for info in plugins.get_all():
            self.source.addItem(info.name, info.id)
        self.source.currentIndexChanged.connect(self.render)
        self.dev = QCheckBox("Recharger automatiquement le plugin quand ses fichiers changent")
        self.dev.toggled.connect(self.toggle_dev)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        buttons = QHBoxLayout()
        for text, fn in (("Valider un dossier de plugin…", self.validate), ("Recharger", self.reload),
                         ("Effacer", self.clear)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Les lignes « ▶ » sont votre code ; « · Voktora » est le code de l'application."))
        layout.addWidget(self.source)
        layout.addWidget(self.dev)
        layout.addWidget(self.view)
        layout.addLayout(buttons)
        self._bridge = _Bridge()
        self._bridge.entry.connect(lambda _e: self.render())
        self._stop = devtools.subscribe(self._bridge.entry.emit)
        self.finished.connect(lambda _r: self._stop())
        self.render()

    def _id(self):
        return self.source.currentData()

    def render(self) -> None:
        lines = []
        for e in devtools.entries(self._id()):
            text = devtools.split_traceback(e["text"]) if e["kind"] == "error" else e["text"]
            lines.append(f"[{e['time']}] {e['source']} ({e['kind']})\n{text}\n")
        self.view.setPlainText("\n".join(lines) or "Aucune erreur enregistrée.")

    def toggle_dev(self, on: bool) -> None:
        if self._id():
            devtools.set_dev(self._id(), on)

    def reload(self) -> None:
        if self._id():
            plugins.runtime.reload_plugin(self._id())
            self.render()

    def clear(self) -> None:
        devtools.clear()
        self.render()

    def validate(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Dossier du plugin", str(plugins.runtime.plugins_dir()))
        if not folder:
            return
        self.view.setPlainText("Validation en cours (exécution réelle du plugin)…")
        self.view.repaint()
        result = devtools.validate(Path(folder))
        out = ["✔ VALIDE" if result["ok"] else "✘ INVALIDE", ""]
        out += [f"ERREUR  {e}" for e in result["errors"]] + [f"AVERT.  {w}" for w in result["warnings"]]
        out += ["", "Permissions détectées : " + (", ".join(result["detected"]) or "aucune"), "", *result["logs"]]
        self.view.setPlainText("\n".join(out))
