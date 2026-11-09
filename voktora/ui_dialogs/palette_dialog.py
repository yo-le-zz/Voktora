"""
Voktora — ui_dialogs.palette_dialog (1.1.0)
Palette de commandes (Ctrl+K) : tape quelques lettres pour lancer n'importe quelle action des menus ou ouvrir un projet.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMenuBar, QVBoxLayout


def collect_actions(menubar: QMenuBar) -> list[tuple[str, QAction]]:
    """Toutes les actions activables des menus, avec leur chemin (« Outils › Synchronisation »)."""
    out: list[tuple[str, QAction]] = []

    def walk(menu: QMenu, prefix: str) -> None:
        for action in menu.actions():
            if action.isSeparator():
                continue
            title = action.text().replace("&", "").strip()
            if action.menu():
                walk(action.menu(), f"{prefix}{title} › ")
            elif action.isEnabled() and title:
                out.append((f"{prefix}{title}", action))

    for action in menubar.actions():
        if action.menu():
            walk(action.menu(), f"{action.text().replace('&', '').strip()} › ")
    return out


def score(query: str, text: str) -> int:
    """Correspondance floue : tous les mots présents (0 = non). Plus petit = meilleur, début de mot favorisé."""
    low = text.lower()
    total = 0
    for word in query.lower().split():
        pos = low.find(word)
        if pos < 0:
            return 0
        total += pos + (0 if pos == 0 or low[pos - 1] in " ›-_/" else 20) + 1
    return max(1, 1000 - total)


class PaletteDialog(QDialog):
    def __init__(self, parent, entries: list[tuple[str, Callable[[], None]]]):
        super().__init__(parent, Qt.Popup)
        self.setMinimumWidth(560)
        self._entries = entries
        v = QVBoxLayout(self)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Tapez une action ou un nom de projet…")
        self.edit.textChanged.connect(self._filter)
        self.edit.returnPressed.connect(self._run)
        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _i: self._run())
        v.addWidget(self.edit)
        v.addWidget(self.list)
        self._filter()

    def _filter(self) -> None:
        query = self.edit.text().strip()
        ranked = [(score(query, label) if query else 1, i) for i, (label, _fn) in enumerate(self._entries)]
        ranked = sorted((r for r in ranked if r[0] > 0), key=lambda r: (-r[0], r[1]))[:40]
        self.list.clear()
        for _s, i in ranked:
            item = QListWidgetItem(self._entries[i][0])
            item.setData(Qt.UserRole, i)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Down, Qt.Key_Up) and self.list.count():
            row = self.list.currentRow() + (1 if event.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
            return
        super().keyPressEvent(event)

    def _run(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        fn = self._entries[item.data(Qt.UserRole)][1]
        self.accept()
        fn()
