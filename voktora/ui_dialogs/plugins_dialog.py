"""
Voktora — ui_dialogs.plugins_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import sys

import plugins
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

# ════════════════════════════════════════════════════════════════════════════
# PLUGINS UI
# ════════════════════════════════════════════════════════════════════════════

class PluginsDialog(QDialog):
    """Gestionnaire de plugins."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plugins Voktora")
        self.setMinimumSize(520, 380)

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(14, 12, 14, 12)
        v.addWidget(QLabel("<b>Plugins</b>", styleSheet="color:#cdd6f4; font-size:14px;"))

        hint = QLabel(
            f"Dossier : <code>{plugins.plugins_dir()}</code><br>"
            "Ajoutez un fichier .py dans ce dossier et rechargez."
        )
        hint.setTextFormat(Qt.RichText)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#a6adc8; font-size:11px;")
        v.addWidget(hint)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Plugin", "Version", "Auteur", "Statut"])
        self._tree.setColumnWidth(0, 160)
        v.addWidget(self._tree)

        row = QHBoxLayout()
        btn_reload = QPushButton("Recharger")
        btn_reload.clicked.connect(self._reload)
        btn_open = QPushButton("Ouvrir dossier")
        btn_open.clicked.connect(self._open_dir)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_reload)
        row.addWidget(btn_open)
        row.addStretch()
        row.addWidget(btn_close)
        v.addLayout(row)

        self._refresh()

    def _refresh(self) -> None:
        self._tree.clear()
        for info in plugins.get_all():
            status = "Erreur" if info.error else f"{len(info.commands)} cmd / {len(info.buttons)} btn"
            item   = QTreeWidgetItem([info.name, info.version, info.author, status])
            if info.error:
                item.setToolTip(0, info.error)
            self._tree.addTopLevelItem(item)

    def _reload(self) -> None:
        plugins.load_all()
        self._refresh()

    def _open_dir(self) -> None:
        import subprocess as _sp
        d = str(plugins.plugins_dir())
        if sys.platform == "win32":
            _sp.Popen(["explorer", d])
        else:
            _sp.Popen(["xdg-open", d])
