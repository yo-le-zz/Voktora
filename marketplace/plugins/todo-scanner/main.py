"""TODO Scanner — onglet qui liste les marqueurs TODO / FIXME / HACK.

Montre : add_project_tab, run_async (analyse hors du thread d'interface), QTreeWidget.
"""

import re
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

PATTERN = re.compile(r"\b(TODO|FIXME|HACK)\b[:\s-]*(.{0,120})")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "target", "dist", "build"}
MAX_FILES, MAX_BYTES = 3000, 300_000


def scan(root: Path):
    found, seen = [], 0
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            continue
        seen += 1
        if seen > MAX_FILES:
            break
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            match = PATTERN.search(line)
            if match:
                found.append((match.group(1), str(path.relative_to(root)), number, match.group(2).strip()))
    return found


class TodoTab(QWidget):
    def __init__(self, api):
        super().__init__()
        self._api, self._path = api, None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        self._label = QLabel("Sélectionnez un projet")
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Type", "Fichier", "Ligne", "Texte"])
        self._tree.itemDoubleClicked.connect(self._open)
        button = QPushButton("Analyser à nouveau")
        button.clicked.connect(self.refresh)
        layout.addWidget(self._label)
        layout.addWidget(self._tree, stretch=1)
        layout.addWidget(button)

    def set_project(self, path):
        self._path = path
        self.refresh()

    def refresh(self):
        self._tree.clear()
        if self._path is None:
            self._label.setText("Sélectionnez un projet")
            return
        self._label.setText("Analyse…")
        root = self._path
        self._api.run_async(lambda: scan(root), lambda rows: self._show(root, rows))

    def _show(self, root, rows):
        if root != self._path:
            return                                     # on a changé de projet entre-temps
        for row in rows:
            self._tree.addTopLevelItem(QTreeWidgetItem([row[0], row[1], str(row[2]), row[3]]))
        self._label.setText(f"{len(rows)} marqueur(s) trouvé(s) — double-clic pour ouvrir le fichier")

    def _open(self, item, _column):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._path / item.text(1))))


def on_load(api):
    api.add_project_tab("TODO", lambda ctx: TodoTab(api), icon="mdi:format-list-checks")
