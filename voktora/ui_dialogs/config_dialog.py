"""
Voktora — ui_dialogs.config_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

from pathlib import Path

import core
import ollama_client
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


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

        # ── 4bis. Ollama (génération IA locale) ───────────
        grp_ollama = QGroupBox("🤖 Ollama (génération IA locale)")
        form_ollama = QFormLayout()

        self.ollama_host_edit = QLineEdit()
        self.ollama_host_edit.setPlaceholderText("http://localhost:11434")
        form_ollama.addRow("Hôte:", self.ollama_host_edit)

        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setEditable(True)
        model_row = QHBoxLayout()
        model_row.addWidget(self.ollama_model_combo, stretch=1)
        btn_detect_models = QPushButton("🔄 Détecter")
        btn_detect_models.setToolTip("Lister les modèles installés sur le serveur Ollama configuré ci-dessus.")
        btn_detect_models.clicked.connect(self._detect_ollama_models)
        model_row.addWidget(btn_detect_models)
        form_ollama.addRow("Modèle:", model_row)

        self.ollama_status_lbl = QLabel(
            "Utilisé pour générer des descriptions de projet et suggérer des "
            "emojis. Nécessite un serveur Ollama lancé localement (aucune "
            "donnée n'est envoyée en dehors de votre machine)."
        )
        self.ollama_status_lbl.setWordWrap(True)
        self.ollama_status_lbl.setStyleSheet("font-size: 11px; color:#a6adc8;")
        form_ollama.addRow(self.ollama_status_lbl)

        grp_ollama.setLayout(form_ollama)
        layout.addWidget(grp_ollama)

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
        btn_json_editor = QPushButton("🛠 Éditer le JSON (avancé)")
        btn_json_editor.setObjectName("subtle")
        btn_json_editor.setToolTip(
            "Édition manuelle directe de config.json — réservée au dépannage."
        )
        btn_json_editor.clicked.connect(self._open_json_editor)
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("💾 Enregistrer")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._save)
        btn_bar.addWidget(btn_reset)
        btn_bar.addWidget(btn_json_editor)
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

        # Ollama
        ollama_cfg = core.get_ollama_config()
        self.ollama_host_edit.setText(ollama_cfg["host"])
        if ollama_cfg["model"]:
            self.ollama_model_combo.setCurrentText(ollama_cfg["model"])

        # GitHub OAuth Client ID
        self.client_id_edit.setText(core.get_github_client_id())

    def _detect_ollama_models(self) -> None:
        host = self.ollama_host_edit.text().strip() or ollama_client.DEFAULT_HOST
        try:
            models = ollama_client.list_models(host)
        except ollama_client.OllamaError as e:
            QMessageBox.warning(self, "Ollama", str(e))
            return
        if not models:
            QMessageBox.information(
                self, "Ollama",
                "Aucun modèle installé sur ce serveur Ollama.\n"
                "Installez-en un avec par ex. « ollama pull llama3.1 »."
            )
            return
        current = self.ollama_model_combo.currentText()
        self.ollama_model_combo.clear()
        self.ollama_model_combo.addItems(models)
        if current in models:
            self.ollama_model_combo.setCurrentText(current)

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

        # Ollama
        core.set_ollama_config(
            self.ollama_host_edit.text().strip() or ollama_client.DEFAULT_HOST,
            self.ollama_model_combo.currentText().strip(),
        )

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

    def _open_json_editor(self) -> None:
        from ui_dialogs.json_config_editor_dialog import JsonConfigEditorDialog
        dlg = JsonConfigEditorDialog(self)
        if dlg.exec():
            self._load_current_values()


