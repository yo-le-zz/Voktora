"""Gitignore Generator — choisit des modèles (langages, éditeurs, systèmes), les fusionne dans le .gitignore du projet.

Montre : api.project_files / project_read_text / project_write_text, un dialogue Qt, une logique pure testée (core.py).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from . import core


class GitignoreDialog(QDialog):
    def __init__(self, api, project, parent=None):
        super().__init__(parent)
        self._api, self._project = api, project
        self._files = api.project_files
        self._read, self._write = api.project_read_text, api.project_write_text
        self.setWindowTitle(f"Gitignore — {project.name}")
        self.resize(820, 560)
        try:
            self._existing = self._read(project, ".gitignore")
        except Exception:  # noqa: BLE001 — pas de .gitignore : c'est normal
            self._existing = ""
        try:
            suggested = core.detect(self._files(project, "*", limit=400))
        except Exception:  # noqa: BLE001
            suggested = []
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Cochez les modèles à ajouter. Les règles déjà présentes ne sont jamais dupliquées ni modifiées."))
        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumWidth(260)
        for name in core.names():
            item = QListWidgetItem(name + ("  ·  détecté" if name in suggested else ""))
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if name in suggested else Qt.Unchecked)
            self.list.addItem(item)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        body.addWidget(self.list)
        body.addWidget(self.preview, 1)
        root.addLayout(body, 1)
        self.info = QLabel("")
        buttons = QHBoxLayout()
        self.write_btn = QPushButton("Écrire dans .gitignore")
        self.write_btn.clicked.connect(self.write)
        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        buttons.addWidget(self.info, 1)
        buttons.addWidget(self.write_btn)
        buttons.addWidget(close)
        root.addLayout(buttons)
        self.list.itemChanged.connect(self.refresh)
        self.refresh()

    def selected(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.Checked]

    def result(self) -> str:
        return core.merge(self._existing, self.selected())

    def refresh(self, *_):
        text = self.result()
        self.preview.setPlainText(text)
        changed = text != self._existing
        self.write_btn.setEnabled(changed)
        added = len(core.existing_rules(text)) - len(core.existing_rules(self._existing))
        self.info.setText(f"{added} règle(s) à ajouter" if changed else "Rien à ajouter")

    def write(self):
        text = self.result()
        self._write(self._project, ".gitignore", text)
        self._existing = text
        self._api.notify(".gitignore mis à jour")
        self.refresh()


def on_load(api):
    def open_dialog(*_):
        project = api.current_project()
        if project is None:
            api.notify("Ouvrez d'abord un projet")
            return
        GitignoreDialog(api, project, api.main_window()).exec()

    api.add_menu_action("Outils", "Générer un .gitignore…", open_dialog, icon="mdi:file-hidden")
    api.add_palette_command("Générer un .gitignore", open_dialog)
