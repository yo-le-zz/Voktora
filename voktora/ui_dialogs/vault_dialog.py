"""
Voktora — ui_dialogs.vault_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import core
import vault
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

# ════════════════════════════════════════════════════════════════════════════
# VAULT UI
# ════════════════════════════════════════════════════════════════════════════

class VaultDialog(QDialog):
    """Interface du vault securise : voir, ajouter, supprimer les secrets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vault — Secrets securises")
        self.setMinimumSize(560, 420)

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(16, 14, 16, 14)

        title = QLabel("Vault Voktora")
        title.setStyleSheet("font-size:14px; font-weight:bold; color:#cdd6f4;")
        v.addWidget(title)

        status_color = "#a6e3a1" if core.vault_is_unlocked() else "#f38ba8"
        status_text  = "Deverrouille" if core.vault_is_unlocked() else "Verrouille"
        self._status_lbl = QLabel(status_text)
        self._status_lbl.setStyleSheet(f"color:{status_color}; font-size:12px;")
        v.addWidget(self._status_lbl)

        self._list = QListWidget()
        v.addWidget(self._list)

        row = QHBoxLayout()
        btn_add  = QPushButton("Ajouter")
        btn_add.clicked.connect(self._add_secret)
        btn_del  = QPushButton("Supprimer")
        btn_del.clicked.connect(self._del_secret)
        btn_view = QPushButton("Afficher valeur")
        btn_view.clicked.connect(self._view_secret)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        for b in (btn_add, btn_del, btn_view):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(btn_close)
        v.addLayout(row)

        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for entry in vault.list_entries():
            item = QListWidgetItem(f"{entry.kind}  /  {entry.label}")
            item.setData(Qt.UserRole, entry.key)
            self._list.addItem(item)

    def _add_secret(self) -> None:
        if not core.vault_is_unlocked():
            QMessageBox.warning(self, "Vault verrouille", "Deverrouillez le vault d'abord.")
            return
        key, ok = QInputDialog.getText(self, "Cle", "Nom de la cle (ex: MY_API_KEY) :")
        if not ok or not key.strip():
            return
        val, ok2 = QInputDialog.getText(self, "Valeur", "Valeur secrete :", QLineEdit.Password)
        if not ok2:
            return
        kinds = ["general", "github_token", "ssh_key", "api_key", "env_secret"]
        kind, ok3 = QInputDialog.getItem(self, "Type", "Type de secret :", kinds, 0, False)
        if not ok3:
            return
        label, _ = QInputDialog.getText(self, "Label", "Label (optionnel) :")
        vault.store(key.strip(), val, kind, label)
        self._refresh()

    def _del_secret(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        key = item.data(Qt.UserRole)
        if QMessageBox.question(self, "Supprimer", f"Supprimer {key} ?") == QMessageBox.Yes:
            vault.delete(key)
            self._refresh()

    def _view_secret(self) -> None:
        if not core.vault_is_unlocked():
            QMessageBox.warning(self, "Vault verrouille", "Deverrouillez le vault d'abord.")
            return
        item = self._list.currentItem()
        if not item:
            return
        key = item.data(Qt.UserRole)
        val = vault.retrieve(key)
        QMessageBox.information(self, f"Secret : {key}", f"Valeur :\n{val}")


