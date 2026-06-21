"""
ui_dialogs.py — Dialogs Voktora
Version : 1.0.1
Regroupe tous les dialogs : categories, statuts, config, personnalisation,
thèmes, chiffrement, migration, master password, vault, profils, hooks,
snapshots, dashboard, plugins.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from datetime import datetime

from PySide6.QtCore    import Qt, QThread, Signal, QTimer
from PySide6.QtGui     import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QCompleter,
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QStackedWidget,
    QTabWidget, QTextEdit, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QProgressBar,
)

import core
import vault
import hooks as hooks_module
import profiles
import snapshots
import dashboard
import plugins
import theme_manager


# ════════════ categories_dialog.py ════════════
class CategoriesDialog(QDialog):
    """Dialogue pour gérer les catégories de projets."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📂 Gestion des catégories — Voktora")
        self.setModal(True)
        self.setFixedSize(500, 450)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Liste des catégories existantes
        list_group = QGroupBox("📂 Catégories existantes")
        list_layout = QVBoxLayout()
        
        self.categories_list = QListWidget()
        list_layout.addWidget(self.categories_list)
        
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)
        
        # Ajouter une nouvelle catégorie
        add_group = QGroupBox("➕ Ajouter une catégorie")
        add_layout = QFormLayout()
        
        self.new_category_edit = QLineEdit()
        self.new_category_edit.setPlaceholderText("Nom de la nouvelle catégorie...")
        add_layout.addRow("Nom:", self.new_category_edit)
        
        self.btn_add_category = QPushButton("➕ Ajouter")
        self.btn_add_category.clicked.connect(self._add_category)
        add_layout.addRow("", self.btn_add_category)
        
        add_group.setLayout(add_layout)
        layout.addWidget(add_group)
        
        # Boutons
        btn_layout = QHBoxLayout()
        btn_delete = QPushButton("🗑️ Supprimer")
        btn_delete.clicked.connect(self._delete_selected)
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_apply = QPushButton("Appliquer")
        btn_apply.setObjectName("primary")
        btn_apply.clicked.connect(self.accept)
        
        btn_layout.addWidget(btn_delete)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_apply)
        layout.addLayout(btn_layout)
        
        # Charger les catégories existantes
        self._load_categories()
        
    def _load_categories(self):
        """Charge la liste des catégories existantes."""
        cfg = core._load_config()
        categories = cfg.get("categories", [])
        
        # Catégories par défaut
        default_categories = ["Web", "Desktop", "Mobile", "API", "CLI", "Game", "AI/ML", "Data", "DevOps", "Security", "IoT", "Blockchain", "Autre"]
        
        all_categories = list(set(default_categories + categories))
        all_categories.sort()
        
        for category in all_categories:
            item = QListWidgetItem(category)
            self.categories_list.addItem(item)
            
    def _add_category(self):
        """Ajoute une nouvelle catégorie."""
        category = self.new_category_edit.text().strip()
        if not category:
            QMessageBox.warning(self, "Attention", "Veuillez entrer un nom de catégorie.")
            return
            
        # Vérifier si la catégorie existe déjà
        for i in range(self.categories_list.count()):
            if self.categories_list.item(i).text().lower() == category.lower():
                QMessageBox.warning(self, "Attention", f"La catégorie '{category}' existe déjà.")
                return
                
        # Ajouter la catégorie
        item = QListWidgetItem(category)
        self.categories_list.addItem(item)
        self.new_category_edit.clear()
        
    def _delete_selected(self):
        """Supprime la catégorie sélectionnée."""
        current_item = self.categories_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention", "Veuillez sélectionner une catégorie à supprimer.")
            return
            
        category = current_item.text()
        reply = QMessageBox.question(
            self, "Supprimer",
            f"Êtes-vous sûr de vouloir supprimer la catégorie '{category}' ?\n\n"
            "Les projets utilisant cette catégorie ne seront pas affectés.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.categories_list.takeItem(self.categories_list.row(current_item))
            
    def get_categories(self):
        """Retourne la liste des catégories."""
        categories = []
        for i in range(self.categories_list.count()):
            categories.append(self.categories_list.item(i).text())
        return categories


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


# ════════════ config_dialog.py ════════════
class ConfigDialog(QDialog):
    """Dialogue de configuration globale de Voktora."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Configuration — Voktora")
        self.setModal(True)
        self.setMinimumSize(560, 680)

        # Layout racine
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Zone scrollable
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        container = QWidget()
        layout    = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 10)
        layout.setSpacing(16)

        # ── 1. Stockage ───────────────────────────────────
        grp_storage = QGroupBox("📁 Stockage des projets")
        form_storage = QFormLayout()

        self.instances_root_edit = QLineEdit()
        self.instances_root_edit.setPlaceholderText("Chemin personnalisé (laisser vide = défaut)")
        btn_inst_browse = QPushButton("…")
        btn_inst_browse.setFixedWidth(32)
        btn_inst_browse.clicked.connect(
            lambda: self._browse_dir(self.instances_root_edit)
        )
        row_inst = QHBoxLayout()
        row_inst.addWidget(self.instances_root_edit)
        row_inst.addWidget(btn_inst_browse)
        form_storage.addRow("Instances :", row_inst)

        self.intents_root_edit = QLineEdit()
        self.intents_root_edit.setPlaceholderText("Chemin personnalisé (laisser vide = défaut)")
        btn_int_browse = QPushButton("…")
        btn_int_browse.setFixedWidth(32)
        btn_int_browse.clicked.connect(
            lambda: self._browse_dir(self.intents_root_edit)
        )
        row_int = QHBoxLayout()
        row_int.addWidget(self.intents_root_edit)
        row_int.addWidget(btn_int_browse)
        form_storage.addRow("Intents :", row_int)

        # Créer les dossiers immédiatement
        self.btn_create_dirs = QPushButton("📂 Créer les dossiers maintenant")
        self.btn_create_dirs.clicked.connect(self._create_install_dirs)
        form_storage.addRow("", self.btn_create_dirs)

        grp_storage.setLayout(form_storage)
        layout.addWidget(grp_storage)

        # ── 2. Cache ──────────────────────────────────────
        grp_cache = QGroupBox("🗃️ Cache")
        form_cache = QFormLayout()

        self.cache_mode_combo = QComboBox()
        self.cache_mode_combo.addItem("🧠 Mémoire vive (RAM) — rapide, non persistant", "memory")
        self.cache_mode_combo.addItem("💾 Disque — persistant, plus lent", "disk")
        form_cache.addRow("Mode de stockage :", self.cache_mode_combo)

        self.cache_size_spin = QSpinBox()
        self.cache_size_spin.setRange(32, 4096)
        self.cache_size_spin.setSuffix(" Mo")
        self.cache_size_spin.setToolTip("Taille maximale du cache avant éviction (32–4096 Mo)")
        form_cache.addRow("Taille maximale :", self.cache_size_spin)

        grp_cache.setLayout(form_cache)
        layout.addWidget(grp_cache)

        # ── 3. Interface ──────────────────────────────────
        grp_ui = QGroupBox("🖥️ Interface")
        form_ui = QFormLayout()

        self.chk_hide_github_notif = QCheckBox(
            "Masquer la notification « Compte GitHub non connecté »"
        )
        self.chk_hide_github_notif.setToolTip(
            "Désactive la carte d'avertissement dans la barre latérale "
            "quand aucun compte GitHub n'est configuré."
        )
        form_ui.addRow("", self.chk_hide_github_notif)

        self.chk_auto_save_notes = QCheckBox("Sauvegarde automatique des notes")
        form_ui.addRow("", self.chk_auto_save_notes)

        self.note_interval_spin = QSpinBox()
        self.note_interval_spin.setRange(5, 600)
        self.note_interval_spin.setSuffix(" s")
        form_ui.addRow("Intervalle auto-save notes :", self.note_interval_spin)

        grp_ui.setLayout(form_ui)
        layout.addWidget(grp_ui)

        # ── 4. Barre rapide ───────────────────────────────
        grp_apps = QGroupBox("⚡ Barre rapide — Applications")
        apps_layout = QVBoxLayout()

        help_lbl = QLabel(
            "Ajoutez des applications à ouvrir rapidement depuis la barre latérale.\n"
            "Commande : utilisez {path} pour insérer le chemin du projet.  Ex : code {path}"
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("font-size: 11px; color: #6c7086;")
        apps_layout.addWidget(help_lbl)

        self.apps_list = QListWidget()
        self.apps_list.setMaximumHeight(130)
        apps_layout.addWidget(self.apps_list)

        app_row = QFormLayout()
        self.app_name_edit = QLineEdit()
        self.app_name_edit.setPlaceholderText("VS Code")
        app_row.addRow("Nom :", self.app_name_edit)

        self.app_cmd_edit = QLineEdit()
        self.app_cmd_edit.setPlaceholderText("code {path}")
        app_row.addRow("Commande :", self.app_cmd_edit)

        self.app_icon_edit = QLineEdit()
        self.app_icon_edit.setPlaceholderText("💙")
        self.app_icon_edit.setMaximumWidth(60)
        app_row.addRow("Icône :", self.app_icon_edit)

        apps_layout.addLayout(app_row)

        btn_app_row = QHBoxLayout()
        btn_add_app = QPushButton("➕ Ajouter")
        btn_add_app.clicked.connect(self._add_quick_app)
        btn_remove_app = QPushButton("🗑️ Supprimer")
        btn_remove_app.clicked.connect(self._remove_quick_app)
        btn_app_row.addWidget(btn_add_app)
        btn_app_row.addWidget(btn_remove_app)
        btn_app_row.addStretch()
        apps_layout.addLayout(btn_app_row)

        grp_apps.setLayout(apps_layout)
        layout.addWidget(grp_apps)

        # ── 5. GitHub OAuth ───────────────────────────────
        grp_gh = QGroupBox("🐙 GitHub OAuth")
        form_gh = QFormLayout()

        self.client_id_edit = QLineEdit()
        self.client_id_edit.setPlaceholderText("Votre GitHub OAuth App Client ID")
        self.client_id_edit.setEchoMode(QLineEdit.Password)
        form_gh.addRow("Client ID :", self.client_id_edit)

        show_btn = QPushButton("👁 Afficher")
        show_btn.setObjectName("subtle")
        show_btn.setCheckable(True)
        show_btn.toggled.connect(
            lambda checked: self.client_id_edit.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        form_gh.addRow("", show_btn)

        grp_gh.setLayout(form_gh)
        layout.addWidget(grp_gh)

        layout.addStretch()
        scroll.setWidget(container)
        root_layout.addWidget(scroll)

        # ── Boutons bas (hors scroll) ──────────────────
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(20, 8, 20, 16)
        btn_reset = QPushButton("↺ Réinitialiser la config")
        btn_reset.setObjectName("danger")
        btn_reset.clicked.connect(self._reset_config)
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("💾 Enregistrer")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._save)
        btn_bar.addWidget(btn_reset)
        btn_bar.addStretch()
        btn_bar.addWidget(btn_cancel)
        btn_bar.addWidget(btn_save)
        root_layout.addLayout(btn_bar)

        # ── Chargement initial ──────────────────────────
        self._load_current_values()

    # ──────────────────────────────────────────────────

    def _load_current_values(self) -> None:
        storage = core.get_storage_config()
        self.instances_root_edit.setText(storage.get("instances_root") or "")
        self.intents_root_edit.setText(storage.get("intents_root") or "")

        cache = core.get_cache_config()
        idx   = self.cache_mode_combo.findData(cache["mode"])
        self.cache_mode_combo.setCurrentIndex(max(idx, 0))
        self.cache_size_spin.setValue(cache.get("size_limit_mb", 256))

        app_cfg = core.get_app_config()
        self.chk_hide_github_notif.setChecked(
            app_cfg.get("hide_github_not_connected", False)
        )
        self.chk_auto_save_notes.setChecked(app_cfg.get("auto_save_notes", False))
        self.note_interval_spin.setValue(app_cfg.get("note_auto_save_interval", 30))

        # Barre rapide
        self._refresh_apps_list()

        # GitHub OAuth Client ID
        self.client_id_edit.setText(core.get_github_client_id())

    def _refresh_apps_list(self) -> None:
        self.apps_list.clear()
        for app in core.get_quick_apps():
            item = QListWidgetItem(
                f"{app.get('icon','⚡')}  {app['name']}  —  {app['cmd']}"
            )
            item.setData(Qt.UserRole, app)
            self.apps_list.addItem(item)

    def _add_quick_app(self) -> None:
        name = self.app_name_edit.text().strip()
        cmd  = self.app_cmd_edit.text().strip()
        icon = self.app_icon_edit.text().strip() or "⚡"

        if not name or not cmd:
            QMessageBox.warning(self, "Attention",
                                "Renseignez au moins le nom et la commande.")
            return

        apps = core.get_quick_apps()
        if any(a["name"].lower() == name.lower() for a in apps):
            QMessageBox.warning(self, "Doublon",
                                f"Une application nommée '{name}' existe déjà.")
            return

        apps.append({"name": name, "cmd": cmd, "icon": icon})
        core.set_quick_apps(apps)

        self.app_name_edit.clear()
        self.app_cmd_edit.clear()
        self.app_icon_edit.clear()
        self._refresh_apps_list()

    def _remove_quick_app(self) -> None:
        item = self.apps_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Attention",
                                "Sélectionnez une application à supprimer.")
            return
        app_data = item.data(Qt.UserRole)
        apps     = [a for a in core.get_quick_apps()
                    if a["name"] != app_data["name"]]
        core.set_quick_apps(apps)
        self._refresh_apps_list()

    def _browse_dir(self, line_edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choisir un dossier", str(Path.home())
        )
        if path:
            line_edit.setText(path)

    def _create_install_dirs(self) -> None:
        """Crée immédiatement les dossiers instances/intents configurés."""
        inst_root = self.instances_root_edit.text().strip()
        int_root  = self.intents_root_edit.text().strip()

        created = []
        errors  = []

        for label, path_str in [("Instances", inst_root), ("Intents", int_root)]:
            if path_str:
                p = Path(path_str)
            else:
                # Utiliser le chemin par défaut
                p = (core.get_instances_root()
                     if label == "Instances" else core.get_intents_root())
            try:
                p.mkdir(parents=True, exist_ok=True)
                created.append(f"✅ {label} : {p}")
            except Exception as e:
                errors.append(f"❌ {label} : {e}")

        # Créer aussi le dossier data
        try:
            core.get_data_dir()
            created.append(f"✅ Data : {core.get_data_dir()}")
        except Exception as e:
            errors.append(f"❌ Data : {e}")

        msg = "\n".join(created + errors)
        if errors:
            QMessageBox.warning(self, "Dossiers créés (avec erreurs)", msg)
        else:
            QMessageBox.information(self, "Dossiers créés", msg)

    def _save(self) -> None:
        # Stockage
        inst_root = self.instances_root_edit.text().strip() or None
        int_root  = self.intents_root_edit.text().strip()  or None
        core.set_storage_config(inst_root, int_root)

        # Cache
        cache_mode = self.cache_mode_combo.currentData()
        cache_size = self.cache_size_spin.value()
        core.set_cache_config(cache_mode, cache_size)

        # App config
        app_cfg = core.get_app_config()
        app_cfg["hide_github_not_connected"] = (
            self.chk_hide_github_notif.isChecked()
        )
        app_cfg["auto_save_notes"]           = self.chk_auto_save_notes.isChecked()
        app_cfg["note_auto_save_interval"]   = self.note_interval_spin.value()
        core.set_app_config(app_cfg)

        # GitHub Client ID
        cid = self.client_id_edit.text().strip()
        if cid:
            core.set_github_client_id(cid)

        QMessageBox.information(
            self, "Configuration enregistrée",
            "Les paramètres ont été sauvegardés.\n"
            "Certains changements nécessitent un redémarrage."
        )
        self.accept()

    def _reset_config(self) -> None:
        reply = QMessageBox.question(
            self, "Réinitialiser",
            "Voulez-vous vraiment réinitialiser toute la configuration ?\n\n"
            "⚠ Les listes d'instances et d'intents seront préservées.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            ok, msg = core.repair_config()
            if ok:
                QMessageBox.information(self, "Réinitialisé", msg)
                self._load_current_values()
            else:
                QMessageBox.critical(self, "Erreur", msg)


# ════════════ customize_dialog.py ════════════
class CustomizeProjectDialog(QDialog):
    """Dialogue pour personnaliser un projet sélectionné."""
    
    def __init__(self, project_path: str, project_kind: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.project_kind = project_kind
        self.setWindowTitle("🎨 Personnaliser le projet — Voktora")
        self.setModal(True)
        self.setFixedSize(500, 600)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Informations du projet
        info_group = QGroupBox("📋 Informations du projet")
        info_layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setReadOnly(True)
        info_layout.addRow("Nom:", self.name_edit)
        
        self.path_label = QLabel(project_path)
        self.path_label.setWordWrap(True)
        info_layout.addRow("Chemin:", self.path_label)
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Personnalisation
        custom_group = QGroupBox("🎨 Personnalisation")
        custom_layout = QFormLayout()
        
        # Couleur
        self.color_button = QPushButton("Choisir une couleur")
        self.color_button.clicked.connect(self._choose_color)
        self.color_preview = QLabel("■")
        self.color_preview.setStyleSheet("font-size: 24px;")
        
        color_layout = QHBoxLayout()
        color_layout.addWidget(self.color_preview)
        color_layout.addWidget(self.color_button)
        color_layout.addStretch()
        custom_layout.addRow("Couleur:", color_layout)
        
        # Emoji
        self.emoji_combo = QComboBox()
        self.emoji_combo.setEditable(True)
        self.emoji_combo.addItems([
            "📦", "🎯", "🚀", "⚡", "🔥", "💎", "🌟", 
            "🎨", "🛠️", "📚", "🔬", "🎮", "🌐", "📱",
            "💻", "⌨️", "🖥️", "📊", "📈", "🗂️", "📁",
            "🔐", "🔒", "🔑", "🛡️", "⚙️", "🔧", "🔨"
        ])
        custom_layout.addRow("Emoji:", self.emoji_combo)
        
        # Catégorie
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        
        # Charger les catégories par défaut et personnalisées
        default_categories = [
            "Web", "Desktop", "Mobile", "API", "CLI", "Game", "AI/ML",
            "Data", "DevOps", "Security", "IoT", "Blockchain", "Autre"
        ]
        
        # Récupérer les catégories personnalisées depuis la config
        cfg = core._load_config()
        custom_categories = cfg.get("categories", [])
        
        # Combiner et dédupliquer les catégories
        all_categories = list(set(default_categories + custom_categories))
        all_categories.sort()
        
        self.category_combo.addItems(all_categories)
        
        # Configurer l'autocomplétion
        completer = QCompleter(all_categories)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.category_combo.setCompleter(completer)

        self.language_combo = QComboBox()
        self.language_combo.setEditable(True)
        self.language_combo.addItems([
            "Python", "JavaScript", "TypeScript", "C#", "Java", "Go",
            "PHP", "Ruby", "Shell", "PowerShell", "Rust", "Dart",
            "Kotlin", "Swift", "C++", "C", "HTML", "CSS", "JSON", "Autre"
        ])
        self.language_combo.setCurrentText("")
        custom_layout.addRow("Langage:", self.language_combo)
        
        custom_layout.addRow("Catégorie:", self.category_combo)
        
        custom_group.setLayout(custom_layout)
        layout.addWidget(custom_group)
        
        # Statut
        status_group = QGroupBox("📊 Statut du projet")
        status_layout = QFormLayout()
        
        self.status_combo = QComboBox()
        # Charger tous les statuts (par défaut + personnalisés)
        all_statuses = core.get_all_project_statuses()
        for status_id, status in all_statuses.items():
            self.status_combo.addItem(f"{status.emoji} {status.name}", status_id)
        status_layout.addRow("Statut:", self.status_combo)
        
        # Notes
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Notes personnelles sur le projet...")
        status_layout.addRow("Notes:", self.notes_edit)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Boutons
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_reset = QPushButton("Réinitialiser")
        btn_reset.clicked.connect(self._reset_customization)
        btn_apply = QPushButton("Appliquer")
        btn_apply.setObjectName("primary")
        btn_apply.clicked.connect(self._apply_customization)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_reset)
        btn_layout.addWidget(btn_apply)
        layout.addLayout(btn_layout)
        
        # Charger les données actuelles
        self._load_current_data()
        
    def _load_current_data(self):
        """Charge les données de personnalisation actuelles du projet."""
        entry = core._find_entry(core._load_config(), self.project_kind + "s", Path(self.project_path))
        if entry:
            self.name_edit.setText(entry.get("name", ""))
            
            # Couleur
            color = entry.get("color")
            if color:
                self.color_preview.setStyleSheet(
                f"font-size: 20px; color: {color};"
                f" background: {color}; border-radius: 6px;"
                f" padding: 2px 8px; border: 2px solid #45475a;"
            )
                self.current_color = color
            else:
                self.current_color = "#89b4fa"
                self.color_preview.setStyleSheet(
                    "font-size: 20px; color: #89b4fa; background: #89b4fa;"
                    " border-radius: 6px; padding: 2px 8px; border: 2px solid #45475a;"
                )
            
            # Emoji
            emoji = entry.get("emoji")
            if emoji:
                index = self.emoji_combo.findText(emoji)
                if index >= 0:
                    self.emoji_combo.setCurrentIndex(index)
                else:
                    self.emoji_combo.setCurrentText(emoji)
            
            # Catégorie
            category = entry.get("category")
            if category:
                index = self.category_combo.findText(category)
                if index >= 0:
                    self.category_combo.setCurrentIndex(index)
                else:
                    self.category_combo.setCurrentText(category)
            
            # Statut
            status = entry.get("status", core.DEFAULT_PROJECT_STATUS)
            index = self.status_combo.findData(status)
            if index >= 0:
                self.status_combo.setCurrentIndex(index)
            else:
                self.status_combo.setCurrentIndex(0)  # Premier statut (par défaut)
            
            # Langage
            self.language_combo.setCurrentText(entry.get("language", "") or "")
            
            # Notes
            self.notes_edit.setText(entry.get("note", ""))
        else:
            # Valeurs par défaut
            self.current_color = "#89b4fa"
            self.color_preview.setStyleSheet("font-size: 24px; color: #89b4fa;")
            
    def _choose_color(self):
        """Ouvre le dialogue de sélection de couleur."""
        color = QColorDialog.getColor(QColor(self.current_color), self, "Choisir une couleur")
        if color.isValid():
            self.current_color = color.name()
            self.color_preview.setStyleSheet(f"font-size: 24px; color: {self.current_color};")
            
    def _reset_customization(self):
        """Réinitialise la personnalisation aux valeurs par défaut."""
        self.current_color = "#89b4fa"
        self.color_preview.setStyleSheet("font-size: 24px; color: #89b4fa;")
        self.emoji_combo.setCurrentText("")
        self.category_combo.setCurrentText("")
        self.status_combo.setCurrentIndex(0)  # Premier statut (par défaut)
        self.notes_edit.setText("")
        
    def _apply_customization(self):
        """Applique la personnalisation au projet."""
        try:
            cfg = core._load_config()
            
            # Trouver l'entrée correspondante
            entry = core._find_entry(cfg, self.project_kind + "s", Path(self.project_path))
            if entry:
                entry["color"] = self.current_color if self.current_color != "#89b4fa" else None
                entry["emoji"] = self.emoji_combo.currentText() or None
                entry["category"] = self.category_combo.currentText() or None
                entry["language"] = self.language_combo.currentText() or None
                entry["status"] = self.status_combo.currentData()
                entry["note"] = self.notes_edit.text()
                
                core._save_config(cfg)
                QMessageBox.information(
                    self, "Personnalisation appliquée",
                    "La personnalisation du projet a été enregistrée avec succès."
                )
                self.accept()
            else:
                QMessageBox.critical(self, "Erreur", "Projet introuvable dans la configuration.")
                
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'appliquer la personnalisation :\n{e}")


# ════════════ theme_dialog.py ════════════
class CustomThemeDialog(QDialog):
    """Dialogue pour créer ou modifier un thème personnalisé."""

    # Couleurs clés exposées dans l'éditeur (les plus impactantes visuellement)
    _COLOR_KEYS = [
        ("base",      "Fond principal"),
        ("mantle",    "Fond secondaire / panneaux"),
        ("crust",     "Fond profond / barre de statut"),
        ("surface0",  "Surface 0 (listes, champs)"),
        ("surface1",  "Surface 1 (bordures)"),
        ("surface2",  "Surface 2 (scrollbars)"),
        ("text",      "Texte principal"),
        ("subtext1",  "Texte secondaire"),
        ("overlay0",  "Texte désactivé"),
        ("blue",      "Couleur primaire (accent)"),
        ("lavender",  "Accent 2"),
        ("green",     "Succès / info positive"),
        ("yellow",    "Avertissement"),
        ("red",       "Erreur / danger"),
        ("primary",   "Bouton primary"),
    ]

    def __init__(self, parent=None, theme_data: dict | None = None,
                 theme_name: str = ""):
        super().__init__(parent)
        self._editing = bool(theme_name)
        self._original_name = theme_name

        title = f"✏️ Modifier — {theme_name}" if self._editing else "➕ Nouveau thème"
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(540, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # ── Nom ──
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.name_edit = QLineEdit(theme_data.get("name", "") if theme_data else "")
        self.name_edit.setPlaceholderText("Nom du thème (ex: Mon Thème)")
        form.addRow("Nom :", self.name_edit)

        self.slug_edit = QLineEdit(theme_name)
        self.slug_edit.setPlaceholderText("slug_sans_espace (identifiant fichier)")
        if self._editing:
            self.slug_edit.setEnabled(False)
        form.addRow("Identifiant :", self.slug_edit)

        self.desc_edit = QLineEdit(theme_data.get("description", "") if theme_data else "")
        self.desc_edit.setPlaceholderText("Description courte du thème")
        form.addRow("Description :", self.desc_edit)
        layout.addLayout(form)

        # ── Copier depuis un thème existant ──
        row_copy = QHBoxLayout()
        lbl_copy = QLabel("Partir de :")
        self.base_combo = QComboBox()
        for t in theme_manager.get_available_themes():
            self.base_combo.addItem(t)
        btn_copy = QPushButton("Copier les couleurs")
        btn_copy.clicked.connect(self._copy_from_base)
        row_copy.addWidget(lbl_copy)
        row_copy.addWidget(self.base_combo, 1)
        row_copy.addWidget(btn_copy)
        layout.addLayout(row_copy)

        # ── Éditeur de couleurs ──
        lbl_colors = QLabel("Couleurs :")
        lbl_colors.setStyleSheet("font-weight:bold;")
        layout.addWidget(lbl_colors)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        color_widget = QWidget()
        self._color_grid = QFormLayout(color_widget)
        self._color_grid.setLabelAlignment(Qt.AlignRight)
        self._color_grid.setVerticalSpacing(6)
        scroll.setWidget(color_widget)
        layout.addWidget(scroll, 1)

        self._color_edits: dict[str, QLineEdit] = {}
        init_colors = (theme_data or {}).get("colors", {})
        for key, label in self._COLOR_KEYS:
            row_w = QWidget()
            row_h = QHBoxLayout(row_w)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(6)

            edit = QLineEdit(init_colors.get(key, "#1e1e2e"))
            edit.setMaximumWidth(100)
            edit.setPlaceholderText("#rrggbb")
            self._color_edits[key] = edit

            preview = QLabel()
            preview.setFixedSize(22, 22)
            preview.setStyleSheet(
                f"background:{init_colors.get(key,'#1e1e2e')};"
                "border:1px solid #555; border-radius:3px;"
            )

            def _make_picker(e=edit, p=preview):
                def _pick():
                    col = QColorDialog.getColor(
                        QColor(e.text()), self, "Choisir une couleur"
                    )
                    if col.isValid():
                        e.setText(col.name())
                        p.setStyleSheet(
                            f"background:{col.name()};"
                            "border:1px solid #555; border-radius:3px;"
                        )
                return _pick

            def _make_update(e=edit, p=preview):
                def _upd(text):
                    if len(text) in (4, 7) and text.startswith("#"):
                        p.setStyleSheet(
                            f"background:{text};"
                            "border:1px solid #555; border-radius:3px;"
                        )
                return _upd

            edit.textChanged.connect(_make_update())
            btn_pick = QPushButton("…")
            btn_pick.setFixedWidth(28)
            btn_pick.setToolTip("Ouvrir le sélecteur de couleur")
            btn_pick.clicked.connect(_make_picker())

            row_h.addWidget(edit)
            row_h.addWidget(preview)
            row_h.addWidget(btn_pick)
            row_h.addStretch()
            self._color_grid.addRow(f"{label} ({key}) :", row_w)

        # ── Boutons ──
        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("💾 Enregistrer")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

    # ──────────────────────────────────────────────────

    def _copy_from_base(self) -> None:
        base_name = self.base_combo.currentText()
        try:
            base = theme_manager.load_theme(base_name)
            colors = base.get("colors", {})
            for key, _ in self._COLOR_KEYS:
                if key in colors and key in self._color_edits:
                    self._color_edits[key].setText(colors[key])
            if not self.name_edit.text():
                self.name_edit.setText(f"Copie de {base.get('name', base_name)}")
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Impossible de charger le thème : {e}")

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        slug = self.slug_edit.text().strip().replace(" ", "_").lower()

        if not name:
            QMessageBox.warning(self, "Champ manquant", "Le nom du thème est obligatoire.")
            return
        if not slug:
            QMessageBox.warning(self, "Champ manquant",
                                "L'identifiant (slug) est obligatoire.")
            return

        colors = {key: self._color_edits[key].text().strip()
                  for key, _ in self._COLOR_KEYS}

        # Valider les couleurs hex
        import re
        bad = [k for k, v in colors.items()
               if not re.match(r"^#[0-9a-fA-F]{3,6}$", v)]
        if bad:
            QMessageBox.warning(
                self, "Couleur invalide",
                f"Couleur(s) invalide(s) : {', '.join(bad)}\n"
                "Format attendu : #rrggbb ou #rgb"
            )
            return

        theme_data = {
            "name":        name,
            "description": self.desc_edit.text().strip(),
            "colors":      colors,
        }

        try:
            dest = theme_manager.THEMES_DIR / f"{slug}.json"
            theme_manager.THEMES_DIR.mkdir(parents=True, exist_ok=True)
            import json as _json
            dest.write_text(
                _json.dumps(theme_data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            QMessageBox.information(
                self, "Thème enregistré",
                f"Le thème '{name}' a été enregistré."
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible d'enregistrer le thème :\n{e}")


class ThemeSettingsDialog(QDialog):
    """Dialogue pour choisir, créer, importer et exporter des thèmes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎨 Paramètres de thème — Voktora")
        self.setModal(True)
        self.setMinimumSize(520, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # ── Titre ──
        title = QLabel("🎨 Choisissez un thème")
        title.setObjectName("sectionLbl")
        layout.addWidget(title)

        # ── Liste des thèmes ──
        self.theme_list = QListWidget()
        self.theme_list.setMinimumHeight(160)
        layout.addWidget(self.theme_list)

        # ── Description ──
        self.desc_label = QLabel("")
        self.desc_label.setWordWrap(True)
        self.desc_label.setObjectName("sectionLbl")
        layout.addWidget(self.desc_label)

        # ── Rangée 1 : actions sur les thèmes ──
        row1 = QHBoxLayout()
        btn_create = QPushButton("➕ Créer")
        btn_create.clicked.connect(self._create_custom_theme)
        btn_edit = QPushButton("✏️ Modifier")
        btn_edit.clicked.connect(self._edit_theme)
        btn_delete = QPushButton("🗑 Supprimer")
        btn_delete.setObjectName("danger")
        btn_delete.clicked.connect(self._delete_theme)
        row1.addWidget(btn_create)
        row1.addWidget(btn_edit)
        row1.addWidget(btn_delete)
        row1.addStretch()
        layout.addLayout(row1)

        # ── Rangée 2 : import / export ──
        row2 = QHBoxLayout()
        btn_import = QPushButton("📥 Importer un thème…")
        btn_import.clicked.connect(self._import_theme)
        btn_export = QPushButton("📤 Exporter ce thème…")
        btn_export.clicked.connect(self._export_theme)
        row2.addWidget(btn_import)
        row2.addWidget(btn_export)
        row2.addStretch()
        layout.addLayout(row2)

        # ── Rangée 3 : Annuler / Appliquer ──
        row3 = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_apply = QPushButton("✔ Appliquer")
        btn_apply.setObjectName("primary")
        btn_apply.clicked.connect(self._apply_theme)
        row3.addStretch()
        row3.addWidget(btn_cancel)
        row3.addWidget(btn_apply)
        layout.addLayout(row3)

        # ── Connexions ──
        self._load_themes()
        self.theme_list.currentItemChanged.connect(self._on_theme_changed)

    # ──────────────────────────────────────────────────

    def _load_themes(self) -> None:
        self.theme_list.clear()
        try:
            themes       = theme_manager.get_available_themes()
            current_theme = core.get_app_config().get("theme", "default")

            for theme_name in themes:
                try:
                    theme_data = theme_manager.load_theme(theme_name)
                    display    = f"🎨 {theme_data.get('name', theme_name)}"
                    if theme_name == current_theme:
                        display += "  ✓"
                    item = QListWidgetItem(display)
                    item.setData(Qt.UserRole, theme_name)
                    if theme_name == current_theme:
                        item.setSelected(True)
                    self.theme_list.addItem(item)
                except Exception as e:
                    print(f"Erreur chargement thème {theme_name}: {e}")

        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible de charger les thèmes :\n{e}")

    def _on_theme_changed(self, current, previous) -> None:
        if current:
            theme_name = current.data(Qt.UserRole)
            try:
                theme_data = theme_manager.load_theme(theme_name)
                self.desc_label.setText(
                    f"<i>{theme_data.get('description', 'Pas de description')}</i>"
                )
            except Exception:
                self.desc_label.setText("Erreur lors du chargement de la description")
        else:
            self.desc_label.setText("")

    def _apply_theme(self) -> None:
        current_item = self.theme_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention", "Veuillez sélectionner un thème.")
            return
        theme_name = current_item.data(Qt.UserRole)
        try:
            theme_manager.set_theme(theme_name)
            theme_manager.apply_theme_to_app(QApplication.instance())
            QMessageBox.information(
                self, "Thème appliqué",
                f"Le thème '{theme_name}' a été appliqué.\n\n"
                "Redémarrez l'application pour voir tous les changements."
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible d'appliquer le thème :\n{e}")

    # ── Créer / Modifier / Supprimer ──────────────────

    def _create_custom_theme(self) -> None:
        dlg = CustomThemeDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self._load_themes()

    def _edit_theme(self) -> None:
        current_item = self.theme_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention",
                                "Veuillez sélectionner un thème à modifier.")
            return
        theme_name = current_item.data(Qt.UserRole)
        if theme_name in ("default", "dark", "light"):
            QMessageBox.warning(self, "Thème protégé",
                                f"Le thème '{theme_name}' est un thème par défaut "
                                "et ne peut pas être modifié.")
            return
        try:
            theme_data = theme_manager.load_theme(theme_name)
            dlg = CustomThemeDialog(self, theme_data, theme_name)
            if dlg.exec() == QDialog.Accepted:
                self._load_themes()
        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible de charger le thème pour modification :\n{e}")

    def _delete_theme(self) -> None:
        current_item = self.theme_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention",
                                "Veuillez sélectionner un thème à supprimer.")
            return
        theme_name = current_item.data(Qt.UserRole)
        if theme_name in ("default", "dark", "light"):
            QMessageBox.warning(self, "Thème protégé",
                                f"Le thème '{theme_name}' est protégé et ne peut pas être supprimé.")
            return
        reply = QMessageBox.question(
            self, "Supprimer",
            f"Supprimer le thème '{theme_name}' ?\n\nCette action est irréversible.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            theme_path = theme_manager.THEMES_DIR / f"{theme_name}.json"
            if theme_path.exists():
                theme_path.unlink()
                QMessageBox.information(self, "Succès",
                                        f"Thème '{theme_name}' supprimé.")
                self._load_themes()
            else:
                QMessageBox.warning(self, "Erreur",
                                    f"Fichier du thème '{theme_name}' introuvable.")
        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                                 f"Impossible de supprimer le thème :\n{e}")

    # ── Import / Export ───────────────────────────────

    def _import_theme(self) -> None:
        """Importe un fichier .json de thème dans le dossier des thèmes."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Importer un thème Voktora",
            str(Path.home()),
            "Thèmes JSON (*.json);;Tous les fichiers (*)",
        )
        if not file_path:
            return

        try:
            theme_name = theme_manager.import_theme(Path(file_path))
            QMessageBox.information(
                self, "Thème importé",
                f"Le thème '{theme_name}' a été importé avec succès !\n"
                "Il est maintenant disponible dans la liste."
            )
            self._load_themes()

        except FileExistsError as e:
            QMessageBox.warning(self, "Thème existant", str(e))
        except ValueError as e:
            QMessageBox.critical(self, "Fichier invalide",
                                 f"Impossible d'importer ce fichier :\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Import échoué :\n{e}")

    def _export_theme(self) -> None:
        """Exporte le thème sélectionné vers un fichier .json."""
        current_item = self.theme_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Attention",
                                "Veuillez sélectionner un thème à exporter.")
            return

        theme_name = current_item.data(Qt.UserRole)

        dest_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter le thème",
            str(Path.home() / f"{theme_name}.json"),
            "Thèmes JSON (*.json);;Tous les fichiers (*)",
        )
        if not dest_path:
            return

        try:
            exported = theme_manager.export_theme(theme_name, Path(dest_path))
            QMessageBox.information(
                self, "Thème exporté",
                f"Le thème '{theme_name}' a été exporté vers :\n{exported}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Export échoué :\n{e}")


# ════════════ encrypt_dialog.py ════════════
def _is_operation_running() -> bool:
    return _operation_in_progress



def _set_operation(state: bool) -> None:
    global _operation_in_progress
    _operation_in_progress = state


# ──────────────────────────────────────────────
# WORKER — Chiffrement en arrière-plan
# ──────────────────────────────────────────────


class EncryptWorker(QThread):
    """Chiffre/déchiffre récursivement un dossier dans un thread séparé."""

    progress_text  = Signal(str)   # Message de statut
    progress_value = Signal(int)   # Pourcentage 0-100
    finished       = Signal(bool, str)  # (succès, message)

    def __init__(self, path: Path, password: str, mode: str):
        """
        mode : "encrypt" ou "decrypt"
        """
        super().__init__()
        self._path     = path
        self._password = password
        self._mode     = mode

    def run(self) -> None:
        try:
            if self._mode == "encrypt":
                self._do_encrypt()
            else:
                self._do_decrypt()
            self.finished.emit(True, "Opération terminée avec succès.")
        except Exception as e:
            self.finished.emit(False, str(e))

    # ── Dérivation de clé ──────────────────────────

    @staticmethod
    def _derive_key(password: str) -> bytes:
        return hashlib.sha512(password.encode("utf-8")).digest()

    # ── Chiffrement ────────────────────────────────

    def _do_encrypt(self) -> None:
        files = [f for f in self._path.rglob("*")
                 if f.is_file() and not f.name.startswith(".")]
        total = len(files)
        if total == 0:
            return

        key = self._derive_key(self._password)

        for i, file_path in enumerate(files):
            # Ignorer les fichiers déjà chiffrés
            if file_path.suffix == ".menc":
                continue
            self.progress_text.emit(f"Chiffrement : {file_path.name}")
            self.progress_value.emit(int(i / total * 90))

            try:
                with open(file_path, "rb") as f:
                    data = f.read()

                encrypted = bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])
                enc_path  = file_path.with_suffix(file_path.suffix + ".menc")

                with open(enc_path, "wb") as f:
                    f.write(encrypted)

                file_path.unlink()

            except Exception as e:
                self.progress_text.emit(f"⚠ Ignoré : {file_path.name} ({e})")

        # Marqueur de chiffrement
        marker = self._path / ".voktora_encrypted"
        marker.write_text(
            f"Encrypted with Voktora v{core.APP_VERSION}\n"
            f"Date: {datetime.now().isoformat()}\n"
        )
        self.progress_value.emit(100)

    # ── Déchiffrement ──────────────────────────────

    def _do_decrypt(self) -> None:
        files = [f for f in self._path.rglob("*.menc") if f.is_file()]
        total = len(files)
        if total == 0:
            # Tenter l'ancien format (.encrypted)
            files = [f for f in self._path.rglob("*.encrypted") if f.is_file()]
            total = len(files)

        if total == 0:
            self.progress_value.emit(100)
            return

        key = self._derive_key(self._password)

        for i, file_path in enumerate(files):
            self.progress_text.emit(f"Déchiffrement : {file_path.name}")
            self.progress_value.emit(int(i / total * 90))

            try:
                with open(file_path, "rb") as f:
                    encrypted_data = f.read()

                decrypted = bytes([b ^ key[i % len(key)] for i, b in enumerate(encrypted_data)])

                # Retirer l'extension .menc ou .encrypted
                if file_path.suffix == ".menc":
                    original_path = file_path.with_suffix("")
                elif file_path.suffix == ".encrypted":
                    original_path = Path(str(file_path)[:-10])
                else:
                    continue

                with open(original_path, "wb") as f:
                    f.write(decrypted)

                file_path.unlink()

            except Exception as e:
                self.progress_text.emit(f"⚠ Ignoré : {file_path.name} ({e})")

        # Supprimer le marqueur
        marker = self._path / ".voktora_encrypted"
        if marker.exists():
            marker.unlink()

        self.progress_value.emit(100)


# ──────────────────────────────────────────────
# WORKER — Copie/backup avec progression
# ──────────────────────────────────────────────


class CopyWorker(QThread):
    """Copie un dossier avec progression en arrière-plan."""

    progress_text  = Signal(str)
    progress_value = Signal(int)
    finished       = Signal(bool, str)

    def __init__(self, src: Path, dst: Path):
        super().__init__()
        self._src = src
        self._dst = dst

    def run(self) -> None:
        try:
            files = [f for f in self._src.rglob("*") if f.is_file()]
            total = len(files)
            self._dst.mkdir(parents=True, exist_ok=True)

            for i, src_file in enumerate(files):
                rel = src_file.relative_to(self._src)
                dst_file = self._dst / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)

                self.progress_text.emit(f"Copie : {src_file.name}")
                self.progress_value.emit(int(i / max(total, 1) * 100))

                shutil.copy2(src_file, dst_file)

            self.progress_value.emit(100)
            self.finished.emit(True, f"Copie terminée vers {self._dst}")
        except Exception as e:
            self.finished.emit(False, str(e))


# ──────────────────────────────────────────────
# DIALOGUE PRINCIPAL
# ──────────────────────────────────────────────


class EncryptProjectDialog(QDialog):
    """Dialogue pour chiffrer/déchiffrer un projet avec barre de progression."""

    def __init__(self, project_path: str, project_kind: str, parent=None):
        super().__init__(parent)
        self.project_path  = Path(project_path)
        self.project_kind  = project_kind
        self._worker: EncryptWorker | None = None
        self._copy_worker: CopyWorker | None = None

        self.setWindowTitle("🔐 Chiffrement de projet — Voktora")
        self.setModal(True)
        self.setMinimumSize(480, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ── Informations du projet ──
        info_group = QGroupBox("📋 Projet")
        info_layout = QFormLayout()

        path_label = QLabel(str(self.project_path))
        path_label.setWordWrap(True)
        info_layout.addRow("Chemin :", path_label)

        self.is_encrypted = self._check_if_encrypted()
        status_text  = "🔒 Chiffré" if self.is_encrypted else "🔓 Non chiffré"
        status_color = "#f38ba8" if self.is_encrypted else "#a6e3a1"
        status_lbl   = QLabel(f"<b>{status_text}</b>")
        status_lbl.setStyleSheet(f"color: {status_color}; font-size: 14px;")
        info_layout.addRow("État :", status_lbl)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # ── Mot de passe ──
        pwd_group = QGroupBox("🔑 Mot de passe")
        pwd_layout = QVBoxLayout()

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Entrez le mot de passe...")
        pwd_layout.addWidget(self.password_edit)

        if not self.is_encrypted:
            self.confirm_edit = QLineEdit()
            self.confirm_edit.setEchoMode(QLineEdit.Password)
            self.confirm_edit.setPlaceholderText("Confirmez le mot de passe...")
            pwd_layout.addWidget(self.confirm_edit)
        else:
            self.confirm_edit = None

        pwd_group.setLayout(pwd_layout)
        layout.addWidget(pwd_group)

        # ── Options ──
        if not self.is_encrypted:
            self.chk_backup = QCheckBox("Créer une sauvegarde avant chiffrement")
            self.chk_backup.setChecked(True)
            layout.addWidget(self.chk_backup)
        else:
            self.chk_backup = None

        # ── Progression ──
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # ── Boutons ──
        btn_layout = QHBoxLayout()

        if self.is_encrypted:
            self.btn_action = QPushButton("🔓 Déchiffrer")
            self.btn_action.setObjectName("success")
            self.btn_action.clicked.connect(self._start_decrypt)
        else:
            self.btn_action = QPushButton("🔒 Chiffrer")
            self.btn_action.setObjectName("primary")
            self.btn_action.clicked.connect(self._start_encrypt)

        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self._on_cancel)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_action)
        layout.addLayout(btn_layout)

    # ── Helpers ────────────────────────────────────

    def _check_if_encrypted(self) -> bool:
        return (self.project_path / ".voktora_encrypted").exists()

    def _lock_ui(self, locked: bool) -> None:
        """Active/désactive les contrôles pendant une opération."""
        self.btn_action.setEnabled(not locked)
        self.password_edit.setEnabled(not locked)
        if self.confirm_edit:
            self.confirm_edit.setEnabled(not locked)
        if self.chk_backup:
            self.chk_backup.setEnabled(not locked)
        self.progress_bar.setVisible(locked)

    # ── Chiffrement ────────────────────────────────

    def _start_encrypt(self) -> None:
        # Vérifier qu'aucune opération n'est déjà en cours
        if _is_operation_running():
            QMessageBox.warning(
                self, "Opération en cours",
                "Une opération de chiffrement ou de copie est déjà en cours.\n"
                "Attendez qu'elle se termine avant d'en lancer une autre."
            )
            return

        password = self.password_edit.text()
        confirm  = self.confirm_edit.text() if self.confirm_edit else password

        if not password:
            QMessageBox.warning(self, "Attention", "Veuillez entrer un mot de passe.")
            return
        if password != confirm:
            QMessageBox.warning(self, "Attention", "Les mots de passe ne correspondent pas.")
            return
        if len(password) < 8:
            QMessageBox.warning(self, "Attention", "Le mot de passe doit contenir au moins 8 caractères.")
            return

        # Backup si demandé
        if self.chk_backup and self.chk_backup.isChecked():
            backup_path = (self.project_path.parent /
                           f"{self.project_path.name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            self._lock_ui(True)
            self.lbl_status.setText("📦 Création de la sauvegarde...")
            _set_operation(True)

            self._copy_worker = CopyWorker(self.project_path, backup_path)
            self._copy_worker.progress_text.connect(self.lbl_status.setText)
            self._copy_worker.progress_value.connect(self.progress_bar.setValue)
            self._copy_worker.finished.connect(
                lambda ok, msg: self._on_backup_done(ok, msg, password)
            )
            self._copy_worker.start()
        else:
            _set_operation(True)
            self._run_encrypt(password)

    def _on_backup_done(self, ok: bool, msg: str, password: str) -> None:
        if not ok:
            _set_operation(False)
            self._lock_ui(False)
            QMessageBox.critical(self, "Erreur backup", f"Sauvegarde échouée :\n{msg}")
            return
        self._run_encrypt(password)

    def _run_encrypt(self, password: str) -> None:
        self._lock_ui(True)
        self.lbl_status.setText("🔒 Chiffrement en cours...")
        self.progress_bar.setValue(0)

        self._worker = EncryptWorker(self.project_path, password, "encrypt")
        self._worker.progress_text.connect(self.lbl_status.setText)
        self._worker.progress_value.connect(self.progress_bar.setValue)
        self._worker.finished.connect(self._on_encrypt_done)
        self._worker.start()

    def _on_encrypt_done(self, ok: bool, msg: str) -> None:
        _set_operation(False)
        self._lock_ui(False)

        if ok:
            algo = "Whirlpool" if core._whirlpool_available() else "SHA-512"
            QMessageBox.information(
                self, "Chiffrement réussi",
                f"Le projet a été chiffré avec succès.\n\n"
                f"Algorithme : {algo}\n"
                "⚠ Ne perdez pas votre mot de passe !"
            )
            self.accept()
        else:
            QMessageBox.critical(self, "Erreur", f"Chiffrement échoué :\n{msg}")

    # ── Déchiffrement ──────────────────────────────

    def _start_decrypt(self) -> None:
        if _is_operation_running():
            QMessageBox.warning(
                self, "Opération en cours",
                "Une opération de chiffrement ou de copie est déjà en cours.\n"
                "Attendez qu'elle se termine avant d'en lancer une autre."
            )
            return

        password = self.password_edit.text()
        if not password:
            QMessageBox.warning(self, "Attention", "Veuillez entrer le mot de passe.")
            return

        _set_operation(True)
        self._lock_ui(True)
        self.lbl_status.setText("🔓 Déchiffrement en cours...")
        self.progress_bar.setValue(0)

        self._worker = EncryptWorker(self.project_path, password, "decrypt")
        self._worker.progress_text.connect(self.lbl_status.setText)
        self._worker.progress_value.connect(self.progress_bar.setValue)
        self._worker.finished.connect(self._on_decrypt_done)
        self._worker.start()

    def _on_decrypt_done(self, ok: bool, msg: str) -> None:
        _set_operation(False)
        self._lock_ui(False)

        if ok:
            QMessageBox.information(self, "Déchiffrement réussi",
                                    "Le projet a été déchiffré avec succès.")
            self.accept()
        else:
            QMessageBox.critical(self, "Erreur", f"Déchiffrement échoué :\n{msg}")

    # ── Fermeture ──────────────────────────────────

    def _on_cancel(self) -> None:
        if _is_operation_running():
            reply = QMessageBox.question(
                self, "Annuler ?",
                "Une opération est en cours. Voulez-vous vraiment annuler ?\n"
                "⚠ Annuler en cours de chiffrement peut corrompre les fichiers !",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            # Tenter d'arrêter les workers
            for worker in [self._worker, self._copy_worker]:
                if worker and worker.isRunning():
                    worker.terminate()
                    worker.wait(2000)
            _set_operation(False)
        self.reject()

    def closeEvent(self, event) -> None:
        if _is_operation_running():
            event.ignore()
            self._on_cancel()
        else:
            super().closeEvent(event)


# ════════════ migrate_dialog.py ════════════
class ExportWorker(QThread):
    progress_signal = Signal(str, int)
    finished        = Signal(bool, str, list, list)

    def __init__(self, dest: Path):
        super().__init__()
        self._dest = dest

    def run(self) -> None:
        res = mc.export_bundle(
            self._dest,
            on_progress=lambda msg, pct: self.progress_signal.emit(msg, pct),
        )
        self.finished.emit(res.success, res.message, res.log, res.warnings)



class ImportWorker(QThread):
    progress_signal = Signal(str, int)
    finished        = Signal(bool, str, list, list)

    def __init__(self, src: Path, base: Path, rules: list):
        super().__init__()
        self._src   = src
        self._base  = base
        self._rules = rules

    def run(self) -> None:
        res = mc.import_bundle(
            self._src, self._base,
            custom_rules=self._rules,
            on_progress=lambda msg, pct: self.progress_signal.emit(msg, pct),
        )
        self.finished.emit(res.success, res.message, res.log, res.warnings)


# ──────────────────────────────────────────────
# DIALOGUE PRINCIPAL
# ──────────────────────────────────────────────


class MigrateDialog(QDialog):
    """
    Dialogue de migration complète.
    Deux onglets : Export (créer bundle) et Import (restaurer bundle).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔀 Migration de projets — Voktora")
        self.setModal(True)
        self.setMinimumSize(640, 580)

        self._export_worker: ExportWorker | None = None
        self._import_worker: ImportWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)

        # ── En-tête ──
        hdr = QLabel(
            "🔀 <b>Migration Voktora</b> — Transfert de projets Windows ↔ Linux"
        )
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        desc = QLabel(
            "Exportez un bundle <b>.mpack</b> depuis cette machine, puis importez-le "
            "sur la machine cible. Les chemins sont remappés automatiquement."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(desc)

        # ── Onglets ──
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_export_tab(), "📤 Exporter (cette machine)")
        self._tabs.addTab(self._build_import_tab(), "📥 Importer (bundle reçu)")
        layout.addWidget(self._tabs)

        # ── Journal ──
        log_group = QGroupBox("📋 Journal")
        log_layout = QVBoxLayout()
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumHeight(160)
        self._log_edit.setObjectName("noteEdit")
        log_layout.addWidget(self._log_edit)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # ── Barre de progression ──
        self._progress_lbl = QLabel("")
        self._progress_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(self._progress_lbl)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # ── Bouton fermer ──
        btn_row = QHBoxLayout()
        self._btn_close = QPushButton("Fermer")
        self._btn_close.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        layout.addLayout(btn_row)

    # ──────────────────────────────────────────────
    # ONGLET EXPORT
    # ──────────────────────────────────────────────

    def _build_export_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Info plateforme
        import core as _core
        platform_str = "Windows" if sys.platform == "win32" else "Linux/RPi"
        info = QLabel(
            f"Plateforme actuelle : <b>{platform_str}</b>\n"
            f"Version Voktora    : <b>v{_core.APP_VERSION}</b>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        grp = QGroupBox("📦 Destination du bundle")
        form = QFormLayout()

        self._export_dest_edit = QLineEdit()
        self._export_dest_edit.setPlaceholderText("Chemin du fichier .mpack à créer…")
        btn_browse = QPushButton("…")
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse_export_dest)
        row = QHBoxLayout()
        row.addWidget(self._export_dest_edit)
        row.addWidget(btn_browse)
        form.addRow("Fichier .mpack :", row)

        # Préfiller un nom par défaut
        import core as _core
        ts   = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        host = mc._safe_hostname()
        default_name = f"voktora_{host}_{ts}.mpack"
        default_path = Path.home() / default_name
        self._export_dest_edit.setText(str(default_path))

        grp.setLayout(form)
        layout.addWidget(grp)

        # Résumé des projets à exporter
        grp2 = QGroupBox("📋 Projets inclus dans le bundle")
        grp2_layout = QVBoxLayout()
        self._export_summary = QLabel(self._build_export_summary())
        self._export_summary.setWordWrap(True)
        self._export_summary.setStyleSheet("font-size: 12px; color: #a6adc8;")
        grp2_layout.addWidget(self._export_summary)
        grp2.setLayout(grp2_layout)
        layout.addWidget(grp2)

        layout.addStretch()

        self._btn_export = QPushButton("📤 Créer le bundle de migration")
        self._btn_export.setObjectName("primary")
        self._btn_export.clicked.connect(self._start_export)
        layout.addWidget(self._btn_export)

        return w

    def _build_export_summary(self) -> str:
        try:
            import core as _core
            cfg  = _core._load_config()
            inst = cfg.get("instances", [])
            intn = cfg.get("intents",   [])
            ok_i = sum(1 for e in inst if Path(e["path"]).exists())
            ok_n = sum(1 for e in intn if Path(e["path"]).exists())
            miss_i = len(inst) - ok_i
            miss_n = len(intn) - ok_n
            lines = [
                f"  📦 Instances : {ok_i} valide(s)" +
                (f", {miss_i} absente(s) du disque" if miss_i else ""),
                f"  🌱 Intents   : {ok_n} valide(s)" +
                (f", {miss_n} absent(s) du disque" if miss_n else ""),
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"Impossible de lire la config : {e}"

    def _browse_export_dest(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Choisir la destination du bundle",
            self._export_dest_edit.text() or str(Path.home()),
            "Bundle Voktora (*.mpack);;Tous les fichiers (*)"
        )
        if path:
            if not path.endswith(".mpack"):
                path += ".mpack"
            self._export_dest_edit.setText(path)

    def _start_export(self) -> None:
        dest_str = self._export_dest_edit.text().strip()
        if not dest_str:
            QMessageBox.warning(self, "Attention",
                                "Choisissez un emplacement de destination.")
            return
        dest = Path(dest_str)
        if dest.exists():
            r = QMessageBox.question(
                self, "Fichier existant",
                f"Le fichier {dest.name} existe déjà.\nL'écraser ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if r != QMessageBox.Yes:
                return

        self._lock(True)
        self._log("─── Démarrage de l'export ───")
        self._export_worker = ExportWorker(dest)
        self._export_worker.progress_signal.connect(self._on_progress)
        self._export_worker.finished.connect(self._on_export_done)
        self._export_worker.start()

    def _on_export_done(self, ok: bool, msg: str, log: list, warn: list) -> None:
        self._lock(False)
        self._progress_bar.setVisible(False)
        self._progress_lbl.setText("")
        for line in log:
            self._log(line)
        for w in warn:
            self._log(f"⚠ {w}", color="#fab387")
        if ok:
            dest = self._export_dest_edit.text()
            self._log(f"✅ {msg}", color="#a6e3a1")
            QMessageBox.information(
                self, "Export réussi",
                f"Le bundle de migration a été créé :\n\n{dest}\n\n"
                "Copiez ce fichier sur la machine cible et utilisez l'onglet "
                "« Importer » pour restaurer vos projets."
            )
        else:
            self._log(f"❌ {msg}", color="#f38ba8")
            QMessageBox.critical(self, "Erreur d'export", msg)

    # ──────────────────────────────────────────────
    # ONGLET IMPORT
    # ──────────────────────────────────────────────

    def _build_import_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Source
        grp_src = QGroupBox("📦 Bundle à importer")
        form_src = QFormLayout()

        self._import_src_edit = QLineEdit()
        self._import_src_edit.setPlaceholderText("Chemin du fichier .mpack…")
        self._import_src_edit.textChanged.connect(self._on_bundle_changed)
        btn_browse_src = QPushButton("…")
        btn_browse_src.setFixedWidth(32)
        btn_browse_src.clicked.connect(self._browse_import_src)
        row_src = QHBoxLayout()
        row_src.addWidget(self._import_src_edit)
        row_src.addWidget(btn_browse_src)
        form_src.addRow("Fichier .mpack :", row_src)

        # Infos bundle (remplies dynamiquement)
        self._bundle_info_lbl = QLabel("Sélectionnez un fichier .mpack pour voir ses infos.")
        self._bundle_info_lbl.setWordWrap(True)
        self._bundle_info_lbl.setStyleSheet("font-size: 11px; color: #6c7086;")
        form_src.addRow("", self._bundle_info_lbl)

        grp_src.setLayout(form_src)
        layout.addWidget(grp_src)

        # Destination
        grp_dst = QGroupBox("📁 Dossier de destination")
        form_dst = QFormLayout()

        self._import_base_edit = QLineEdit()
        default_base = str(Path.home()) if sys.platform != "win32" else "D:\\"
        self._import_base_edit.setText(default_base)
        self._import_base_edit.setPlaceholderText(
            "Dossier racine (ex: /home/ubuntu ou D:\\)"
        )
        btn_browse_dst = QPushButton("…")
        btn_browse_dst.setFixedWidth(32)
        btn_browse_dst.clicked.connect(self._browse_import_base)
        row_dst = QHBoxLayout()
        row_dst.addWidget(self._import_base_edit)
        row_dst.addWidget(btn_browse_dst)
        form_dst.addRow("Racine :", row_dst)

        hint = QLabel(
            "Les projets seront extraits dans :\n"
            "  <racine>/instances/<nom_projet>/\n"
            "  <racine>/intents/<nom_projet>/"
        )
        hint.setStyleSheet("font-size: 11px; color: #6c7086;")
        hint.setWordWrap(True)
        form_dst.addRow("", hint)

        grp_dst.setLayout(form_dst)
        layout.addWidget(grp_dst)

        # Règles de remappage personnalisées (optionnel)
        grp_rules = QGroupBox("⚙️ Remappage personnalisé (optionnel)")
        rules_layout = QVBoxLayout()

        rules_hint = QLabel(
            "Si les chemins ne sont pas remappés correctement, ajoutez des règles "
            "manuelles (format  ancien_préfixe : nouveau_préfixe)."
        )
        rules_hint.setWordWrap(True)
        rules_hint.setStyleSheet("font-size: 11px; color: #6c7086;")
        rules_layout.addWidget(rules_hint)

        self._rules_list = QListWidget()
        self._rules_list.setMaximumHeight(80)
        rules_layout.addWidget(self._rules_list)

        rule_input_row = QHBoxLayout()
        self._rule_old_edit = QLineEdit()
        self._rule_old_edit.setPlaceholderText("Ancien préfixe  ex: D:\\Projects")
        self._rule_new_edit = QLineEdit()
        self._rule_new_edit.setPlaceholderText("Nouveau préfixe  ex: /home/user/Projects")
        btn_add_rule = QPushButton("➕")
        btn_add_rule.setFixedWidth(32)
        btn_add_rule.clicked.connect(self._add_rule)
        btn_del_rule = QPushButton("🗑")
        btn_del_rule.setFixedWidth(32)
        btn_del_rule.clicked.connect(self._remove_rule)
        rule_input_row.addWidget(self._rule_old_edit)
        rule_input_row.addWidget(QLabel("→"))
        rule_input_row.addWidget(self._rule_new_edit)
        rule_input_row.addWidget(btn_add_rule)
        rule_input_row.addWidget(btn_del_rule)
        rules_layout.addLayout(rule_input_row)

        grp_rules.setLayout(rules_layout)
        layout.addWidget(grp_rules)

        layout.addStretch()

        self._btn_import = QPushButton("📥 Importer le bundle")
        self._btn_import.setObjectName("primary")
        self._btn_import.clicked.connect(self._start_import)
        layout.addWidget(self._btn_import)

        return w

    def _browse_import_src(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Sélectionner un bundle Voktora",
            str(Path.home()),
            "Bundle Voktora (*.mpack);;Fichiers ZIP (*.zip);;Tous les fichiers (*)"
        )
        if path:
            self._import_src_edit.setText(path)

    def _browse_import_base(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier de destination",
            self._import_base_edit.text() or str(Path.home())
        )
        if path:
            self._import_base_edit.setText(path)

    def _on_bundle_changed(self, text: str) -> None:
        """Met à jour les infos du bundle quand l'utilisateur change le chemin."""
        p = Path(text.strip())
        if not p.exists() or not text.strip():
            self._bundle_info_lbl.setText("Sélectionnez un fichier .mpack pour voir ses infos.")
            self._bundle_info_lbl.setStyleSheet("font-size: 11px; color: #6c7086;")
            return
        info = mc.validate_bundle(p)
        if info["valid"]:
            m = info["manifest"]
            src_plat   = m.get("source_platform", "?")
            tgt_plat   = "Linux" if sys.platform != "win32" else "Windows"
            arrow      = f"{src_plat.capitalize()} → {tgt_plat}"
            n_proj     = m.get("_detected_project_count", "?")
            size_kb    = m.get("_bundle_size_kb", "?")
            created    = m.get("created_at", "?")[:16].replace("T", " ")
            self._bundle_info_lbl.setText(
                f"✅ Bundle valide  |  {arrow}  |  {n_proj} projet(s)  "
                f"|  {size_kb} Ko  |  Créé le {created}"
            )
            self._bundle_info_lbl.setStyleSheet("font-size: 11px; color: #a6e3a1;")
        else:
            self._bundle_info_lbl.setText(f"❌ {info['error']}")
            self._bundle_info_lbl.setStyleSheet("font-size: 11px; color: #f38ba8;")

    def _add_rule(self) -> None:
        old = self._rule_old_edit.text().strip()
        new = self._rule_new_edit.text().strip()
        if not old or not new:
            QMessageBox.warning(self, "Attention",
                                "Renseignez l'ancien et le nouveau préfixe.")
            return
        item = QListWidgetItem(f"{old}  →  {new}")
        item.setData(Qt.UserRole, (old, new))
        self._rules_list.addItem(item)
        self._rule_old_edit.clear()
        self._rule_new_edit.clear()

    def _remove_rule(self) -> None:
        item = self._rules_list.currentItem()
        if item:
            self._rules_list.takeItem(self._rules_list.row(item))

    def _get_rules(self) -> list:
        rules = []
        for i in range(self._rules_list.count()):
            item = self._rules_list.item(i)
            rules.append(item.data(Qt.UserRole))
        return rules

    def _start_import(self) -> None:
        src_str  = self._import_src_edit.text().strip()
        base_str = self._import_base_edit.text().strip()

        if not src_str:
            QMessageBox.warning(self, "Attention",
                                "Sélectionnez un bundle .mpack à importer.")
            return
        if not base_str:
            QMessageBox.warning(self, "Attention",
                                "Choisissez un dossier de destination.")
            return

        src  = Path(src_str)
        base = Path(base_str)

        if not src.exists():
            QMessageBox.critical(self, "Erreur",
                                 f"Bundle introuvable : {src}")
            return

        # Valider avant
        info = mc.validate_bundle(src)
        if not info["valid"]:
            QMessageBox.critical(self, "Bundle invalide", info["error"])
            return

        # Confirmation
        m = info["manifest"]
        n = m.get("_detected_project_count", "?")
        reply = QMessageBox.question(
            self, "Confirmer l'import",
            f"Importer {n} projet(s) depuis ce bundle ?\n\n"
            f"Source      : {m.get('source_platform','?')}\n"
            f"Destination : {base}\n\n"
            "⚠ La configuration locale sera remplacée.\n"
            "Créez un export de cette machine d'abord si nécessaire !",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self._lock(True)
        self._log("─── Démarrage de l'import ───")
        self._import_worker = ImportWorker(src, base, self._get_rules())
        self._import_worker.progress_signal.connect(self._on_progress)
        self._import_worker.finished.connect(self._on_import_done)
        self._import_worker.start()

    def _on_import_done(self, ok: bool, msg: str, log: list, warn: list) -> None:
        self._lock(False)
        self._progress_bar.setVisible(False)
        self._progress_lbl.setText("")
        for line in log:
            self._log(line)
        for w in warn:
            self._log(f"⚠ {w}", color="#fab387")
        if ok:
            self._log(f"✅ {msg}", color="#a6e3a1")
            QMessageBox.information(
                self, "Import réussi",
                f"{msg}\n\n"
                "🔄 Redémarrez Voktora pour charger vos projets importés."
            )
        else:
            self._log(f"❌ {msg}", color="#f38ba8")
            QMessageBox.critical(self, "Erreur d'import", msg)

    # ──────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────

    def _on_progress(self, msg: str, pct: int) -> None:
        self._progress_lbl.setText(msg)
        self._progress_bar.setValue(pct)
        self._progress_bar.setVisible(True)

    def _log(self, text: str, color: str = "") -> None:
        if color:
            self._log_edit.append(
                f'<span style="color:{color}">{text}</span>'
            )
        else:
            self._log_edit.append(text)
        self._log_edit.verticalScrollBar().setValue(
            self._log_edit.verticalScrollBar().maximum()
        )

    def _lock(self, locked: bool) -> None:
        self._btn_export.setEnabled(not locked)
        self._btn_import.setEnabled(not locked)
        self._btn_close.setEnabled(not locked)
        self._tabs.setEnabled(not locked or True)   # onglets toujours visibles
        self._progress_bar.setVisible(locked)



# ════════════════════════════════════════════════════════════════════════════
# MASTER PASSWORD — Setup au premier lancement
# ════════════════════════════════════════════════════════════════════════════

class MasterPasswordSetupDialog(QDialog):
    """Dialog affiché au premier lancement pour créer le master password du vault."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Voktora — Configuration du vault")
        self.setFixedWidth(440)
        self.setModal(True)
        self._password = ""

        v = QVBoxLayout(self)
        v.setSpacing(14)
        v.setContentsMargins(28, 22, 28, 22)

        icon = QLabel("🔐")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 42px;")
        v.addWidget(icon)

        title = QLabel("Bienvenue dans Voktora !")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #cdd6f4;")
        v.addWidget(title)

        desc = QLabel(
            "Creez un <b>mot de passe maitre</b> pour securiser vos tokens GitHub, "
            "cles SSH et autres secrets.<br><br>"
            "Ce mot de passe derive une cle AES-256 unique par type de secret. "
            "Il n'est jamais stocke, seulement un verifier PBKDF2 (480 000 iterations)."
        )
        desc.setWordWrap(True)
        desc.setTextFormat(Qt.RichText)
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("color: #a6adc8; font-size: 12px;")
        v.addWidget(desc)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #313244;")
        v.addWidget(sep)

        form = QFormLayout()
        form.setSpacing(10)

        self._pwd1 = QLineEdit()
        self._pwd1.setEchoMode(QLineEdit.Password)
        self._pwd1.setPlaceholderText("Mot de passe maitre")
        self._pwd1.setMinimumHeight(36)

        self._pwd2 = QLineEdit()
        self._pwd2.setEchoMode(QLineEdit.Password)
        self._pwd2.setPlaceholderText("Confirmer le mot de passe")
        self._pwd2.setMinimumHeight(36)

        self._strength = QLabel("")
        self._strength.setStyleSheet("font-size: 11px;")
        self._pwd1.textChanged.connect(self._on_pwd_change)

        form.addRow("Mot de passe :", self._pwd1)
        form.addRow("Confirmation :", self._pwd2)
        form.addRow("Force :", self._strength)
        v.addLayout(form)

        self._err = QLabel("")
        self._err.setStyleSheet("color: #f38ba8; font-size: 11px;")
        self._err.setAlignment(Qt.AlignCenter)
        v.addWidget(self._err)

        btn = QPushButton("Creer le vault et demarrer")
        btn.setObjectName("primary")
        btn.setFixedHeight(40)
        btn.clicked.connect(self._confirm)
        v.addWidget(btn)

        skip = QPushButton("Passer (vault non chiffre — deconseille)")
        skip.setStyleSheet("color: #6c7086; font-size: 11px;")
        skip.clicked.connect(self._skip)
        v.addWidget(skip)

    def _on_pwd_change(self, text: str) -> None:
        n          = len(text)
        has_upper  = any(c.isupper() for c in text)
        has_digit  = any(c.isdigit() for c in text)
        has_symbol = any(not c.isalnum() for c in text)
        score      = n // 4 + has_upper + has_digit + has_symbol
        colors = ["#f38ba8", "#fab387", "#f9e2af", "#a6e3a1"]
        labels = ["Tres faible", "Faible", "Moyen", "Fort"]
        idx    = min(score, 3) if n >= 4 else 0
        self._strength.setText(labels[idx])
        self._strength.setStyleSheet(f"color:{colors[idx]}; font-size:11px;")

    def _confirm(self) -> None:
        p1 = self._pwd1.text()
        p2 = self._pwd2.text()
        if len(p1) < 8:
            self._err.setText("Le mot de passe doit faire au moins 8 caracteres.")
            return
        if p1 != p2:
            self._err.setText("Les mots de passe ne correspondent pas.")
            return
        self._password = p1
        self.accept()

    def _skip(self) -> None:
        self._password = ""
        self.accept()

    def get_password(self) -> str:
        return self._password


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


# ════════════════════════════════════════════════════════════════════════════
# PROFILES UI
# ════════════════════════════════════════════════════════════════════════════

class ProfilesDialog(QDialog):
    """Gestion des profils d'execution d'un projet."""

    def __init__(self, project_path: Path, parent=None):
        super().__init__(parent)
        self._project_path = project_path
        self.setWindowTitle(f"Profils — {project_path.name}")
        self.setMinimumSize(520, 480)

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(14, 12, 14, 12)

        v.addWidget(QLabel(f"<b>Profils d'execution</b> — {project_path.name}",
                           styleSheet="color:#cdd6f4;"))

        self._list = QListWidget()
        self._list.setMaximumHeight(120)
        self._list.currentRowChanged.connect(self._on_select)
        v.addWidget(self._list)

        form = QFormLayout()
        form.setSpacing(8)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Mon profil")
        self._cmd_edit  = QLineEdit()
        self._cmd_edit.setPlaceholderText("python src/main.py")
        self._dir_edit  = QLineEdit()
        self._dir_edit.setPlaceholderText("(racine du projet)")
        self._env_edit  = QTextEdit()
        self._env_edit.setFixedHeight(70)
        self._env_edit.setPlaceholderText("VARIABLE=valeur\nAUTRE=valeur2")
        self._pre_edit  = QTextEdit()
        self._pre_edit.setFixedHeight(50)
        self._pre_edit.setPlaceholderText("cmd pre-run (une par ligne)")
        self._post_edit = QTextEdit()
        self._post_edit.setFixedHeight(50)
        self._post_edit.setPlaceholderText("cmd post-run (une par ligne)")
        self._default_chk = QCheckBox("Profil par defaut")

        form.addRow("Nom :", self._name_edit)
        form.addRow("Commande :", self._cmd_edit)
        form.addRow("Dossier :", self._dir_edit)
        form.addRow("Env vars :", self._env_edit)
        form.addRow("Pre-run :", self._pre_edit)
        form.addRow("Post-run :", self._post_edit)
        form.addRow("", self._default_chk)
        v.addLayout(form)

        row = QHBoxLayout()
        for label, slot in [
            ("Nouveau", self._new),
            ("Sauvegarder", self._save),
            ("Supprimer", self._delete),
            ("Lancer", self._run),
        ]:
            b = QPushButton(label)
            if label == "Sauvegarder":
                b.setObjectName("primary")
            b.clicked.connect(slot)
            row.addWidget(b)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        row.addStretch()
        row.addWidget(btn_close)
        v.addLayout(row)

        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for p in profiles.load_profiles(self._project_path):
            self._list.addItem(f"{'* ' if p.default else ''}{p.name}  —  {p.run_cmd}")

    def _on_select(self, row: int) -> None:
        all_p = profiles.load_profiles(self._project_path)
        if 0 <= row < len(all_p):
            p = all_p[row]
            self._name_edit.setText(p.name)
            self._cmd_edit.setText(p.run_cmd)
            self._dir_edit.setText(p.work_dir)
            self._env_edit.setPlainText("\n".join(f"{k}={v}" for k, v in p.env.items()))
            self._pre_edit.setPlainText("\n".join(p.pre_run))
            self._post_edit.setPlainText("\n".join(p.post_run))
            self._default_chk.setChecked(p.default)

    def _parse_env(self) -> dict:
        out = {}
        for line in self._env_edit.toPlainText().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
        return out

    def _save(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Erreur", "Le nom est requis.")
            return
        all_p = profiles.load_profiles(self._project_path)
        pr = profiles.RunProfile(
            name      = name,
            run_cmd   = self._cmd_edit.text().strip(),
            work_dir  = self._dir_edit.text().strip(),
            env       = self._parse_env(),
            pre_run   = [l for l in self._pre_edit.toPlainText().splitlines() if l.strip()],
            post_run  = [l for l in self._post_edit.toPlainText().splitlines() if l.strip()],
            default   = self._default_chk.isChecked(),
        )
        idx = next((i for i, p in enumerate(all_p) if p.name == name), -1)
        if idx >= 0:
            all_p[idx] = pr
        else:
            all_p.append(pr)
        if pr.default:
            for i, p in enumerate(all_p):
                if p.name != name:
                    all_p[i].default = False
        profiles.save_profiles(self._project_path, all_p)
        self._refresh()

    def _new(self) -> None:
        for w in (self._name_edit, self._cmd_edit, self._dir_edit,
                  self._env_edit, self._pre_edit, self._post_edit):
            if hasattr(w, "clear"):
                w.clear()
        self._default_chk.setChecked(False)
        self._name_edit.setFocus()

    def _delete(self) -> None:
        row = self._list.currentRow()
        all_p = profiles.load_profiles(self._project_path)
        if 0 <= row < len(all_p):
            profiles.delete_profile(self._project_path, all_p[row].name)
            self._refresh()

    def _run(self) -> None:
        row = self._list.currentRow()
        all_p = profiles.load_profiles(self._project_path)
        if 0 <= row < len(all_p):
            proc = profiles.launch(self._project_path, all_p[row])
            if proc:
                QMessageBox.information(self, "Lance",
                    f"Profil '{all_p[row].name}' lance (PID {proc.pid}).")


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


# ════════════════════════════════════════════════════════════════════════════
# SNAPSHOTS UI
# ════════════════════════════════════════════════════════════════════════════

class SnapshotDialog(QDialog):
    """Creation, liste et restauration de snapshots d'un projet."""

    def __init__(self, project_path: Path, parent=None):
        super().__init__(parent)
        self._path = project_path
        self.setWindowTitle(f"Snapshots — {project_path.name}")
        self.setMinimumSize(520, 360)

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(14, 12, 14, 12)
        v.addWidget(QLabel(f"<b>Snapshots</b> — {project_path.name}",
                           styleSheet="color:#cdd6f4;"))

        self._list = QListWidget()
        v.addWidget(self._list)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        v.addWidget(self._progress)

        row = QHBoxLayout()
        for label, slot in [
            ("Creer", self._create),
            ("Restaurer", self._restore),
            ("Comparer", self._diff),
            ("Supprimer", self._delete),
        ]:
            b = QPushButton(label)
            if label == "Creer":
                b.setObjectName("primary")
            b.clicked.connect(slot)
            row.addWidget(b)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        row.addStretch()
        row.addWidget(btn_close)
        v.addLayout(row)

        self._refresh()

    def _refresh(self) -> None:
        self._list.clear()
        for s in snapshots.list_snaps(self._path):
            item = QListWidgetItem(f"{s.label}  /  {s.timestamp}  /  {s.size_mb} MB")
            item.setData(Qt.UserRole, str(s.path))
            self._list.addItem(item)

    def _selected_snap(self):
        item = self._list.currentItem()
        return Path(item.data(Qt.UserRole)) if item else None

    def _create(self) -> None:
        label, ok = QInputDialog.getText(self, "Label", "Label du snapshot :")
        if not ok:
            return
        self._progress.setVisible(True)
        QApplication.processEvents()
        try:
            out = snapshots.create(self._path, label)
            self._progress.setVisible(False)
            self._refresh()
            QMessageBox.information(self, "Snapshot cree", str(out))
        except Exception as e:
            self._progress.setVisible(False)
            QMessageBox.critical(self, "Erreur", str(e))

    def _restore(self) -> None:
        snap = self._selected_snap()
        if not snap:
            return
        target = QFileDialog.getExistingDirectory(self, "Dossier de restauration")
        if not target:
            return
        dest = Path(target) / self._path.name
        try:
            snapshots.restore(snap, dest, overwrite=False)
            QMessageBox.information(self, "Restaure", str(dest))
        except FileExistsError:
            if QMessageBox.question(self, "Ecraser ?", f"{dest} existe. Ecraser ?") == QMessageBox.Yes:
                snapshots.restore(snap, dest, overwrite=True)

    def _diff(self) -> None:
        snaps_list = snapshots.list_snaps(self._path)
        if len(snaps_list) < 2:
            QMessageBox.information(self, "Diff", "Besoin d'au moins 2 snapshots.")
            return
        names = [s.label for s in snaps_list]
        a_name, ok = QInputDialog.getItem(self, "Snapshot A", "Choisir A :", names, 0, False)
        if not ok:
            return
        b_name, ok = QInputDialog.getItem(self, "Snapshot B", "Choisir B :", names, 1, False)
        if not ok:
            return
        snap_a = next(s for s in snaps_list if s.label == a_name)
        snap_b = next(s for s in snaps_list if s.label == b_name)
        diff   = snapshots.diff_snaps(snap_a.path, snap_b.path)
        text   = "\n".join(f"{v.upper():10}  {k}" for k, v in sorted(diff.items()))
        dlg    = QDialog(self)
        dlg.setWindowTitle("Diff snapshots")
        dlg.setMinimumSize(500, 380)
        lay    = QVBoxLayout(dlg)
        te     = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(text or "Aucune difference.")
        te.setStyleSheet("font-family:Consolas,'DejaVu Sans Mono',monospace; font-size:12px;")
        lay.addWidget(te)
        close  = QPushButton("Fermer")
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)
        dlg.exec()

    def _delete(self) -> None:
        snap = self._selected_snap()
        if not snap:
            return
        if QMessageBox.question(self, "Supprimer", "Supprimer ce snapshot ?") == QMessageBox.Yes:
            snapshots.delete_snap(snap)
            self._refresh()


# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD UI
# ════════════════════════════════════════════════════════════════════════════

class DashboardDialog(QDialog):
    """Tableau de bord sante et usage."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dashboard — Sante & Usage")
        self.setMinimumSize(640, 500)

        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.setContentsMargins(14, 12, 14, 12)

        title = QLabel("Dashboard Voktora")
        title.setStyleSheet("font-size:15px; font-weight:bold; color:#cdd6f4;")
        v.addWidget(title)

        self._summary = QLabel("Cliquez sur Analyser pour generer le rapport.")
        self._summary.setStyleSheet("color:#a6adc8; font-size:12px;")
        self._summary.setWordWrap(True)
        v.addWidget(self._summary)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Projet", "Score", "Problemes"])
        self._tree.setColumnWidth(0, 220)
        self._tree.setColumnWidth(1, 70)
        v.addWidget(self._tree)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setFixedHeight(110)
        self._detail.setStyleSheet("font-size:12px;")
        v.addWidget(self._detail)

        row = QHBoxLayout()
        btn_analyze = QPushButton("Analyser")
        btn_analyze.setObjectName("primary")
        btn_analyze.clicked.connect(self._analyze)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_analyze)
        row.addStretch()
        row.addWidget(btn_close)
        v.addLayout(row)

        self._tree.itemClicked.connect(self._on_item_click)

    def _analyze(self) -> None:
        report = dashboard.generate_report()
        self._tree.clear()
        for h in report.health:
            n_issues = len(h.issues) + len(h.warnings)
            item = QTreeWidgetItem([
                f"{h.status_icon} {h.name}",
                f"{h.score}/100",
                str(n_issues) if n_issues else "OK",
            ])
            item.setData(0, Qt.UserRole, h)
            self._tree.addTopLevelItem(item)

        stats = report.usage_stats
        self._summary.setText(
            f"<b>{report.total_projects}</b> projets — "
            f"<b>{stats['healthy_count']}</b> sains — "
            f"<b>{stats['broken_count']}</b> problematiques — "
            f"rapport du {report.generated_at}"
        )

    def _on_item_click(self, item, _col) -> None:
        h = item.data(0, Qt.UserRole)
        if not h:
            return
        lines = list(h.issues) + list(h.warnings) + list(h.info)
        lines.append(f"Commits : {h.commit_count}  /  Derniere ouverture : {h.last_opened}")
        self._detail.setPlainText("\n".join(lines))


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
