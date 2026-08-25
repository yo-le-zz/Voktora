"""
Voktora — ui_dialogs.status_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import core
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


# ════════════ status_dialog.py ════════════
class StatusDialog(QDialog):
    """Dialogue pour gérer les statuts de projets personnalisés."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 Gestion des statuts — Voktora")
        self.setModal(True)
        self.setMinimumSize(620, 580)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # ── Liste des statuts existants ──
        list_group = QGroupBox("📊 Statuts existants (gris = défaut non modifiable)")
        list_layout = QVBoxLayout()

        self.status_list = QListWidget()
        list_layout.addWidget(self.status_list)

        # Boutons de la liste
        list_btn_row = QHBoxLayout()
        self.btn_edit   = QPushButton("✏️ Modifier")
        self.btn_edit.clicked.connect(self._edit_selected)
        self.btn_delete = QPushButton("🗑️ Supprimer")
        self.btn_delete.clicked.connect(self._delete_selected)
        list_btn_row.addWidget(self.btn_edit)
        list_btn_row.addWidget(self.btn_delete)
        list_btn_row.addStretch()
        list_layout.addLayout(list_btn_row)

        list_group.setLayout(list_layout)
        layout.addWidget(list_group)

        # ── Ajouter un nouveau statut ──
        add_group = QGroupBox("➕ Ajouter un statut personnalisé")
        add_layout = QFormLayout()

        self.new_status_id = QLineEdit()
        self.new_status_id.setPlaceholderText("ID unique (ex: review)")
        add_layout.addRow("ID :", self.new_status_id)

        self.new_status_name = QLineEdit()
        self.new_status_name.setPlaceholderText("Nom affiché (ex: En revue)")
        add_layout.addRow("Nom :", self.new_status_name)

        self.new_status_emoji = QLineEdit()
        self.new_status_emoji.setPlaceholderText("Emoji (ex: 🔍)")
        add_layout.addRow("Emoji :", self.new_status_emoji)

        # Sélection de couleur
        self.current_color = "#89b4fa"
        self.color_preview = QLabel("■")
        self.color_preview.setStyleSheet("font-size: 24px; color: #89b4fa;")
        self.color_button  = QPushButton("Choisir une couleur")
        self.color_button.clicked.connect(self._choose_color)
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_preview)
        color_row.addWidget(self.color_button)
        color_row.addStretch()
        add_layout.addRow("Couleur :", color_row)

        self.btn_add_status = QPushButton("➕ Ajouter")
        self.btn_add_status.setObjectName("primary")
        self.btn_add_status.clicked.connect(self._add_status)
        add_layout.addRow("", self.btn_add_status)

        add_group.setLayout(add_layout)
        layout.addWidget(add_group)

        # ── Boutons bas ──
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Fermer")
        btn_cancel.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        self._load_statuses()

    # ──────────────────────────────────────────────────────────

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.current_color), self, "Choisir une couleur")
        if color.isValid():
            self.current_color = color.name()
            self.color_preview.setStyleSheet(f"font-size: 24px; color: {self.current_color};")

    def _load_statuses(self) -> None:
        self.status_list.clear()

        # Statuts par défaut (non modifiables)
        for status_id, status in core.PROJECT_STATUSES.items():
            item = QListWidgetItem(f"{status.emoji} {status.name}  [défaut]")
            item.setData(Qt.UserRole, {
                "id": status_id, "name": status.name,
                "emoji": status.emoji, "color": status.color,
                "is_default": True,
            })
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            item.setForeground(QColor("#6c7086"))
            self.status_list.addItem(item)

        # Statuts personnalisés
        cfg = core._load_config()
        custom_statuses = cfg.get("custom_statuses", {})
        for status_id, status_data in custom_statuses.items():
            item = QListWidgetItem(
                f"{status_data['emoji']} {status_data['name']}  [personnalisé]"
            )
            item.setData(Qt.UserRole, {
                "id":         status_id,
                "name":       status_data["name"],
                "emoji":      status_data["emoji"],
                "color":      status_data["color"],
                "is_default": False,
            })
            self.status_list.addItem(item)

    def _add_status(self) -> None:
        status_id = self.new_status_id.text().strip()
        name      = self.new_status_name.text().strip()
        emoji     = self.new_status_emoji.text().strip()

        if not status_id or not name:
            QMessageBox.warning(self, "Attention",
                                "Veuillez remplir l'ID et le nom du statut.")
            return

        if status_id in core.PROJECT_STATUSES:
            QMessageBox.warning(self, "Attention",
                                f"L'ID '{status_id}' existe déjà dans les statuts par défaut.")
            return

        cfg = core._load_config()
        custom_statuses = cfg.get("custom_statuses", {})

        if status_id in custom_statuses:
            QMessageBox.warning(self, "Attention",
                                f"L'ID '{status_id}' existe déjà dans les statuts personnalisés.")
            return

        custom_statuses[status_id] = {
            "name":  name,
            "emoji": emoji or "📊",
            "color": self.current_color,
        }
        cfg["custom_statuses"] = custom_statuses
        core._save_config(cfg)

        self.new_status_id.clear()
        self.new_status_name.clear()
        self.new_status_emoji.clear()
        self.current_color = "#89b4fa"
        self.color_preview.setStyleSheet("font-size: 24px; color: #89b4fa;")
        self._load_statuses()
        QMessageBox.information(self, "Succès", f"Le statut '{name}' a été ajouté.")

    def _edit_selected(self) -> None:
        """Ouvre un dialogue inline pour modifier un statut personnalisé."""
        current_item = self.status_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention", "Sélectionnez un statut à modifier.")
            return

        status_data = current_item.data(Qt.UserRole)
        if not status_data:
            return

        if status_data["is_default"]:
            QMessageBox.warning(self, "Attention",
                                "Les statuts par défaut ne peuvent pas être modifiés.")
            return

        # Ouvrir le dialogue d'édition
        dlg = EditStatusDialog(status_data, self)
        if dlg.exec() == QDialog.Accepted:
            new_data = dlg.get_data()
            cfg = core._load_config()
            custom_statuses = cfg.get("custom_statuses", {})

            if status_data["id"] in custom_statuses:
                custom_statuses[status_data["id"]] = {
                    "name":  new_data["name"],
                    "emoji": new_data["emoji"],
                    "color": new_data["color"],
                }
                cfg["custom_statuses"] = custom_statuses
                core._save_config(cfg)
                self._load_statuses()
                QMessageBox.information(self, "Succès",
                                        f"Statut '{new_data['name']}' mis à jour.")

    def _delete_selected(self) -> None:
        current_item = self.status_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention",
                                "Veuillez sélectionner un statut à supprimer.")
            return

        status_data = current_item.data(Qt.UserRole)
        if not status_data:
            return

        if status_data["is_default"]:
            QMessageBox.warning(self, "Attention",
                                "Les statuts par défaut ne peuvent pas être supprimés.")
            return

        status_id   = status_data["id"]
        status_name = status_data["name"]

        reply = QMessageBox.question(
            self, "Supprimer",
            f"Supprimer le statut '{status_name}' ?\n\n"
            "Les projets utilisant ce statut ne l'afficheront plus.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            cfg = core._load_config()
            custom_statuses = cfg.get("custom_statuses", {})
            if status_id in custom_statuses:
                del custom_statuses[status_id]
                cfg["custom_statuses"] = custom_statuses
                core._save_config(cfg)
                self._load_statuses()
                QMessageBox.information(self, "Succès",
                                        f"Statut '{status_name}' supprimé.")


# ──────────────────────────────────────────────────────────────
# Dialogue d'édition d'un statut personnalisé
# ──────────────────────────────────────────────────────────────


class EditStatusDialog(QDialog):
    """Dialogue simple pour modifier un statut personnalisé existant."""

    def __init__(self, status_data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✏️ Modifier un statut — Voktora")
        self.setModal(True)
        self.setFixedSize(380, 280)

        self._color = status_data.get("color", "#89b4fa")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        form = QFormLayout()

        self.name_edit = QLineEdit(status_data.get("name", ""))
        form.addRow("Nom :", self.name_edit)

        self.emoji_edit = QLineEdit(status_data.get("emoji", ""))
        form.addRow("Emoji :", self.emoji_edit)

        self.color_preview = QLabel("■")
        self.color_preview.setStyleSheet(f"font-size: 24px; color: {self._color};")
        btn_color = QPushButton("Choisir")
        btn_color.clicked.connect(self._choose_color)
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_preview)
        color_row.addWidget(btn_color)
        color_row.addStretch()
        form.addRow("Couleur :", color_row)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("✔ Enregistrer")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._validate)
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._color), self, "Choisir une couleur")
        if color.isValid():
            self._color = color.name()
            self.color_preview.setStyleSheet(f"font-size: 24px; color: {self._color};")

    def _validate(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Attention", "Le nom ne peut pas être vide.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "name":  self.name_edit.text().strip(),
            "emoji": self.emoji_edit.text().strip() or "📊",
            "color": self._color,
        }


