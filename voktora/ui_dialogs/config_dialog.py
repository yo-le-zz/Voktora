"""
Voktora — ui_dialogs.config_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

from pathlib import Path

import ai_providers
import core
from PySide6.QtGui import QAction
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
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from task_worker import TaskWorker


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

        self.projects_root_edit = QLineEdit()
        self.projects_root_edit.setPlaceholderText("Chemin personnalisé (laisser vide = défaut)")
        btn_root_browse = QPushButton("…")
        btn_root_browse.setFixedWidth(32)
        btn_root_browse.clicked.connect(
            lambda: self._browse_dir(self.projects_root_edit)
        )
        row_root = QHBoxLayout()
        row_root.addWidget(self.projects_root_edit)
        row_root.addWidget(btn_root_browse)
        form_storage.addRow("Projets :", row_root)

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

        # ── 2bis. Disque et sauvegardes ───────────────────
        grp_disk = QGroupBox("💽 Espace disque et snapshots")
        form_disk = QFormLayout()
        self.disk_threshold_spin = QSpinBox()
        self.disk_threshold_spin.setRange(0, 1_000_000)
        self.disk_threshold_spin.setSuffix(" Mo")
        self.disk_threshold_spin.setToolTip(
            "« Tout réinitialiser » (Outils → Espace disque) demande une SECONDE confirmation "
            "(taper un mot) quand la quantité à supprimer dépasse ce seuil. 0 = toujours.")
        form_disk.addRow("Double confirmation au-delà de :", self.disk_threshold_spin)
        self.snapshot_keep_spin = QSpinBox()
        self.snapshot_keep_spin.setRange(0, 999)
        self.snapshot_keep_spin.setSpecialValueText("illimité")
        self.snapshot_keep_spin.setToolTip("Nombre de snapshots conservés par projet ; les plus anciens sont "
                                           "supprimés à la création d'un nouveau. 0 = illimité.")
        form_disk.addRow("Snapshots conservés par projet :", self.snapshot_keep_spin)
        grp_disk.setLayout(form_disk)
        layout.addWidget(grp_disk)

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

        btn_manage_apps = QPushButton("Gérer les actions rapides (ajouter, modifier, icônes)…")
        btn_manage_apps.clicked.connect(self._manage_quick_apps)
        apps_layout.addWidget(btn_manage_apps)

        grp_apps.setLayout(apps_layout)
        layout.addWidget(grp_apps)

        # ── 4bis. Fournisseurs d'IA (Ollama, OmniRoute, compatible OpenAI) ───────────
        grp_ai = QGroupBox("Fournisseurs d'IA")
        form_ai = QFormLayout()

        top_row = QHBoxLayout()
        self.ai_provider_combo = QComboBox()
        self.ai_provider_combo.currentIndexChanged.connect(self._on_ai_provider_changed)
        top_row.addWidget(self.ai_provider_combo, stretch=1)
        self.btn_ai_add = QPushButton("Ajouter")
        add_menu = QMenu(self.btn_ai_add)
        for kind in ai_providers.KINDS:
            action = QAction(ai_providers.KIND_LABELS[kind], add_menu)
            action.triggered.connect(lambda _checked=False, k=kind: self._add_ai_provider(k))
            add_menu.addAction(action)
        self.btn_ai_add.setMenu(add_menu)
        top_row.addWidget(self.btn_ai_add)
        self.btn_ai_remove = QPushButton("Supprimer")
        self.btn_ai_remove.clicked.connect(self._remove_ai_provider)
        top_row.addWidget(self.btn_ai_remove)
        form_ai.addRow("Fournisseur:", top_row)

        self.ai_active_chk = QCheckBox("Utiliser ce fournisseur pour la génération (description, icône)")
        self.ai_active_chk.toggled.connect(self._on_ai_active_toggled)
        form_ai.addRow(self.ai_active_chk)

        self.ai_name_edit = QLineEdit()
        form_ai.addRow("Nom:", self.ai_name_edit)

        self.ai_host_edit = QLineEdit()
        form_ai.addRow("Adresse:", self.ai_host_edit)

        self.ai_key_edit = QLineEdit()
        self.ai_key_edit.setEchoMode(QLineEdit.Password)
        self.ai_key_edit.setPlaceholderText("Facultative (OmniRoute : si REQUIRE_API_KEY est activé)")
        form_ai.addRow("Clé d'API:", self.ai_key_edit)

        self.ai_model_combo = QComboBox()
        self.ai_model_combo.setEditable(True)
        model_row = QHBoxLayout()
        model_row.addWidget(self.ai_model_combo, stretch=1)
        self.btn_ai_detect = QPushButton("Détecter")
        self.btn_ai_detect.setToolTip("Lister les modèles proposés par le serveur configuré ci-dessus.")
        self.btn_ai_detect.clicked.connect(self._detect_ai_models)
        model_row.addWidget(self.btn_ai_detect)
        form_ai.addRow("Modèle:", model_row)

        self.ai_status_lbl = QLabel(
            "Ollama : serveur local (http://localhost:11434). OmniRoute : passerelle compatible OpenAI "
            "(http://localhost:20128/v1) qui route vers plusieurs fournisseurs. Aucune donnée ne part "
            "ailleurs que vers l'adresse configurée ; la clé d'API est stockée dans config.json "
            "(lisible par vous seul) et n'est jamais incluse dans les exports."
        )
        self.ai_status_lbl.setWordWrap(True)
        self.ai_status_lbl.setStyleSheet("font-size: 11px; color:#a6adc8;")
        form_ai.addRow(self.ai_status_lbl)
        self.ai_bar = QProgressBar()
        self.ai_bar.setRange(0, 0)
        self.ai_bar.setTextVisible(False)
        self.ai_bar.setFixedHeight(6)
        self.ai_bar.hide()
        form_ai.addRow(self.ai_bar)

        grp_ai.setLayout(form_ai)
        layout.addWidget(grp_ai)
        self._ai: dict = core.get_ai_config()
        self._ai_index = -1
        self._ai_worker: TaskWorker | None = None

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
        self.projects_root_edit.setText(storage.get("projects_root") or "")

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
        self.disk_threshold_spin.setValue(int(app_cfg.get("disk_reset_confirm_mb", 500)))
        self.snapshot_keep_spin.setValue(int(app_cfg.get("snapshot_keep", 0)))

        # Barre rapide
        self._refresh_apps_list()

        # Fournisseurs d'IA
        self._ai = core.get_ai_config()
        self._refresh_ai_combo(select=self._ai["active"])

        # GitHub OAuth Client ID
        self.client_id_edit.setText(core.get_github_client_id())

    # ── Fournisseurs d'IA ──────────────────────────

    def _provider_label(self, provider: dict) -> str:
        marker = "  (actif)" if provider["id"] == self._ai["active"] else ""
        return f"{provider['name']} — {ai_providers.KIND_LABELS[provider['kind']].split(' (')[0]}{marker}"

    def _refresh_ai_combo(self, select: str | None = None) -> None:
        self.ai_provider_combo.blockSignals(True)
        self.ai_provider_combo.clear()
        for provider in self._ai["providers"]:
            self.ai_provider_combo.addItem(self._provider_label(provider), provider["id"])
        index = max(self.ai_provider_combo.findData(select), 0) if select else 0
        self.ai_provider_combo.setCurrentIndex(index)
        self.ai_provider_combo.blockSignals(False)
        self._ai_index = -1
        self._on_ai_provider_changed(index)

    def _store_ai_fields(self) -> None:
        """Recopie les champs affichés dans le fournisseur actuellement sélectionné."""
        if not 0 <= self._ai_index < len(self._ai["providers"]):
            return
        provider = self._ai["providers"][self._ai_index]
        provider["name"] = self.ai_name_edit.text().strip() or provider["name"]
        provider["host"] = self.ai_host_edit.text().strip()
        provider["api_key"] = self.ai_key_edit.text().strip()
        provider["model"] = self.ai_model_combo.currentText().strip()

    def _on_ai_provider_changed(self, index: int) -> None:
        self._store_ai_fields()
        self._ai_index = index
        if not 0 <= index < len(self._ai["providers"]):
            return
        provider = self._ai["providers"][index]
        self.ai_name_edit.setText(provider["name"])
        self.ai_host_edit.setText(provider["host"])
        self.ai_host_edit.setPlaceholderText(ai_providers.DEFAULT_HOSTS[provider["kind"]])
        self.ai_key_edit.setText(provider["api_key"])
        self.ai_model_combo.clear()
        self.ai_model_combo.setCurrentText(provider["model"])
        self.ai_active_chk.blockSignals(True)
        self.ai_active_chk.setChecked(provider["id"] == self._ai["active"])
        self.ai_active_chk.blockSignals(False)
        only_ollama = len(self._ai["providers"]) == 1
        self.btn_ai_remove.setEnabled(not (provider["kind"] == "ollama" and only_ollama))

    def _on_ai_active_toggled(self, checked: bool) -> None:
        if not 0 <= self._ai_index < len(self._ai["providers"]):
            return
        provider = self._ai["providers"][self._ai_index]
        if checked:
            self._ai["active"] = provider["id"]
        elif self._ai["active"] == provider["id"]:
            self.ai_active_chk.blockSignals(True)
            self.ai_active_chk.setChecked(True)      # il faut toujours un fournisseur actif
            self.ai_active_chk.blockSignals(False)
        self._store_ai_fields()
        self._refresh_ai_combo(select=provider["id"])

    def _add_ai_provider(self, kind: str) -> None:
        self._store_ai_fields()
        base = kind
        ids = {p["id"] for p in self._ai["providers"]}
        new_id, n = base, 2
        while new_id in ids:
            new_id, n = f"{base}-{n}", n + 1
        self._ai["providers"].append({
            "id": new_id, "kind": kind, "name": ai_providers.KIND_LABELS[kind].split(" (")[0],
            "host": ai_providers.DEFAULT_HOSTS[kind], "model": "", "api_key": "",
        })
        self._refresh_ai_combo(select=new_id)

    def _remove_ai_provider(self) -> None:
        index = self._ai_index
        if not 0 <= index < len(self._ai["providers"]):
            return
        removed = self._ai["providers"].pop(index)
        if self._ai["active"] == removed["id"] and self._ai["providers"]:
            self._ai["active"] = self._ai["providers"][0]["id"]
        self._ai_index = -1
        self._refresh_ai_combo(select=self._ai["active"])

    def _detect_ai_models(self) -> None:
        if self._ai_worker is not None and self._ai_worker.isRunning():
            return
        self._store_ai_fields()
        provider = dict(self._ai["providers"][self._ai_index])
        self.btn_ai_detect.setEnabled(False)
        self.ai_bar.show()
        self.ai_status_lbl.setText("Recherche des modèles…")
        self._ai_worker = TaskWorker(lambda _ctx: ai_providers.list_models(provider))
        self._ai_worker.succeeded.connect(self._on_ai_models)
        self._ai_worker.failed.connect(self._on_ai_models_failed)
        self._ai_worker.cancelled.connect(lambda: (self.btn_ai_detect.setEnabled(True), self.ai_bar.hide()))
        self._ai_worker.start()

    def _on_ai_models(self, models) -> None:
        self.btn_ai_detect.setEnabled(True)
        self.ai_bar.hide()
        if not models:
            self.ai_status_lbl.setText("Aucun modèle proposé par ce serveur (Ollama : « ollama pull llama3.1 »).")
            return
        current = self.ai_model_combo.currentText()
        self.ai_model_combo.clear()
        self.ai_model_combo.addItems(models)
        self.ai_model_combo.setCurrentText(current if current in models else models[0])
        self.ai_status_lbl.setText(f"{len(models)} modèle(s) disponible(s).")

    def _on_ai_models_failed(self, message: str) -> None:
        self.btn_ai_detect.setEnabled(True)
        self.ai_bar.hide()
        self.ai_status_lbl.setText(message)
        QMessageBox.warning(self, "Fournisseur d'IA", message)

    def _refresh_apps_list(self) -> None:
        self.apps_list.clear()
        import icons as _icons
        import quick_actions as qa
        for action in qa.load():
            item = QListWidgetItem(_icons.icon(action.icon), f"{action.name}  —  {action.cmd}")
            self.apps_list.addItem(item)

    def _manage_quick_apps(self) -> None:
        from ui_dialogs.quick_actions_dialog import QuickActionsDialog
        QuickActionsDialog(self).exec()
        self._refresh_apps_list()

    def _browse_dir(self, line_edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choisir un dossier", str(Path.home())
        )
        if path:
            line_edit.setText(path)

    def _create_install_dirs(self) -> None:
        """Crée immédiatement le dossier racine des projets configuré."""
        root = self.projects_root_edit.text().strip()

        created = []
        errors  = []

        p = Path(root) if root else core.get_projects_root()
        try:
            p.mkdir(parents=True, exist_ok=True)
            created.append(f"✅ Projets : {p}")
        except Exception as e:
            errors.append(f"❌ Projets : {e}")

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
        core.set_storage_config(self.projects_root_edit.text().strip() or None)

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
        app_cfg["disk_reset_confirm_mb"]     = self.disk_threshold_spin.value()
        app_cfg["snapshot_keep"]             = self.snapshot_keep_spin.value()
        core.set_app_config(app_cfg)

        # Fournisseurs d'IA
        self._store_ai_fields()
        core.set_ai_config(self._ai)

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
            "⚠ Vos projets et catégories seront préservés.",
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


