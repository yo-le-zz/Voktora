"""
Voktora — ui_dialogs.hooks_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import hooks as hooks_module
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

# ════════════════════════════════════════════════════════════════════════════
# HOOKS UI
# ════════════════════════════════════════════════════════════════════════════

class HooksDialog(QDialog):
    """Gestion des hooks Voktora."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hooks — Automatisations")
        self.setMinimumSize(540, 400)

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(14, 12, 14, 12)
        v.addWidget(QLabel("<b>Hooks</b> — Automatisations par evenement",
                           styleSheet="color:#cdd6f4;"))

        self._hook_cb = QComboBox()
        for h in hooks_module.HOOK_NAMES:
            self._hook_cb.addItem(h)
        self._hook_cb.currentTextChanged.connect(self._refresh_list)
        v.addWidget(self._hook_cb)

        self._list = QListWidget()
        v.addWidget(self._list)

        form = QFormLayout()
        form.setSpacing(8)
        self._type_cb   = QComboBox()
        self._type_cb.addItems(["shell", "python"])
        self._cmd_edit  = QLineEdit()
        self._cmd_edit.setPlaceholderText("echo $MERIDIAN_PROJECT_PATH")
        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("Description")
        form.addRow("Type :", self._type_cb)
        form.addRow("Commande :", self._cmd_edit)
        form.addRow("Label :", self._label_edit)
        v.addLayout(form)

        row = QHBoxLayout()
        btn_add = QPushButton("Ajouter")
        btn_add.setObjectName("primary")
        btn_add.clicked.connect(self._add)
        btn_del = QPushButton("Supprimer")
        btn_del.clicked.connect(self._delete)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        row.addStretch()
        row.addWidget(btn_close)
        v.addLayout(row)

        self._refresh_list()

    def _current_hook(self) -> str:
        return self._hook_cb.currentText()

    def _refresh_list(self) -> None:
        self._list.clear()
        for entry in hooks_module.load_hooks().get(self._current_hook(), []):
            label  = entry.get("label") or entry.get("cmd", "")[:40]
            status = "OK" if entry.get("enabled", True) else "pause"
            self._list.addItem(f"[{entry.get('type','shell')}] {status}  {label}")

    def _add(self) -> None:
        cmd = self._cmd_edit.text().strip()
        if not cmd:
            return
        hooks_module.add_hook(
            self._current_hook(),
            self._type_cb.currentText(),
            cmd,
            self._label_edit.text().strip(),
        )
        self._cmd_edit.clear()
        self._label_edit.clear()
        self._refresh_list()

    def _delete(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            hooks_module.remove_hook(self._current_hook(), row)
            self._refresh_list()


