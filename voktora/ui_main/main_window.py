"""
Voktora — ui_main.main_window
Fragment de ui_main.py extrait lors du découpage v1.0.2 en package.
Contient la fenêtre principale MainWindow (fichier volumineux : c'est une
seule classe QMainWindow cohérente, pas séparée davantage pour éviter de
fragmenter ses très nombreuses références internes à self.*).
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

import core
import theme_manager
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from ui_dialogs import (
    CategoriesDialog,
    ConfigDialog,
    CustomizeProjectDialog,
    EncryptProjectDialog,
    StatusDialog,
    ThemeSettingsDialog,
)
from ui_project_panel import ProjectPanel
from ui_project_view import ProjectBrowser

from . import (
    create_dialog,
    diagnostic_dialog,
    git_dialog,
    github_login_dialog,
    push_dialog,
    storage_dialog,
    token_password_dialog,
    uninstall_dialog,
    workers,
)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Voktora — Project Instance Manager")
        self.setMinimumSize(1180, 720)
        
        # Appliquer le thème
        theme_manager.apply_theme_to_app(QApplication.instance())
        
        self._sel_path:   Path | None      = None
        self._sel_kind:   str              = ""
        self._worker:     workers.Worker | None    = None
        self._git_worker: workers.GitWorker | None = None
        self._delete_worker: workers.DeleteWorker | None = None
        self._last_saved_note: str = ""
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.timeout.connect(self._auto_save_note)
        
        # Cache de performances pour les instances et intents
        self._instances_cache: list[dict] | None = None
        self._intents_cache: list[dict] | None = None
        self._cache_timestamp: float | None = None
        self._cache_ttl: float = 30.0  # Cache valide pendant 30 secondes

        self._build_ui()
        self._build_menubar()
        self._build_statusbar()
        self._setup_shortcuts()
        self._refresh_all()

        # Tente de restaurer la session GitHub OAuth au démarrage
        self._restore_github_session()

        # Contrôle de santé au démarrage (v1.0.1)
        self._run_startup_health_check()
        
        # Afficher les résumés de migration (v1.0.1)
        self._show_migration_summary()
        self._reload_note_autosave_timer()

        # Vérification des mises à jour au démarrage (v1.0.1)
        self._update_worker: workers.UpdateCheckWorker | None = None
        QTimer.singleShot(3000, self._run_update_check)

    # ──────────────────────────────────────────────
    #  SESSION GITHUB — Restauration au démarrage
    # ──────────────────────────────────────────────

    def _restore_github_session(self) -> None:
        """
        Restaure la session GitHub au démarrage.
        GitHub App d'abord (token auto-renouvelé), puis OAuth (rétrocompat).
        """
        # ── GitHub App ──────────────────────────────────────
        if core.is_using_github_app() and core.is_github_app_configured():
            try:
                ok = core.load_github_app_session()
                if ok:
                    self._update_github_account_card()
                    return
            except Exception:
                pass  # fallback OAuth

        # ── OAuth App (rétrocompat) ──────────────────────────
        info = core.get_github_account_info()
        if not info["connected"]:
            return

        if info["token_protected"]:
            dlg = token_password_dialog.TokenPasswordDialog(mode="get", parent=self)
            dlg.setWindowTitle("🔐  Déverrouiller le compte GitHub — Voktora")
            if dlg.exec() == QDialog.Accepted:
                ok = core.load_github_account_session(dlg.get_password())
                if not ok:
                    QMessageBox.warning(self, "Voktora",
                        "Mot de passe incorrect — le compte GitHub ne sera pas chargé.")
                    return
        else:
            core.load_github_account_session()

        self._update_github_account_card()

    # ──────────────────────────────────────────────
    #  MISES À JOUR — Vérification au démarrage
    # ──────────────────────────────────────────────

    def _build_update_banner(self) -> QFrame:
        """Construit la bannière de notification de mise à jour (cachée par défaut)."""
        banner = QFrame()
        banner.setObjectName("updateBanner")
        banner.setStyleSheet("""
            QFrame#updateBanner {
                background-color: #1e3a5f;
                border-bottom: 1px solid #89b4fa;
            }
        """)
        h = QHBoxLayout(banner)
        h.setContentsMargins(14, 6, 10, 6)
        h.setSpacing(10)

        self._update_lbl = QLabel()
        self._update_lbl.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        h.addWidget(self._update_lbl)
        h.addStretch()

        self._btn_update_dl = QPushButton("⬇  Télécharger")
        self._btn_update_dl.setStyleSheet(
            "background:#89b4fa; color:#1e1e2e; font-weight:700;"
            " border-radius:5px; padding:4px 14px; font-size:12px;"
        )
        h.addWidget(self._btn_update_dl)

        btn_ignore = QToolButton()
        btn_ignore.setText("✕")
        btn_ignore.setToolTip("Ignorer cette mise à jour")
        btn_ignore.setStyleSheet(
            "color:#6c7086; background:transparent; border:none;"
            " font-size:14px; padding:2px 6px;"
        )
        btn_ignore.clicked.connect(banner.hide)
        h.addWidget(btn_ignore)

        return banner

    def _run_update_check(self) -> None:
        """Lance la vérification des mises à jour en arrière-plan."""
        self._update_worker = workers.UpdateCheckWorker()
        self._update_worker.result.connect(self._on_update_result)
        self._update_worker.start()

    def _on_update_result(self, available: bool, latest: str, url: str) -> None:
        self._update_worker = None
        if available:
            self._update_lbl.setText(
                f"🚀  Mise à jour disponible : <b>v{latest}</b>"
                f"  (version actuelle : v{core.APP_VERSION})"
            )
            self._btn_update_dl.clicked.connect(
                lambda: core.open_url_in_browser(url)
            )
            self._update_banner.show()

    # ──────────────────────────────────────────────
    #  CONTRÔLE DE SANTÉ AU DÉMARRAGE (v1.0.1)
    # ──────────────────────────────────────────────

    def _run_startup_health_check(self) -> None:
        try:
            result = core.run_health_check()
        except Exception as exc:
            self._log(f"⚠  Impossible de lancer le diagnostic : {html.escape(str(exc))}")
            return

        if not result.is_healthy:
            dlg = diagnostic_dialog.DiagnosticDialog(result, parent=self)
            dlg.exec()
            self._refresh_all()

    def _show_migration_summary(self) -> None:
        """
        Affiche un résumé des migrations de configuration effectuées au démarrage.
        """
        migrations = core.show_migration_summary()
        if not migrations:
            return
        
        # Créer le message de migration
        title = f"📋 Migration de configuration v{core.APP_VERSION}"
        message = "<b>Les anciens fichiers de configuration ont été migrés automatiquement :</b><br><br>"
        message += "<ul>"
        for migration in migrations:
            if migration.startswith('✅'):
                message += f'<li style="color: #a6e3a1;">{html.escape(migration)}</li>'
            else:
                message += f'<li style="color: #f38ba8;">{html.escape(migration)}</li>'
        message += "</ul><br>"
        message += "Les anciens fichiers ont été sauvegardés avec l'extension <code>.legacy</code>.<br>"
        message += "Consultez le fichier <code>data/migration.log</code> pour plus de détails."
        
        QMessageBox.information(self, title, message)
        
        # Effacer le log après l'avoir affiché
        core.clear_migration_log()

    # ──────────────────────────────────────────────
    #  STATUSBAR
    # ──────────────────────────────────────────────

    def _build_statusbar(self) -> None:
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)
        self._status_lbl = QLabel("Prêt")
        self._status_lbl.setObjectName("statusLbl")
        sb.addWidget(self._status_lbl)
        # Indicateur version à droite
        ver = core.APP_VERSION
        ver_lbl = QLabel(f"Voktora v{ver}")
        ver_lbl.setStyleSheet("color: #45475a; font-size: 11px; padding-right: 4px;")
        sb.addPermanentWidget(ver_lbl)

    def _set_status(self, msg: str, timeout_ms: int = 0) -> None:
        """Met à jour le message de la statusbar."""
        self._status_lbl.setText(msg)
        if timeout_ms > 0:
            QTimer.singleShot(timeout_ms, lambda: self._status_lbl.setText("Prêt"))

    # ──────────────────────────────────────────────
    #  RACCOURCIS CLAVIER
    # ──────────────────────────────────────────────

    def _setup_shortcuts(self) -> None:
        # F5 — Actualiser
        QShortcut(QKeySequence("F5"), self).activated.connect(self._refresh_all)
        # Ctrl+N — Nouvelle instance
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(
            lambda: self.act_create("instance")
        )
        # Ctrl+F — Focus recherche instances
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            self._show_project_switcher
        )
        # Escape — Effacer la recherche
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._clear_search)

    def _clear_search(self) -> None:
        self._browser.get_search_widget().clear()

    # ──────────────────────────────────────────────
    #  FILTRES RECHERCHE
    # ──────────────────────────────────────────────

    def _filter_instance_list(self, text: str) -> None:
        text = text.strip().lower()
        for i in range(self.instance_list.count()):
            item = self.instance_list.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _filter_intent_list(self, text: str) -> None:
        text = text.strip().lower()
        for i in range(self.intent_list.count()):
            item = self.intent_list.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    # ──────────────────────────────────────────────
    #  MENUBAR
    # ──────────────────────────────────────────────

    def _build_menubar(self):
        from PySide6.QtGui import QAction
        menubar = self.menuBar()
        menubar.setStyleSheet(
            "QMenuBar { background-color: #181825; color: #cdd6f4; padding: 2px 6px; }"
            "QMenuBar::item:selected { background-color: #313244; border-radius: 4px; }"
            "QMenu { background-color: #181825; color: #cdd6f4; border: 1px solid #313244; }"
            "QMenu::item { padding: 7px 22px; }"
            "QMenu::item:selected { background-color: #313244; }"
            "QMenu::separator { height: 1px; background: #313244; margin: 4px 0; }"
        )

        # Menu Fichier
        menu_file = menubar.addMenu("📁 Fichier")
        act_new_inst = QAction("📦 Nouvelle instance", self)
        act_new_inst.triggered.connect(lambda: self.act_create("instance"))
        act_new_int  = QAction("🧩 Nouvel intent", self)
        act_new_int.triggered.connect(lambda: self.act_create("intent"))
        act_import   = QAction("📂 Importer depuis ZIP...", self)
        act_import.triggered.connect(self.act_import_zip)
        act_import_cfg = QAction("🔄 Importer config Meridian / Voktora...", self)
        act_import_cfg.setToolTip("Fusionne un config.json d'une ancienne version Meridian ou Voktora")
        act_import_cfg.triggered.connect(self.act_import_meridian_config)
        act_export   = QAction("📤 Exporter tout en ZIP...", self)
        act_export.triggered.connect(self.act_export_all)
        act_refresh  = QAction("↻ Actualiser", self)
        act_refresh.triggered.connect(self._refresh_all)
        act_quit     = QAction("✕ Quitter", self)
        act_quit.triggered.connect(self.close)
        
        menu_file.addAction(act_new_inst)
        menu_file.addAction(act_new_int)
        menu_file.addSeparator()
        menu_file.addAction(act_import)
        menu_file.addAction(act_import_cfg)
        menu_file.addAction(act_export)
        menu_file.addSeparator()
        menu_file.addAction(act_refresh)
        menu_file.addSeparator()
        menu_file.addAction(act_quit)

        # Menu Git
        menu_git = menubar.addMenu("🐙 Git")
        act_clone    = QAction("📥 Git clone...", self)
        act_clone.triggered.connect(self.act_git_clone)
        act_configure = QAction("🔗 Configurer le repo...", self)
        act_configure.triggered.connect(self.act_git_configure)
        act_init     = QAction("⚙ git init", self)
        act_init.triggered.connect(self.act_git_init)
        act_push     = QAction("🚀 Push initial...", self)
        act_push.triggered.connect(self.act_git_push)
        act_pull     = QAction("⬇ Pull", self)
        act_pull.triggered.connect(self.act_git_pull)
        act_status   = QAction("📋 Status", self)
        act_status.triggered.connect(self.act_git_status)
        act_log      = QAction("📜 Log", self)
        act_log.triggered.connect(self.act_git_log)
        act_checkout = QAction("🌿 Checkout...", self)
        act_checkout.triggered.connect(self.act_git_checkout)
        act_commit_push = QAction("✔ Commit & Push...", self)
        act_commit_push.triggered.connect(self.act_git_commit_push)
        
        menu_git.addAction(act_clone)
        menu_git.addSeparator()
        menu_git.addAction(act_configure)
        menu_git.addAction(act_init)
        menu_git.addAction(act_push)
        menu_git.addSeparator()
        menu_git.addAction(act_pull)
        menu_git.addAction(act_status)
        menu_git.addAction(act_log)
        menu_git.addAction(act_checkout)
        menu_git.addSeparator()
        menu_git.addAction(act_commit_push)

        # Menu Édition
        menu_edit = menubar.addMenu("✏️ Édition")
        act_customize = QAction("🎨 Personnaliser la sélection...", self)
        act_customize.triggered.connect(self.act_customize_selection)
        act_encrypt = QAction("🔐 Chiffrer/Déchiffrer...", self)
        act_encrypt.triggered.connect(self.act_encrypt_project)
        act_category = QAction("📂 Gérer les catégories...", self)
        act_category.triggered.connect(self.act_manage_categories)
        act_status = QAction("📊 Gérer les statuts...", self)
        act_status.triggered.connect(self.act_manage_statuses)
        
        menu_edit.addAction(act_customize)
        menu_edit.addSeparator()
        menu_edit.addAction(act_encrypt)
        menu_edit.addAction(act_category)
        menu_edit.addAction(act_status)

        # Menu Outils
        menu_tools = menubar.addMenu("🛠️ Outils")
        act_builder = QAction("🔨 Projects Builder", self)
        act_builder.triggered.connect(self.act_project_builder)
        act_terminal = QAction("💻 Ouvrir un terminal", self)
        act_terminal.triggered.connect(self.act_open_terminal)
        act_explorer = QAction("📁 Ouvrir l'explorateur", self)
        act_explorer.triggered.connect(self.act_open_explorer)
        
        menu_tools.addAction(act_builder)
        menu_tools.addSeparator()
        menu_tools.addAction(act_terminal)
        menu_tools.addAction(act_explorer)

        # Menu Paramètres
        menu_prefs = menubar.addMenu("⚙️ Paramètres")
        act_storage = QAction("📁 Emplacement de stockage...", self)
        act_storage.triggered.connect(self.act_open_storage_settings)
        act_config = QAction("⚙️ Configuration...", self)
        act_config.triggered.connect(self.act_open_config)
        act_theme = QAction("🎨 Thème...", self)
        act_theme.triggered.connect(self.act_theme_settings)
        act_diag    = QAction("🔍 Diagnostic...", self)
        act_diag.triggered.connect(self.act_run_diagnostic)
        
        menu_prefs.addAction(act_storage)
        menu_prefs.addAction(act_config)
        menu_prefs.addSeparator()
        menu_prefs.addAction(act_theme)
        menu_prefs.addSeparator()
        menu_prefs.addAction(act_diag)

        # Menu GitHub
        menu_gh = menubar.addMenu("🐙 GitHub")
        act_gh_login  = QAction("🔑 Se connecter...", self)
        act_gh_login.triggered.connect(self.act_github_login)
        act_gh_logout = QAction("🚪 Se déconnecter", self)
        act_gh_logout.triggered.connect(self.act_github_logout)
        act_gh_token = QAction("🔑 Gérer les tokens...", self)
        act_gh_token.triggered.connect(self.act_manage_tokens)
        
        menu_gh.addAction(act_gh_login)
        menu_gh.addAction(act_gh_logout)
        menu_gh.addSeparator()
        menu_gh.addAction(act_gh_token)

        # Menu Aide
        menu_help = menubar.addMenu("❓ Aide")
        act_docs = QAction("📚 Documentation", self)
        act_docs.triggered.connect(self.act_open_docs)
        act_about = QAction("ℹ️ À propos", self)
        act_about.triggered.connect(self.act_about)
        
        menu_help.addAction(act_docs)
        menu_help.addSeparator()
        menu_help.addAction(act_about)
        act_info = QAction(f"ℹ️  Voktora v{core.APP_VERSION}", self)
        act_info.setEnabled(False)
        menu_help.addAction(act_info)

        menu_uninst = menubar.addMenu("⚠  Désinstaller")
        act_uninst = QAction("🗑  Désinstaller Voktora...", self)
        act_uninst.triggered.connect(self.act_uninstall)
        menu_uninst.addAction(act_uninst)

    # ──────────────────────────────────────────────
    #  CONSTRUCTION UI
    # ──────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        # Layout vertical : bannière (haut, cachée) + contenu principal (bas)
        root_v = QVBoxLayout(root)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)

        # ── Bannière mise à jour (cachée au démarrage) ────────────────────
        self._update_banner = self._build_update_banner()
        self._update_banner.hide()
        root_v.addWidget(self._update_banner)

        # ── Contenu principal ─────────────────────────────────────────────
        _content_w = QWidget()
        h = QHBoxLayout(_content_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        root_v.addWidget(_content_w, stretch=1)

        # ── Splitter horizontal : sidebar gauche + contenu droit ──
        self._main_splitter = QSplitter(Qt.Horizontal)
        self._main_splitter.setHandleWidth(4)
        self._main_splitter.setChildrenCollapsible(False)

        left = QWidget()
        left.setObjectName("sidebar")
        left.setMinimumWidth(160)
        left.setMaximumWidth(480)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        lv.addWidget(self._build_sidebar_header())
        self._main_splitter.addWidget(left)

        # ── Colonne droite : stack  ──────────────────────────────
        # idx 0 = ProjectBrowser (liste / grille)
        # idx 1 = ProjectPanel   (détail projet)
        self._right_stack = QStackedWidget()

        self._browser = ProjectBrowser()
        self._browser.project_selected.connect(self._on_project_selected)
        self._browser.create_requested.connect(self.act_create)
        self._right_stack.addWidget(self._browser)     # idx 0

        self._project_panel = ProjectPanel()
        self._project_panel.back_requested.connect(self._show_welcome)
        self._project_panel.switch_requested.connect(self._show_project_switcher)
        self._project_panel.project_modified.connect(self._refresh_all)
        self._right_stack.addWidget(self._project_panel)   # idx 1

        self._main_splitter.addWidget(self._right_stack)
        self._main_splitter.setSizes([220, 9999])
        self._main_splitter.setStretchFactor(0, 0)
        self._main_splitter.setStretchFactor(1, 1)

        h.addWidget(self._main_splitter, stretch=1)

        # Legacy widgets (pour les act_* qui les référencent encore)
        self._legacy_content = self._build_content()

    # ── SIDEBAR ──────────────────────────────────

    def _build_sidebar_header(self) -> QWidget:
        """
        Sidebar avec QSplitter vertical interne :
          zone haute = titre + GitHub + disque
          zone basse = stats (redimensionnable en hauteur)
        """
        sb = QWidget()
        sb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        root_v = QVBoxLayout(sb)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)

        self._sidebar_splitter = QSplitter(Qt.Vertical)
        self._sidebar_splitter.setHandleWidth(5)
        self._sidebar_splitter.setChildrenCollapsible(False)
        self._sidebar_splitter.setStyleSheet(
            "QSplitter::handle:vertical {"
            "  background:#313244; border-top:1px solid #45475a; height:5px;"
            "}"
            "QSplitter::handle:vertical:hover { background:#89b4fa; }"
        )

        # ── Zone haute ────────────────────────────────────────────────────────
        top = QWidget()
        top.setObjectName("sidebar")
        v = QVBoxLayout(top)
        v.setContentsMargins(12, 14, 12, 10)
        v.setSpacing(4)

        lbl_t = QLabel("✦  Voktora")
        lbl_t.setObjectName("appTitle")
        v.addWidget(lbl_t)

        lbl_s = QLabel("Project Instance Manager")
        lbl_s.setObjectName("appSub")
        v.addWidget(lbl_s)

        v.addSpacing(2)
        v.addWidget(workers._make_sep())
        v.addSpacing(2)

        self._github_card = self._build_github_account_card()
        v.addWidget(self._github_card)

        v.addSpacing(2)
        v.addWidget(workers._make_sep())
        v.addSpacing(2)

        lbl_d = QLabel("DISQUE")
        lbl_d.setObjectName("sectionLbl")
        v.addWidget(lbl_d)

        self.drive_combo = QComboBox()
        self.drive_combo.currentTextChanged.connect(self._on_drive_changed)
        v.addWidget(self.drive_combo)

        btn_ref = QPushButton("↻  Actualiser")
        btn_ref.setToolTip("Actualiser (F5)")
        btn_ref.setObjectName("subtle")
        btn_ref.clicked.connect(self._refresh_all)
        v.addWidget(btn_ref)
        v.addStretch()

        # ── Zone basse (stats redimensionnable) ───────────────────────────────
        stats_frame = QFrame()
        stats_frame.setObjectName("sidebarStats")
        stats_frame.setMinimumHeight(40)
        stats_frame.setStyleSheet(
            "QFrame#sidebarStats { background:#11111b; border-radius:0px; }"
            "QLabel { color:#6c7086; font-size:11px; background:transparent; }"
            "QLabel[class='statVal'] { color:#a6adc8; font-weight:600; font-size:11px; }"
        )
        sv = QVBoxLayout(stats_frame)
        sv.setContentsMargins(12, 8, 12, 10)
        sv.setSpacing(3)

        hdr = QLabel("STATISTIQUES")
        hdr.setStyleSheet(
            "color:#45475a; font-size:9px; font-weight:700;"
            " letter-spacing:1px; background:transparent;"
        )
        sv.addWidget(hdr)

        def _stat_row(label: str, attr: str) -> None:
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl_k = QLabel(label)
            lbl_v = QLabel("—")
            lbl_v.setProperty("class", "statVal")
            lbl_v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(lbl_k)
            row.addStretch()
            row.addWidget(lbl_v)
            sv.addLayout(row)
            setattr(self, attr, lbl_v)

        _stat_row("📁 Instances",  "_stat_instances")
        _stat_row("🎯 Intents",    "_stat_intents")
        _stat_row("💾 Disques",    "_stat_drives")
        _stat_row("✅ Sains",      "_stat_healthy")
        _stat_row("⚠️  Avertiss.", "_stat_warnings")
        _stat_row("❌ Cassés",     "_stat_broken")
        sv.addStretch()

        self._sidebar_splitter.addWidget(top)
        self._sidebar_splitter.addWidget(stats_frame)
        self._sidebar_splitter.setSizes([350, 150])
        self._sidebar_splitter.setStretchFactor(0, 1)
        self._sidebar_splitter.setStretchFactor(1, 0)

        root_v.addWidget(self._sidebar_splitter)
        return sb

    def _refresh_sidebar_stats(self) -> None:
        """Met à jour les compteurs de la zone stats de la sidebar."""
        try:
            cfg       = core._load_config()
            instances = cfg.get("instances", [])
            intents   = cfg.get("intents", [])
            self._stat_instances.setText(str(len(instances)))
            self._stat_intents.setText(str(len(intents)))
        except Exception:
            self._stat_instances.setText("—")
            self._stat_intents.setText("—")

        try:
            self._stat_drives.setText(str(self.drive_combo.count()))
        except Exception:
            self._stat_drives.setText("—")

        try:
            from pathlib import Path as _P

            import dashboard as _dash
            cfg   = core._load_config()
            paths = [_P(e["path"]) for e in
                     cfg.get("instances", []) + cfg.get("intents", [])]
            if paths:
                health = [_dash.analyze_project(p) for p in paths]
                healthy  = sum(1 for h in health if h.score >= 80)
                warnings = sum(1 for h in health if 50 <= h.score < 80)
                broken   = sum(1 for h in health if h.score < 50)
                self._stat_healthy.setText(str(healthy))
                self._stat_warnings.setText(str(warnings))
                self._stat_broken.setText(str(broken))
            else:
                for attr in ("_stat_healthy", "_stat_warnings", "_stat_broken"):
                    getattr(self, attr).setText("0")
        except Exception:
            for attr in ("_stat_healthy", "_stat_warnings", "_stat_broken"):
                getattr(self, attr).setText("—")

    def _build_welcome(self) -> QWidget:
        """Écran d'accueil quand aucun projet n'est sélectionné."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(16)

        lbl_icon = QLabel("✦")
        lbl_icon.setStyleSheet("font-size:48px; color:#313244;")
        lbl_icon.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl_icon)

        lbl = QLabel("Sélectionnez un projet dans le panneau gauche")
        lbl.setObjectName("noSel")
        lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl)

        hint = QLabel("Vue liste ☰ ou grille ⊞ — basculez avec les boutons en haut à gauche")
        hint.setStyleSheet("color:#45475a; font-size:11px;")
        hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)

        return w

    def _build_github_account_card(self) -> QWidget:
        """
        Construit la carte de compte GitHub dans la sidebar.
        Affiche soit le compte connecté, soit un bouton de connexion.
        """
        card = QFrame()
        card.setObjectName("githubCard")
        v = QVBoxLayout(card)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)

        # Ligne du haut : icône + statut
        top = QHBoxLayout()
        self._lbl_gh_status = QLabel("🐙  GitHub")
        self._lbl_gh_status.setStyleSheet("font-size: 12px; font-weight: 700; color: #6c7086;")
        top.addWidget(self._lbl_gh_status)
        top.addStretch()
        v.addLayout(top)

        # Sous-ligne : login ou hint
        self._lbl_gh_login = QLabel("Non connecté")
        self._lbl_gh_login.setStyleSheet("font-size: 11px; color: #45475a;")
        v.addWidget(self._lbl_gh_login)

        # Boutons
        btn_row = QHBoxLayout()
        self._btn_gh_connect = QPushButton("🔑  Se connecter")
        self._btn_gh_connect.setObjectName("github")
        self._btn_gh_connect.setFixedHeight(28)
        self._btn_gh_connect.clicked.connect(self.act_github_login)

        self._btn_gh_disconnect = QPushButton("🚪  Déconnecter")
        self._btn_gh_disconnect.setObjectName("subtle")
        self._btn_gh_disconnect.setFixedHeight(28)
        self._btn_gh_disconnect.clicked.connect(self.act_github_logout)
        self._btn_gh_disconnect.setVisible(False)

        btn_row.addWidget(self._btn_gh_connect)
        btn_row.addWidget(self._btn_gh_disconnect)
        v.addLayout(btn_row)

        return card

    def _update_github_account_card(self) -> None:
        """Rafraîchit l'affichage de la carte GitHub selon la session en cours."""
        session = core.get_github_session()
        info    = core.get_github_account_info()

        if session and session.get("login"):
            login = session["login"]
            name  = session.get("name") or login

            self._github_card.setObjectName("githubCardConnected")
            self._github_card.style().unpolish(self._github_card)
            self._github_card.style().polish(self._github_card)

            self._lbl_gh_status.setText("🐙  GitHub  ✅")
            self._lbl_gh_status.setStyleSheet("font-size: 12px; font-weight: 700; color: #a6e3a1;")
            self._lbl_gh_login.setText(f"@{login}  —  {name}")
            self._lbl_gh_login.setStyleSheet("font-size: 11px; color: #a6adc8;")

            self._btn_gh_connect.setVisible(False)
            self._btn_gh_disconnect.setVisible(True)
        else:
            self._github_card.setObjectName("githubCard")
            self._github_card.style().unpolish(self._github_card)
            self._github_card.style().polish(self._github_card)

            self._lbl_gh_status.setText("🐙  GitHub")
            self._lbl_gh_status.setStyleSheet("font-size: 12px; font-weight: 700; color: #6c7086;")

            if info["connected"]:
                # Compte sauvegardé mais pas chargé en session (token protégé)
                login = info.get("login", "")
                self._lbl_gh_login.setText(f"@{login}  (verrouillé 🔐)")
                self._lbl_gh_login.setStyleSheet("font-size: 11px; color: #fab387;")
                self._btn_gh_connect.setText("🔓  Déverrouiller")
            else:
                self._lbl_gh_login.setText("Non connecté")
                self._lbl_gh_login.setStyleSheet("font-size: 11px; color: #45475a;")
                self._btn_gh_connect.setText("🔑  Se connecter")

            self._btn_gh_connect.setVisible(True)
            self._btn_gh_disconnect.setVisible(False)

    # ── CONTENT ──────────────────────────────────

    def _build_content(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)

        self.lbl_no_sel = QLabel("← Sélectionnez une instance ou un intent")
        self.lbl_no_sel.setObjectName("noSel")
        self.lbl_no_sel.setAlignment(Qt.AlignCenter)
        v.addWidget(self.lbl_no_sel)

        self.detail_widget = QWidget()
        self.detail_widget.setVisible(False)
        dv = QVBoxLayout(self.detail_widget)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(10)

        header_h = QHBoxLayout()
        self.lbl_kind_tag = QLabel()
        self.lbl_sel_name = QLabel()
        self.lbl_sel_name.setObjectName("selTitle")
        header_h.addWidget(self.lbl_kind_tag)
        header_h.addWidget(self.lbl_sel_name)
        header_h.addStretch()

        btn_rename = QPushButton("✏  Renommer")
        btn_rename.setObjectName("subtle")
        btn_rename.clicked.connect(self.act_rename)
        header_h.addWidget(btn_rename)
        dv.addLayout(header_h)

        path_grp = QGroupBox("📂  Chemin complet")
        pg = QVBoxLayout(path_grp)
        self.lbl_path = QLabel()
        self.lbl_path.setObjectName("pathLabel")
        self.lbl_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_path.setWordWrap(True)
        pg.addWidget(self.lbl_path)

        path_btns = QHBoxLayout()
        btn_explorer = QPushButton("🗂  Explorateur")
        btn_explorer.clicked.connect(self.act_open_explorer)
        btn_terminal = QPushButton("⬛  Terminal")
        btn_terminal.clicked.connect(self.act_open_terminal)
        btn_vscode = QPushButton("💙  VS Code")
        btn_vscode.setObjectName("teal")
        btn_vscode.clicked.connect(self.act_open_vscode)
        btn_open_with = QPushButton("📂  Ouvrir avec...")
        btn_open_with.setObjectName("subtle")
        btn_open_with.clicked.connect(self.act_open_with)
        path_btns.addWidget(btn_explorer)
        path_btns.addWidget(btn_terminal)
        path_btns.addWidget(btn_vscode)
        path_btns.addWidget(btn_open_with)
        path_btns.addStretch()
        pg.addLayout(path_btns)
        dv.addWidget(path_grp)

        details_toggle_row = QHBoxLayout()
        self.btn_toggle_details = QPushButton("📌 Cacher les détails")
        self.btn_toggle_details.setObjectName("subtle")
        self.btn_toggle_details.setCheckable(True)
        self.btn_toggle_details.setChecked(True)
        self.btn_toggle_details.clicked.connect(self._toggle_details_panel)
        details_toggle_row.addWidget(self.btn_toggle_details)
        details_toggle_row.addStretch()
        dv.addLayout(details_toggle_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_actions_left())
        self._project_details_panel = self._build_project_details_panel()
        splitter.addWidget(self._project_details_panel)
        splitter.addWidget(self._build_log_panel())
        splitter.setSizes([420, 260, 320])
        splitter.setChildrenCollapsible(False)  # Empêcher la fermeture complète
        splitter.setHandleWidth(5)  # Rendre la poignée plus visible
        dv.addWidget(splitter)

        v.addWidget(self.detail_widget)
        v.addStretch()

        return w

    def _build_actions_left(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 8, 0)
        v.setSpacing(10)

        grp_note = QGroupBox("📝  Note")
        gn = QVBoxLayout(grp_note)
        gn.setSpacing(6)
        self.note_edit = QTextEdit()
        self.note_edit.setObjectName("noteEdit")
        self.note_edit.setPlaceholderText("Description, remarques, to-do…")
        self.note_edit.setMinimumHeight(60)
        self.note_edit.setMaximumHeight(100)
        gn.addWidget(self.note_edit)
        btn_save_note = QPushButton("💾  Sauvegarder la note")
        btn_save_note.setObjectName("subtle")
        btn_save_note.clicked.connect(self.act_save_note)
        gn.addWidget(btn_save_note, alignment=Qt.AlignRight)
        v.addWidget(grp_note)

        grp_zip = QGroupBox("📦  Export / Import")
        gz = QVBoxLayout(grp_zip)
        gz.setSpacing(6)
        self.btn_export = QPushButton("💾  Exporter en .zip  (auto → data/backups/)")
        self.btn_export.clicked.connect(self.act_export)
        gz.addWidget(self.btn_export)
        btn_export_custom = QPushButton("💾  Exporter en .zip  (choisir le dossier)")
        btn_export_custom.clicked.connect(self.act_export_custom)
        gz.addWidget(btn_export_custom)
        h3 = QHBoxLayout()
        btn_import_inst = QPushButton("📂  Importer une instance  (.zip)")
        btn_import_inst.clicked.connect(lambda: self.act_import("instance"))
        btn_import_int  = QPushButton("📂  Importer un intent  (.zip)")
        btn_import_int.clicked.connect(lambda: self.act_import("intent"))
        h3.addWidget(btn_import_inst)
        h3.addWidget(btn_import_int)
        gz.addLayout(h3)
        v.addWidget(grp_zip)

        grp_danger = QGroupBox("⚠  Gestion")
        gd = QVBoxLayout(grp_danger)
        self.btn_delete = QPushButton("🗑  Supprimer définitivement ce dossier")
        self.btn_delete.setObjectName("danger")
        self.btn_delete.clicked.connect(self.act_delete)
        gd.addWidget(self.btn_delete)
        self.delete_progress = QProgressBar()
        self.delete_progress.setRange(0, 100)
        self.delete_progress.setValue(0)
        self.delete_progress.setTextVisible(True)
        self.delete_progress.setVisible(False)
        gd.addWidget(self.delete_progress)
        v.addWidget(grp_danger)

        self.grp_git = QGroupBox("🐙  GitHub & Git  (instances)")
        gg = QVBoxLayout(self.grp_git)
        gg.setSpacing(6)

        self.lbl_repo = QLabel("Repo : (non lié)")
        self.lbl_repo.setObjectName("repoLine")
        self.lbl_repo.setTextInteractionFlags(Qt.TextSelectableByMouse)
        gg.addWidget(self.lbl_repo)

        self.lbl_branch_info = QLabel("Branches : —")
        self.lbl_branch_info.setObjectName("repoLine")
        gg.addWidget(self.lbl_branch_info)

        # Indicateur token actif (v1.0.1)
        self.lbl_token_active = QLabel("")
        self.lbl_token_active.setObjectName("sectionLbl")
        self.lbl_token_active.setStyleSheet("color: #6c7086; font-size: 11px;")
        gg.addWidget(self.lbl_token_active)

        h_git1 = QHBoxLayout()
        self.btn_git_clone = QPushButton("📥  Clone")
        self.btn_git_cfg  = QPushButton("🔗  Configurer")
        self.btn_git_init = QPushButton("⚙  git init")
        self.btn_git_push = QPushButton("🚀  Push initial…")
        h_git1.addWidget(self.btn_git_clone)
        h_git1.addWidget(self.btn_git_cfg)
        h_git1.addWidget(self.btn_git_init)
        h_git1.addWidget(self.btn_git_push)
        gg.addLayout(h_git1)

        h_git2 = QHBoxLayout()
        self.btn_git_pull     = QPushButton("⬇  Pull")
        self.btn_git_merge    = QPushButton("🔀  Merge")
        self.btn_git_status   = QPushButton("📋  Status")
        self.btn_git_log      = QPushButton("📜  Log")
        self.btn_git_checkout = QPushButton("🌿  Checkout")
        h_git2.addWidget(self.btn_git_pull)
        h_git2.addWidget(self.btn_git_merge)
        h_git2.addWidget(self.btn_git_status)
        h_git2.addWidget(self.btn_git_log)
        h_git2.addWidget(self.btn_git_checkout)
        gg.addLayout(h_git2)

        h_git3 = QHBoxLayout()
        self.btn_git_commit_push = QPushButton("✔  Commit & Push…")
        self.btn_git_commit_push.setObjectName("success")
        h_git3.addWidget(self.btn_git_commit_push)
        gg.addLayout(h_git3)

        self.lbl_git_busy = QLabel("")
        self.lbl_git_busy.setObjectName("sectionLbl")
        self.lbl_git_busy.setStyleSheet("color: #fab387;")
        gg.addWidget(self.lbl_git_busy)

        self.lbl_token_status = QLabel("")
        self.lbl_token_status.setObjectName("sectionLbl")
        gg.addWidget(self.lbl_token_status)

        self.btn_git_cfg.clicked.connect(self.act_git_configure)
        self.btn_git_clone.clicked.connect(self.act_git_clone)
        self.btn_git_init.clicked.connect(self.act_git_init)
        self.btn_git_push.clicked.connect(self.act_git_push)
        self.btn_git_pull.clicked.connect(self.act_git_pull)
        self.btn_git_merge.clicked.connect(self.act_git_merge)
        self.btn_git_status.clicked.connect(self.act_git_status)
        self.btn_git_log.clicked.connect(self.act_git_log)
        self.btn_git_checkout.clicked.connect(self.act_git_checkout)
        self.btn_git_commit_push.clicked.connect(self.act_git_commit_push)

        v.addWidget(self.grp_git)

        grp_build = QGroupBox("🔨  Project Builder")
        gb = QVBoxLayout(grp_build)
        self.btn_build = QPushButton("▶  Lancer Project Builder dans un terminal")
        self.btn_build.setObjectName("success")
        self.btn_build.clicked.connect(self.act_run_builder)
        gb.addWidget(self.btn_build)
        v.addWidget(grp_build)

        v.addStretch()
        return w

    def _build_project_details_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 0, 0, 0)
        v.setSpacing(6)

        grp = QGroupBox("📌  Détails du projet")
        gl = QFormLayout(grp)
        gl.setLabelAlignment(Qt.AlignLeft)
        gl.setFormAlignment(Qt.AlignTop)
        gl.setHorizontalSpacing(12)
        gl.setVerticalSpacing(10)

        self.detail_type = QLabel("—")
        self.detail_type.setWordWrap(True)
        gl.addRow("Type :", self.detail_type)

        self.detail_status = QLabel("—")
        self.detail_status.setWordWrap(True)
        gl.addRow("Statut :", self.detail_status)

        self.detail_language = QLabel("—")
        self.detail_language.setWordWrap(True)
        gl.addRow("Langage :", self.detail_language)

        self.detail_category = QLabel("—")
        self.detail_category.setWordWrap(True)
        gl.addRow("Catégorie :", self.detail_category)

        self.detail_repo = QLabel("—")
        self.detail_repo.setWordWrap(True)
        gl.addRow("Répertoire Git :", self.detail_repo)

        self.detail_branch = QLabel("—")
        self.detail_branch.setWordWrap(True)
        gl.addRow("Branche :", self.detail_branch)

        self.detail_token_source = QLabel("—")
        self.detail_token_source.setWordWrap(True)
        gl.addRow("Source token :", self.detail_token_source)

        self.detail_created = QLabel("—")
        self.detail_created.setWordWrap(True)
        gl.addRow("Créé le :", self.detail_created)

        self.detail_path = QLabel("—")
        self.detail_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail_path.setWordWrap(True)
        gl.addRow("Chemin :", self.detail_path)

        v.addWidget(grp)
        return w

    def _build_log_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 0, 0, 0)
        v.setSpacing(6)
        grp = QGroupBox("📝  Journal")
        gl = QVBoxLayout(grp)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        gl.addWidget(self.log_area)
        btn_clear = QPushButton("Effacer le journal")
        btn_clear.setObjectName("subtle")
        btn_clear.setFixedWidth(140)
        btn_clear.clicked.connect(self.log_area.clear)
        gl.addWidget(btn_clear, alignment=Qt.AlignRight)
        v.addWidget(grp)
        return w

    # ──────────────────────────────────────────────
    #  HELPERS
    # ──────────────────────────────────────────────

    def _log(self, msg: str):
        # Déléguer au panneau projet si ouvert
        if hasattr(self, "_project_panel") and self._right_stack.currentIndex() == 1:
            self._project_panel.log(msg)
        elif hasattr(self, "log_area"):
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_area.append(
                f'<span style="color:#6c7086">[{ts}]</span>  {msg}'
            )
            sb = self.log_area.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _need_sel(self) -> bool:
        if not self._sel_path:
            QMessageBox.warning(self, "Voktora",
                "Sélectionnez d'abord une instance ou un intent.")
            return False
        return True

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(
            self, title, text, QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes

    def _toggle_details_panel(self) -> None:
        visible = not self._project_details_panel.isVisible()
        self._project_details_panel.setVisible(visible)
        self.btn_toggle_details.setText(
            "📌 Cacher les détails" if visible else "📌 Afficher les détails"
        )

    def _current_drive(self) -> str:
        return self.drive_combo.currentText()

    def _get_token_for_git(self) -> str:
        """
        Retourne le token le plus approprié pour une opération git.
        Priorité : PAT instance > OAuth global.
        Demande le mot de passe si le PAT est protégé.
        """
        if not self._sel_path:
            return ""

        # Token PAT instance depuis le vault
        token = core.get_instance_token(self._sel_path)
        if token:
            return token

        # Token PAT instance protégé
        if core.is_token_protected(self._sel_path):
            dlg = token_password_dialog.TokenPasswordDialog(mode="get", parent=self)
            if dlg.exec() == QDialog.Accepted:
                pwd   = dlg.get_password()
                token = core.get_instance_token(self._sel_path, pwd)
                if not token:
                    QMessageBox.warning(self, "Voktora",
                        "Mot de passe incorrect — impossible de déchiffrer le token.")
                return token

        # Fallback : token OAuth global
        session = core.get_github_session()
        if session and session.get("token"):
            return session["token"]

        return ""

    def _git_buttons(self) -> list[QPushButton]:
        return [
            self.btn_git_clone, self.btn_git_cfg, self.btn_git_init, self.btn_git_push,
            self.btn_git_pull, self.btn_git_merge, self.btn_git_status, self.btn_git_log,
            self.btn_git_checkout, self.btn_git_commit_push,
        ]

    def _set_git_buttons_enabled(self, enabled: bool) -> None:
        for btn in self._git_buttons():
            btn.setEnabled(enabled)

    def _start_worker(self, fn, *args):
        self._worker = workers.Worker(fn, *args)
        self._worker.finished.connect(
            lambda out: self._log(
                f"<pre style='color:#cdd6f4; margin:0'>{html.escape(out)}</pre>"
            )
        )
        self._worker.start()

    def _start_git_worker(self, fn, *args, **kwargs) -> None:
        if self._git_worker and self._git_worker.isRunning():
            QMessageBox.warning(self, "Voktora",
                "Une opération git est déjà en cours.\n"
                "Attendez qu'elle se termine avant d'en lancer une autre.")
            return

        self._set_git_buttons_enabled(False)
        self.lbl_git_busy.setText("⏳  Opération en cours…")

        self._git_worker = workers.GitWorker(fn, *args, **kwargs)
        self._git_worker.log_line.connect(self._log)
        self._git_worker.finished.connect(self._on_git_worker_finished)
        self._git_worker.start()

    def _on_git_worker_finished(self, success: bool) -> None:
        self._set_git_buttons_enabled(True)
        self.lbl_git_busy.setText("")
        if success:
            self._log(
                '<span style="color:#a6e3a1; font-weight:600">✅  Opération git terminée.</span>'
            )

    def _reload_note_autosave_timer(self) -> None:
        app_cfg = core.get_app_config()
        enabled = bool(app_cfg.get("auto_save_notes", False))
        interval = int(app_cfg.get("note_auto_save_interval", 30))
        self._auto_save_timer.setInterval(max(5000, interval * 1000))
        if enabled:
            self._auto_save_timer.start()
        else:
            self._auto_save_timer.stop()

    def _auto_save_note(self) -> None:
        if not self._sel_path or not self._sel_kind:
            return
        current = self.note_edit.toPlainText()
        if current == self._last_saved_note:
            return
        try:
            if self._sel_kind == "instance":
                core.set_instance_note(self._sel_path, current)
            else:
                core.set_intent_note(self._sel_path, current)
            self._last_saved_note = current
            self._log("📝  Note sauvegardée automatiquement.")
        except Exception as e:
            self._log(f"<span style='color:#f38ba8;'>[ERREUR] Impossible de sauvegarder la note automatique : {html.escape(str(e))}</span>")

    # ──────────────────────────────────────────────
    #  GESTION DU CACHE DE PERFORMANCES
    # ──────────────────────────────────────────────

    def _is_cache_valid(self) -> bool:
        """Vérifie si le cache est encore valide."""
        if self._cache_timestamp is None:
            return False
        import time
        return (time.time() - self._cache_timestamp) < self._cache_ttl

    def _invalidate_cache(self) -> None:
        """Invalide le cache pour forcer le rechargement."""
        self._instances_cache = None
        self._intents_cache = None
        self._cache_timestamp = None

    def _get_cached_instances(self) -> list[dict]:
        """Retourne les instances depuis le cache ou les charge si nécessaire."""
        if not self._is_cache_valid() or self._instances_cache is None:
            self._instances_cache = core.list_instances()
            self._intents_cache = core.list_intents()
            import time
            self._cache_timestamp = time.time()
        return self._instances_cache

    def _get_cached_intents(self) -> list[dict]:
        """Retourne les intents depuis le cache ou les charge si nécessaire."""
        if not self._is_cache_valid() or self._intents_cache is None:
            self._instances_cache = core.list_instances()
            self._intents_cache = core.list_intents()
            import time
            self._cache_timestamp = time.time()
        return self._intents_cache

    # ──────────────────────────────────────────────
    #  CHARGEMENT / RAFRAÎCHISSEMENT
    # ──────────────────────────────────────────────

    def _refresh_all(self):
        self._refresh_drives()
        self._refresh_lists()
        try:
            self._refresh_sidebar_stats()
        except Exception:
            pass

    def _refresh_drives(self):
        self.drive_combo.blockSignals(True)
        self.drive_combo.clear()
        drives = core.get_available_drives()
        self.drive_combo.addItems(drives if drives else ["(aucun disque externe)"])
        self.drive_combo.blockSignals(False)

    def _refresh_lists(self):
        # Utiliser le cache pour un accès instantané
        instances = self._get_cached_instances()
        intents = self._get_cached_intents()

        # Mise à jour statusbar
        n_inst = len(instances)
        n_int  = len(intents)
        if hasattr(self, "_status_lbl"):
            self._set_status(
                f"{n_inst} instance{'s' if n_inst != 1 else ''}  ·  "
                f"{n_int} intent{'s' if n_int != 1 else ''}"
            )

        # Mise à jour du ProjectBrowser (liste + grille)
        self._browser.populate(instances, intents)
        # Compat legacy : aussi maintenir instance_list / intent_list si utilisés ailleurs
        if hasattr(self, "instance_list"):
            self.instance_list.clear()
            for e in instances:
                item = QListWidgetItem(e.get("name", e["path"]))
                item.setData(Qt.UserRole, e["path"])
                self.instance_list.addItem(item)
        if hasattr(self, "intent_list"):
            self.intent_list.clear()
            for e in intents:
                item = QListWidgetItem(e.get("name", e["path"]))
                item.setData(Qt.UserRole, e["path"])
                self.intent_list.addItem(item)

    def _on_drive_changed(self, _):
        pass

    def _on_project_selected(self, path: str, kind: str) -> None:
        """Appelé par ProjectBrowser quand l'utilisateur clique sur un projet."""
        self._sel_path = Path(path)
        self._sel_kind = kind
        self._project_panel.show_project(path, kind, on_action=self._dispatch_action)
        self._right_stack.setCurrentIndex(1)   # switcher vers le panneau projet
        # Mettre à jour statusbar
        if hasattr(self, "_status_lbl"):
            self._set_status(f"Projet : {self._sel_path.name}")
        # Hook on_open + usage tracking
        import dashboard as _d
        import hooks as _h
        _h.fire("on_open", self._sel_path, log_cb=self._project_panel.log)
        _d.record_open(self._sel_path)

    def _show_welcome(self) -> None:
        """Retour à la liste/grille des projets."""
        self._right_stack.setCurrentIndex(0)
        self._sel_path = None
        self._sel_kind = None
        if hasattr(self, "_status_lbl"):
            self._set_status("Pret")

    def _show_project_switcher(self) -> None:
        """Affiche le browser et met le focus sur la recherche."""
        self._right_stack.setCurrentIndex(0)
        self._browser.get_search_widget().setFocus()
        self._browser.get_search_widget().selectAll()

    def _dispatch_action(self, action: str, path: Path, kind: str) -> None:
        """Pont entre ProjectPanel et les méthodes act_* de MainWindow."""
        self._sel_path = path
        self._sel_kind = kind
        dispatch = {
            "open_explorer":  self.act_open_explorer,
            "open_terminal":  self.act_open_terminal,
            "open_vscode":    self.act_open_vscode,
            "open_with":      self.act_open_with,
            "rename":         self.act_rename,
            "delete":         self.act_delete,
            "export":         self.act_export,
            "export_custom":  self.act_export_custom,
            "import_instance": lambda: self.act_import("instance"),
            "import_intent":   lambda: self.act_import("intent"),
            "run_builder":    self.act_run_builder,
            "git_init":       self.act_git_init,
            "git_clone":      self.act_git_clone,
            "git_configure":  self.act_git_configure,
            "git_status":     self.act_git_status,
            "git_pull":       self.act_git_pull,
            "git_push":       self.act_git_push,
            "git_log":        self.act_git_log,
            "git_checkout":   self.act_git_checkout,
            "git_commit_push": self.act_git_commit_push,
            "git_merge":      self.act_git_merge,
            "transfer_kind":  self.act_transfer_kind,
        }
        fn = dispatch.get(action)
        if fn:
            fn()

    def _on_select(self, item: QListWidgetItem | None, kind: str):
        """Compatibilité legacy — redirige vers _on_project_selected."""
        if item is None:
            return
        self._on_project_selected(item.data(Qt.UserRole), kind)
        self._sel_kind = kind
        self._sel_path = Path(item.data(Qt.UserRole))

        if kind == "instance":
            self.intent_list.blockSignals(True)
            self.intent_list.clearSelection()
            self.intent_list.setCurrentItem(None)
            self.intent_list.blockSignals(False)
        else:
            self.instance_list.blockSignals(True)
            self.instance_list.clearSelection()
            self.instance_list.setCurrentItem(None)
            self.instance_list.blockSignals(False)

        self._update_detail_panel()

    def _update_detail_panel(self):
        # Le ProjectPanel gère l'affichage — cette méthode ne fait rien si le panneau est actif
        if self._right_stack.currentIndex() == 1:
            return
        if not self._sel_path:
            self.lbl_no_sel.setVisible(True)
            self.detail_widget.setVisible(False)
            return

        self.lbl_no_sel.setVisible(False)
        self.detail_widget.setVisible(True)

        if self._sel_kind == "instance":
            self.lbl_kind_tag.setText("INSTANCE")
            self.lbl_kind_tag.setObjectName("kindTag")
            self.grp_git.setVisible(True)

            repo      = core.get_instance_repo(self._sel_path)
            branches  = core.get_instance_branches(self._sel_path)
            protected = core.is_token_protected(self._sel_path)

            self.lbl_repo.setText(f"Repo : {repo or '(non lié)'}")
            self.lbl_branch_info.setText(
                f"Branches : {', '.join(branches) if branches else '—'}"
            )
            self.lbl_token_status.setText(
                "🔐  Token PAT protégé par mot de passe (AES-256)" if protected else ""
            )

            # Affiche la source du token qui sera utilisé (v1.0.1)
            pat_raw = core.get_instance_token_raw(self._sel_path)
            session = core.get_github_session()
            if pat_raw:
                src = "🔑  Token PAT spécifique à cette instance"
                if protected:
                    src += " (chiffré)"
            elif session and session.get("token"):
                login = session.get("login", "")
                src = f"🐙  Token OAuth du compte @{login}"
            else:
                src = "⚠  Aucun token — repos publics uniquement"
            self.lbl_token_active.setText(src)

            self.note_edit.setPlainText(core.get_instance_note(self._sel_path))
            self._last_saved_note = self.note_edit.toPlainText()
            self.detail_type.setText("Instance")
            project_entry = core._find_entry(core._load_config(), "instances", self._sel_path)
            project_status = "—"
            if project_entry:
                status_id = project_entry.get("status", "")
                status_obj = core.get_project_status_by_id(status_id)
                project_status = status_obj.name if status_obj else "—"
            self.detail_status.setText(project_status)
            self.detail_language.setText(
                core.get_instance_language(self._sel_path) or core.guess_project_language(self._sel_path)
            )
            self.detail_category.setText(
                project_entry.get("category") or "—" if project_entry else "—"
            )
            self.detail_repo.setText(repo or "—")
            self.detail_branch.setText(branches[0] if branches else "—")
            self.detail_token_source.setText(src)
            self.detail_created.setText(
                project_entry.get("created", "—") if project_entry else "—"
            )
            self.detail_path.setText(str(self._sel_path))
        else:
            self.lbl_kind_tag.setText("INTENT")
            self.lbl_kind_tag.setObjectName("kindTagIntent")
            self.grp_git.setVisible(False)
            self.note_edit.setPlainText(core.get_intent_note(self._sel_path))
            self._last_saved_note = self.note_edit.toPlainText()
            self.detail_type.setText("Intent")
            intent_entry = core._find_entry(core._load_config(), "intents", self._sel_path)
            self.detail_status.setText("—")
            self.detail_language.setText(
                core.get_intent_language(self._sel_path) or core.guess_project_language(self._sel_path)
            )
            self.detail_category.setText(
                intent_entry.get("category") or "—" if intent_entry else "—"
            )
            self.detail_repo.setText("—")
            self.detail_branch.setText("—")
            self.detail_token_source.setText("—")
            self.detail_created.setText(
                intent_entry.get("created", "—") if intent_entry else "—"
            )
            self.detail_path.setText(str(self._sel_path))

        self.lbl_kind_tag.style().unpolish(self.lbl_kind_tag)
        self.lbl_kind_tag.style().polish(self.lbl_kind_tag)

        self.lbl_sel_name.setText(f"  {self._sel_path.name}")
        self.lbl_path.setText(str(self._sel_path))

    # ══════════════════════════════════════════════
    #  ACTIONS — GitHub OAuth (v1.0.1)
    # ══════════════════════════════════════════════

    def act_github_login(self) -> None:
        """Ouvre le dialog de connexion GitHub OAuth."""
        dlg = github_login_dialog.GitHubLoginDialog(parent=self)
        dlg.connected.connect(self._on_github_connected)
        dlg.exec()

    def _on_github_connected(self, login: str, name: str, token: str) -> None:
        """Appelé après connexion OAuth réussie."""
        user_info = {"login": login, "name": name}

        # Proposer de protéger le token par mot de passe
        reply = QMessageBox.question(
            self,
            "🔐  Protéger le token OAuth ?",
            f"Connexion réussie : <b>@{login}</b>\n\n"
            "Voulez-vous protéger le token OAuth avec un mot de passe ?\n"
            "(recommandé si d'autres personnes utilisent cet ordinateur)",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            pwd_dlg = token_password_dialog.TokenPasswordDialog(mode="set", parent=self)
            if pwd_dlg.exec() == QDialog.Accepted:
                password = pwd_dlg.get_password()
                core.save_github_account(token, user_info, password=password)
                self._log(f"🔐  Compte GitHub @{login} connecté et sécurisé.")
            else:
                core.save_github_account(token, user_info)
                self._log(f"🐙  Compte GitHub @{login} connecté (sans protection).")
        else:
            core.save_github_account(token, user_info)
            self._log(f"🐙  Compte GitHub @{login} connecté.")

        self._update_github_account_card()
        self._update_detail_panel()

    def act_github_logout(self) -> None:
        """Déconnecte le compte GitHub."""
        session = core.get_github_session()
        info    = core.get_github_account_info()

        login = (session.get("login") if session else None) or info.get("login") or "GitHub"

        if not self._confirm(
            "Déconnexion GitHub",
            f"Déconnecter le compte @{login} ?\n\n"
            "Le token OAuth sera supprimé de la configuration.\n"
            "Les tokens PAT spécifiques aux instances ne seront pas affectés.",
        ):
            return

        core.clear_github_account()
        self._log(f"🚪  Compte GitHub @{login} déconnecté.")
        self._update_github_account_card()
        self._update_detail_panel()

    # ══════════════════════════════════════════════
    #  ACTIONS — Général
    # ══════════════════════════════════════════════

    def act_create(self, kind: str):
        dlg = create_dialog.CreateDialog(kind, self)
        if dlg.exec() != QDialog.Accepted:
            return
        drive, name = dlg.get_data()
        try:
            path = (core.create_instance(drive, name)
                    if kind == "instance"
                    else core.create_intent(drive, name))
            self._log(
                f"{'📦' if kind == 'instance' else '🧩'}  "
                f"<b>{name}</b> créé  →  <span style='color:#89dceb'>{path}</span>"
            )
            self._invalidate_cache()  # Invalider le cache pour refléter les changements
            self._refresh_lists()
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e))

    def act_rename(self):
        if not self._need_sel():
            return
        old_name = self._sel_path.name
        new_name, ok = QInputDialog.getText(
            self, "Renommer", f"Nouveau nom pour « {old_name} » :", text=old_name
        )
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        try:
            new_path = (core.rename_instance(self._sel_path, new_name.strip())
                        if self._sel_kind == "instance"
                        else core.rename_intent(self._sel_path, new_name.strip()))
            self._log(f"✏  Renommé : <b>{old_name}</b> → <b>{new_path.name}</b>")
            self._sel_path = new_path
            self._invalidate_cache()  # Invalider le cache pour refléter les changements
            self._refresh_lists()
            self._update_detail_panel()
        except Exception as e:
            QMessageBox.critical(self, "Erreur renommage", str(e))

    def act_transfer_kind(self):
        """Bascule le projet sélectionné entre Instance et Intent."""
        if not self._need_sel():
            return
        from_kind = self._sel_kind
        to_kind   = "intent" if from_kind == "instance" else "instance"
        label     = "Intent" if to_kind == "intent" else "Instance"
        if not self._confirm(
            f"Transférer vers {label}",
            f"Transférer « {self._sel_path.name} » de "
            f"{'Instance' if from_kind == 'instance' else 'Intent'} vers {label} ?\n\n"
            "Le dossier sera déplacé physiquement vers l'emplacement correspondant.",
        ):
            return
        try:
            new_path = core.transfer_project(self._sel_path, from_kind, to_kind)
            self._log(f"🔀  <b>{new_path.name}</b> transféré vers {label}.")
            self._sel_path = new_path
            self._sel_kind = to_kind
            self._invalidate_cache()
            self._refresh_lists()
            self._update_detail_panel()
        except Exception as e:
            QMessageBox.critical(self, "Erreur de transfert", str(e))

    def act_save_note(self):
        if not self._need_sel():
            return
        note = self.note_edit.toPlainText()
        try:
            if self._sel_kind == "instance":
                core.set_instance_note(self._sel_path, note)
            else:
                core.set_intent_note(self._sel_path, note)
            self._log("📝  Note sauvegardée.")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e))

    def act_delete(self):
        if not self._need_sel():
            return
        if not self._confirm(
            "Supprimer définitivement",
            f"Supprimer :\n\n{self._sel_path}\n\nCette action est irréversible.",
        ):
            return

        self.btn_delete.setEnabled(False)
        self.delete_progress.setValue(0)
        self.delete_progress.setVisible(True)
        self._delete_worker = workers.DeleteWorker(self._sel_path)
        self._delete_worker.progress.connect(self.delete_progress.setValue)
        self._delete_worker.finished.connect(self._on_delete_finished)
        self._delete_worker.start()

    def _on_delete_finished(self, success: bool, error: str) -> None:
        self.delete_progress.setVisible(False)
        self.btn_delete.setEnabled(True)

        if not success:
            QMessageBox.critical(
                self,
                "Erreur suppression",
                f"Impossible de supprimer le dossier :\n{html.escape(error)}"
            )
            self._log(f"<span style='color:#f38ba8;'>[ERREUR] Suppression échouée : {html.escape(error)}</span>")
            return

        if self._sel_path:
            name, path, kind = self._sel_path.name, self._sel_path, self._sel_kind
            if kind == "instance":
                core.delete_instance(path)
            else:
                core.delete_intent(path)
            self._log(f"🗑  <b>{name}</b> supprimé.")

        self._sel_path = None
        self.lbl_no_sel.setVisible(True)
        self.detail_widget.setVisible(False)
        self._invalidate_cache()  # Invalider le cache pour refléter les changements
        self._refresh_lists()

    def act_export(self):
        if not self._need_sel():
            return
        try:
            zip_path = core.export_to_zip(self._sel_path)
            self._log(f"💾  Exporté  →  <span style='color:#89dceb'>{zip_path}</span>")
            QMessageBox.information(self, "Export réussi", f"Archive sauvegardée :\n{zip_path}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur export", str(e))

    def act_export_custom(self):
        if not self._need_sel():
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Choisir le dossier de destination")
        if not out_dir:
            return
        try:
            zip_path = core.export_to_zip(self._sel_path, Path(out_dir))
            self._log(f"💾  Exporté  →  <span style='color:#89dceb'>{zip_path}</span>")
            QMessageBox.information(self, "Export réussi", f"Archive créée :\n{zip_path}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur export", str(e))

    def act_import(self, kind: str):
        label = "instance" if kind == "instance" else "intent"
        drive = self._current_drive()
        if drive.startswith("("):
            QMessageBox.warning(self, "Voktora", "Aucun disque externe sélectionné.")
            return

        choice = QMessageBox.question(
            self, f"Importer une {label}",
            "Importer depuis un fichier .zip ou directement un dossier existant ?\n\n"
            "Oui = choisir un dossier   ·   Non = choisir un fichier .zip",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.No,
        )
        if choice == QMessageBox.Cancel:
            return

        try:
            if choice == QMessageBox.Yes:
                folder = QFileDialog.getExistingDirectory(
                    self, f"Sélectionner le dossier à importer ({label})"
                )
                if not folder:
                    return
                path = core.import_from_folder(Path(folder), drive, kind)
            else:
                zip_file, _ = QFileDialog.getOpenFileName(
                    self, f"Sélectionner le .zip ({label})",
                    filter="Archives ZIP (*.zip)"
                )
                if not zip_file:
                    return
                path = core.import_from_zip(Path(zip_file), drive, kind)

            self._log(
                f"📂  Import {label}  →  <span style='color:#89dceb'>{path}</span>"
            )
            self._invalidate_cache()  # Invalider le cache pour refléter les changements
            self._refresh_lists()
        except Exception as e:
            QMessageBox.critical(self, "Erreur import", str(e))

    def act_open_explorer(self):
        if not self._need_sel():
            return
        core.open_explorer(self._sel_path)
        self._log(f"🗂  Explorateur ouvert  →  {self._sel_path}")

    def act_open_terminal(self):
        if not self._need_sel():
            return
        core.open_terminal(self._sel_path)
        self._log(f"⬛  Terminal ouvert  →  {self._sel_path}")

    def act_open_vscode(self):
        if not self._need_sel():
            return
        try:
            core.open_vscode(self._sel_path)
            self._log(f"💙  VS Code ouvert  →  {self._sel_path}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur VS Code", str(e))

    # ══════════════════════════════════════════════
    #  ACTIONS — Paramètres (v1.0.1)
    # ══════════════════════════════════════════════

    def act_open_storage_settings(self):
        dlg = storage_dialog.StorageDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._log("⚙  Emplacements de stockage mis à jour.")

    def act_run_diagnostic(self):
        result = core.run_health_check()
        if result.is_healthy:
            QMessageBox.information(self, "Voktora — Diagnostic",
                "✅  Aucun problème détecté.\nL'application et les données sont en bonne santé.")
        else:
            dlg = diagnostic_dialog.DiagnosticDialog(result, parent=self)
            dlg.exec()
            self._refresh_all()

    # ══════════════════════════════════════════════
    #  ACTIONS — Git
    # ══════════════════════════════════════════════

    def act_git_configure(self):
        if not self._need_sel():
            return
        if self._sel_kind != "instance":
            QMessageBox.information(self, "Voktora",
                "GitHub est disponible uniquement pour les instances.")
            return

        current_url     = core.get_instance_repo(self._sel_path)
        current_branch  = core.get_instance_branch(self._sel_path)
        token_protected = core.is_token_protected(self._sel_path)
        session         = core.get_github_session()
        has_global      = bool(session and session.get("token"))
        global_login    = session.get("login", "") if session else ""

        dlg = git_dialog.GitDialog(
            current_url=current_url,
            current_branch=current_branch,
            token_protected=token_protected,
            has_global_account=has_global,
            global_login=global_login,
            parent=self,
        )

        token_in_vault = core.get_instance_token(self._sel_path)
        if token_in_vault:
            dlg.token_edit.setText(token_in_vault)
            dlg._token_in_clear = token_in_vault

        if dlg.exec() != QDialog.Accepted:
            return

        data           = dlg.get_data()
        url            = data["url"]
        token          = data["token"]
        branch         = data["branch"]
        do_init        = data["do_init"]
        do_push        = data["do_push"]
        protect        = data["protect"]
        token_password = data["token_password"]

        if url:
            core.set_instance_repo(self._sel_path, url)
            self._log(f"🔗  GitHub lié  →  {url}")

        core.set_instance_branch(self._sel_path, branch)
        saved = core.get_instance_branches(self._sel_path)
        if branch not in saved:
            core.set_instance_branches(self._sel_path, [branch])
        self._log(f"🌿  Branche principale  →  <b>{branch}</b>")

        if token:
            if protect and token_password:
                core.set_instance_token(self._sel_path, token, token_password)
                algo = "AES-256 (Fernet, PBKDF2-HMAC-SHA256)"
                self._log(f"🔐  Token PAT chiffré et sauvegardé  (algo : {algo})")
            elif not protect:
                core.set_instance_token(self._sel_path, token, "")
                self._log("🔑  Token PAT sauvegardé (non protégé).")

        if do_init:
            out = core.git_init(self._sel_path)
            self._log(f"⚙  git init : {html.escape(out)}")

        if do_push:
            if not url:
                QMessageBox.warning(self, "Voktora", "Configurez d'abord une URL de repo.")
                return
            self._open_push_dialog(mode="initial")
            return

        self._update_detail_panel()

    def act_git_init(self):
        if not self._need_sel():
            return
        out = core.git_init(self._sel_path)
        self._log(f"⚙  git init : {html.escape(out)}")

    def act_git_push(self):
        if not self._need_sel():
            return
        url = core.get_instance_repo(self._sel_path)
        if not url:
            QMessageBox.warning(self, "Voktora",
                "Aucun repo GitHub lié à cette instance.\nConfigurez GitHub d'abord.")
            return
        self._open_push_dialog(mode="initial")

    def act_git_commit_push(self):
        if not self._need_sel():
            return
        url = core.get_instance_repo(self._sel_path)
        if not url:
            QMessageBox.warning(self, "Voktora", "Aucun repo GitHub lié à cette instance.")
            return
        self._open_push_dialog(mode="commit")

    def act_git_merge(self):
        if not self._need_sel():
            return
        if self._sel_kind != "instance":
            QMessageBox.information(self, "Voktora", "Git merge est disponible uniquement pour les instances.")
            return
        
        # Demander la branche à merger
        branch, ok = QInputDialog.getText(
            self, "Git Merge", 
            "Entrez le nom de la branche à merger dans la branche actuelle :",
            text=""
        )
        if not ok or not branch.strip():
            return
        
        if not self._confirm(
            "Git Merge",
            f"Merger la branche <b>{branch.strip()}</b> dans la branche actuelle ?\n\n"
            "Cette action modifiera l'historique Git."
        ):
            return
        
        self._log(f"🔀  Merge de la branche <b>{branch.strip()}</b>...")
        self._start_git_worker(
            core.git_merge,
            self._sel_path,
            branch.strip(),
            token=self._get_token_for_git()
        )

    def _open_push_dialog(self, mode: str = "commit") -> None:
        dlg = push_dialog.PushDialog(instance_path=self._sel_path, mode=mode, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return

        data        = dlg.get_data()
        branches    = data["branches"]
        message     = data["message"]
        description = data["description"]
        force       = data["force"]
        follow_tags = data["follow_tags"]
        no_verify   = data["no_verify"]

        core.set_instance_branches(self._sel_path, branches)

        url      = core.get_instance_repo(self._sel_path)
        token    = self._get_token_for_git()
        push_url = self._build_push_url(url, token)

        # Log de la source du token utilisé
        pat_raw = core.get_instance_token_raw(self._sel_path)
        session = core.get_github_session()
        if pat_raw:
            self._log("🔑  Authentification : token PAT de l'instance")
        elif session and session.get("token"):
            self._log(f"🐙  Authentification : compte GitHub @{session.get('login', '')}")
        else:
            self._log("⚠  Aucun token — push en mode public")

        br_str = ", ".join(f"<b>{b}</b>" for b in branches)
        verb   = "Push initial" if mode == "initial" else "Commit & Push"
        self._log(f"🚀  {verb} → branches : {br_str}")
        if force:
            self._log('<span style="color:#f38ba8">⚠  --force activé</span>')

        self._start_git_worker(
            core.git_push_advanced,
            self._sel_path,
            push_url,
            branches,
            message=message,
            description=description,
            force=force,
            follow_tags=follow_tags,
            no_verify=no_verify,
            is_initial=(mode == "initial"),
        )

        self._update_detail_panel()

    def act_git_pull(self):
        if not self._need_sel():
            return
        url = core.get_instance_repo(self._sel_path)
        if not url:
            QMessageBox.warning(self, "Voktora", "Aucun repo GitHub lié à cette instance.")
            return
        branch = core.get_instance_branch(self._sel_path)
        self._log(f"⬇  git pull → branche <b>{branch}</b>…")
        self._start_worker(core.git_pull, self._sel_path, branch)

    def act_git_status(self):
        if not self._need_sel():
            return
        out = core.git_status(self._sel_path)
        self._log(
            f"<pre style='color:#cdd6f4; margin:0'>{html.escape(out)}</pre>"
        )

    def act_git_log(self):
        if not self._need_sel():
            return
        out = core.git_log(self._sel_path)
        if out:
            self._log(
                f"<pre style='color:#b4befe; margin:0'>{html.escape(out)}</pre>"
            )
        else:
            self._log("📜  Aucun commit trouvé (ou dépôt non initialisé).")

    def act_git_checkout(self):
        if not self._need_sel():
            return
        local_branches = core.git_list_local_branches(self._sel_path)
        current_branch = core.get_instance_branch(self._sel_path)

        items  = local_branches if local_branches else ["main", "develop"]
        branch, ok = QInputDialog.getItem(
            self, "Checkout",
            "Sélectionnez ou saisissez une branche :",
            items, editable=True,
            current=items.index(current_branch) if current_branch in items else 0,
        )
        if not ok or not branch.strip():
            return
        branch = branch.strip()
        out    = core.git_checkout(self._sel_path, branch)
        self._log(f"🌿  git checkout <b>{branch}</b> : {html.escape(out)}")
        core.set_instance_branch(self._sel_path, branch)
        self._update_detail_panel()

    @staticmethod
    def _build_push_url(repo_url: str, token: str) -> str:
        if not token:
            return repo_url
        url = repo_url.rstrip("/")
        if url.startswith("https://"):
            url = "https://" + token + "@" + url[len("https://"):]
        return url

    def act_run_builder(self):
        if not self._need_sel():
            return
        try:
            core.run_project_builder(self._sel_path)
            self._log(f"▶  Project Builder lancé  →  cwd = {self._sel_path}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e))

    def act_uninstall(self):
        dlg = uninstall_dialog.UninstallDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return

        do_backup, backup_dir = dlg.get_options()

        if do_backup and backup_dir:
            progress = QMessageBox(self)
            progress.setWindowTitle("Voktora — Backup en cours")
            progress.setText(
                "Export de toutes les données en cours…\n\n"
                "Veuillez patienter, ne fermez pas l'application."
            )
            progress.setStandardButtons(QMessageBox.NoButton)
            progress.show()
            QApplication.processEvents()

            try:
                done = core.uninstall_backup_all(backup_dir)
                progress.hide()
                detail = "\n".join(done) if done else "(aucune donnée trouvée)"
                QMessageBox.information(
                    self, "Backup terminé",
                    f"Export réussi vers :\n{backup_dir}\n\n"
                    f"Éléments sauvegardés :\n{detail}\n\n"
                    "Voktora va maintenant se désinstaller."
                )
            except Exception as e:
                progress.hide()
                if QMessageBox.critical(
                    self, "Erreur pendant le backup",
                    f"Une erreur s'est produite :\n{e}\n\n"
                    "Voulez-vous continuer la désinstallation quand même ?",
                    QMessageBox.Yes | QMessageBox.No,
                ) == QMessageBox.No:
                    return

        try:
            bat_path = core.create_uninstall_script()
        except Exception as e:
            QMessageBox.critical(self, "Erreur",
                f"Impossible de créer le script de désinstallation :\n{e}")
            return

        QMessageBox.information(
            self, "Voktora — Désinstallation",
            f"Le script de désinstallation a été créé :\n{bat_path}\n\n"
            "Voktora va se fermer maintenant.\n"
            "Une fenêtre de terminal s'ouvrira brièvement pour finaliser\n"
            "la suppression des fichiers, puis disparaîtra."
        )

        core.launch_uninstall_and_quit(bat_path)

    # ──────────────────────────────────────────────
    #  NOUVELLES ACTIONS v1.0.1
    # ──────────────────────────────────────────────

    def act_git_clone(self):
        """Action pour cloner un repo GitHub."""
        from PySide6.QtWidgets import QInputDialog
        
        url, ok = QInputDialog.getText(
            self, "Git Clone", "URL du repository GitHub :"
        )
        if not ok or not url.strip():
            return
            
        # Demander le disque de destination
        drives = core.get_available_drives()
        if not drives:
            QMessageBox.warning(self, "Voktora", "Aucun disque disponible.")
            return
            
        drive, ok = QInputDialog.getItem(
            self, "Git Clone", "Disque de destination :", drives
        )
        if not ok:
            return
            
        # Demander le nom du projet
        project_name, ok = QInputDialog.getText(
            self, "Git Clone", "Nom du projet :", text="cloned-repo"
        )
        if not ok or not project_name.strip():
            return
            
        try:
            target_path = core.get_instances_root(drive) / project_name.strip()
            self._log(f"📥 Clone de {url} vers {target_path}...")
            
            # Utiliser le token effectif si disponible
            token = core.get_effective_token()
            out = core.git_clone(url.strip(), target_path, token)
            
            self._log(f"✅ Clone terminé : {html.escape(out)}")
            
            # Ajouter aux instances si le dossier existe
            if target_path.exists():
                cfg = core._load_config()
                cfg["instances"].append({
                    "name": project_name.strip(),
                    "path": str(target_path),
                    "drive": drive,
                    "created": datetime.now().isoformat(),
                    "github_repo": url.strip(),
                    "github_branches": ["main"],
                    "github_branch": "main",
                    "github_token": "",
                    "github_token_protected": False,
                    "note": f"Cloné depuis {url}",
                    "status": core.DEFAULT_PROJECT_STATUS,
                    "color": None,
                    "emoji": "📥",
                    "category": None,
                })
                core._save_config(cfg)
                self._refresh_all()
                self._log(f"📦 Instance '{project_name}' ajoutée à la liste")
                
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible de cloner le repo :\n{e}")

    def act_import_zip(self):
        """Action pour importer depuis un ZIP."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Importer depuis ZIP", "", "Fichiers ZIP (*.zip)"
        )
        if not file_path:
            return
            
        drives = core.get_available_drives()
        if not drives:
            QMessageBox.warning(self, "Voktora", "Aucun disque disponible.")
            return
            
        drive, ok = QInputDialog.getItem(
            self, "Importer", "Disque de destination :", drives
        )
        if not ok:
            return
            
        kind, ok = QInputDialog.getItem(
            self, "Importer", "Type :", ["instance", "intent"], 0
        )
        if not ok:
            return
            
        try:
            path = core.import_from_zip(Path(file_path), drive, kind)
            self._log(f"📂 Importé : {path}")
            self._refresh_all()
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'importer :\n{e}")

    def act_import_meridian_config(self) -> None:
        """
        Importe un config.json provenant de l'ancienne version Meridian
        (ou d'une autre instance Voktora) et fusionne les instances/intents
        sans écraser les données existantes.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Importer une configuration Meridian / Voktora",
            "",
            "Fichiers JSON (*.json);;Tous les fichiers (*)"
        )
        if not file_path:
            return

        # Lire et valider le JSON
        try:
            with open(file_path, encoding="utf-8") as f:
                legacy_cfg = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Erreur de lecture",
                                 f"Impossible de lire le fichier :\n{e}")
            return

        # Compter ce qu'on va importer
        instances = legacy_cfg.get("instances", [])
        intents   = legacy_cfg.get("intents",   [])
        categories = legacy_cfg.get("categories", [])
        custom_statuses = legacy_cfg.get("custom_statuses", {})
        storage   = legacy_cfg.get("storage",   {})

        if not instances and not intents:
            QMessageBox.warning(
                self, "Rien à importer",
                "Le fichier ne contient ni 'instances' ni 'intents'.\n"
                "Vérifiez qu'il s'agit bien d'un config.json Meridian / Voktora."
            )
            return

        # Résumé de prévisualisation
        preview_lines = []
        if instances:
            preview_lines.append(f"  • {len(instances)} instance(s) :")
            for e in instances[:5]:
                preview_lines.append(f"      - {e.get('name','?')}  [{e.get('language','?')}]  {e.get('status','')}")
            if len(instances) > 5:
                preview_lines.append(f"      … +{len(instances)-5} autres")
        if intents:
            preview_lines.append(f"  • {len(intents)} intent(s) :")
            for e in intents[:5]:
                preview_lines.append(f"      - {e.get('name','?')}  [{e.get('language','?')}]  {e.get('status','')}")
            if len(intents) > 5:
                preview_lines.append(f"      … +{len(intents)-5} autres")
        if categories:
            preview_lines.append(f"  • {len(categories)} catégorie(s)")
        if custom_statuses:
            preview_lines.append(f"  • {len(custom_statuses)} statut(s) personnalisé(s)")
        if storage:
            preview_lines.append(f"  • Racines : {storage.get('instances_root','?')}")

        msg = QMessageBox(self)
        msg.setWindowTitle("Confirmer l'import")
        msg.setIcon(QMessageBox.Question)
        msg.setText(
            f"<b>Fichier :</b> {Path(file_path).name}<br><br>"
            f"Contenu détecté :<br>"
            + "<br>".join(f"<code>{ln}</code>" for ln in preview_lines)
            + "<br><br>Les entrées déjà présentes (même chemin) seront <b>ignorées</b>.<br>"
              "Les nouvelles seront <b>ajoutées</b> sans rien supprimer."
        )
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.button(QMessageBox.Ok).setText("✅ Importer")
        msg.button(QMessageBox.Cancel).setText("Annuler")
        if msg.exec() != QMessageBox.Ok:
            return

        # Fusion dans le config courant
        try:
            current_cfg = core._load_config()

            # Instances — déduplique par chemin
            existing_paths = {e["path"] for e in current_cfg.get("instances", [])}
            added_inst = 0
            for entry in instances:
                if entry.get("path") not in existing_paths:
                    current_cfg.setdefault("instances", []).append(entry)
                    existing_paths.add(entry["path"])
                    added_inst += 1

            # Intents — déduplique par chemin
            existing_paths_i = {e["path"] for e in current_cfg.get("intents", [])}
            added_int = 0
            for entry in intents:
                if entry.get("path") not in existing_paths_i:
                    current_cfg.setdefault("intents", []).append(entry)
                    existing_paths_i.add(entry["path"])
                    added_int += 1

            # Catégories — union
            if categories:
                existing_cats = set(current_cfg.get("categories", []))
                for cat in categories:
                    if cat not in existing_cats:
                        current_cfg.setdefault("categories", []).append(cat)
                        existing_cats.add(cat)

            # Statuts personnalisés — merge sans écraser
            if custom_statuses:
                current_cfg.setdefault("custom_statuses", {}).update(
                    {k: v for k, v in custom_statuses.items()
                     if k not in current_cfg.get("custom_statuses", {})}
                )

            # Racines storage — uniquement si vides
            if storage:
                cfg_storage = current_cfg.setdefault("storage", {})
                if not cfg_storage.get("instances_root") and storage.get("instances_root"):
                    cfg_storage["instances_root"] = storage["instances_root"]
                if not cfg_storage.get("intents_root") and storage.get("intents_root"):
                    cfg_storage["intents_root"] = storage["intents_root"]

            core._save_config(current_cfg)

        except Exception as e:
            QMessageBox.critical(self, "Erreur de fusion",
                                 f"La fusion a échoué :\n{e}")
            return

        self._refresh_all()

        QMessageBox.information(
            self, "Import terminé",
            f"✅ Import réussi !\n\n"
            f"  +{added_inst} instance(s) ajoutée(s)\n"
            f"  +{added_int} intent(s) ajouté(s)\n\n"
            f"L'app a été rechargée."
        )

    def act_export_all(self):
        """Action pour exporter tous les projets en ZIP."""
        try:
            zip_path = core.export_all_to_zip()
            QMessageBox.information(
                self, "Export complet", 
                f"Tous les projets ont été exportés avec succès.\n\n"
                f"Fichier : {zip_path}\n\n"
                "L'export contient toutes les instances, intents et la configuration."
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'exporter :\n{e}")

    def act_customize_selection(self):
        """Action pour personnaliser la sélection."""
        if not self._need_sel():
            return
            
        dlg = CustomizeProjectDialog(str(self._sel_path), self._sel_kind, self)
        dlg.exec()
        self._refresh_all()
        # Rafraîchir le panneau si ouvert
        if (hasattr(self, "_project_panel") and
                self._right_stack.currentIndex() == 1 and self._sel_path):
            self._project_panel.show_project(
                str(self._sel_path), self._sel_kind,
                on_action=self._dispatch_action,
            )

    def act_encrypt_project(self):
        """Action pour chiffrer/déchiffrer un projet."""
        if not self._need_sel():
            return
            
        dlg = EncryptProjectDialog(str(self._sel_path), self._sel_kind, self)
        dlg.exec()
        self._refresh_all()

    def act_manage_categories(self):
        """Action pour gérer les catégories."""
        dlg = CategoriesDialog(self)
        if dlg.exec() == QDialog.Accepted:
            categories = dlg.get_categories()
            # Sauvegarder les catégories dans la configuration
            cfg = core._load_config()
            cfg["categories"] = categories
            core._save_config(cfg)
            QMessageBox.information(self, "Catégories", "Les catégories ont été mises à jour avec succès.")
            self._refresh_all()

    def act_manage_statuses(self):
        """Action pour gérer les statuts personnalisés."""
        dlg = StatusDialog(self)
        dlg.exec()
        # Les statuts sont sauvegardés automatiquement dans le dialogue
        self._refresh_all()

    def act_project_builder(self):
        """Action pour lancer ProjectsBuilder."""
        if not self._need_sel():
            return
        try:
            core.run_project_builder(self._sel_path)
            self._log(f"🔨 ProjectsBuilder lancé → {self._sel_path}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e))

    def act_open_with(self):
        """Ouvre le dossier avec une application choisie par l'utilisateur."""
        if not self._need_sel():
            return
            
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Choisir une application", "", 
            "Exécutables (*.exe);;Tous les fichiers (*.*)"
        )
        if not file_path:
            return
            
        try:
            import subprocess
            subprocess.Popen([file_path, str(self._sel_path)])
            self._log(f"📂 Dossier ouvert avec {Path(file_path).name}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'ouvrir l'application :\n{e}")

    def act_open_config(self):
        """Action pour ouvrir la configuration."""
        dlg = ConfigDialog(self)
        dlg.exec()
        self._reload_note_autosave_timer()

    def act_theme_settings(self):
        """Action pour les paramètres de thème."""
        dlg = ThemeSettingsDialog(self)
        dlg.exec()

    def act_manage_tokens(self):
        """Action pour gérer les tokens GitHub."""
        QMessageBox.information(
            self, "Gestion des tokens",
            "Fonctionnalité à venir dans une future version."
        )

    def act_open_docs(self):
        """Action pour ouvrir la documentation."""
        core.open_url_in_browser("https://github.com/yo-le-zz/voktora")

    def act_about(self):
        """Action pour afficher à propos."""
        QMessageBox.about(
            self,
            "À propos de Voktora",
            f"""<b>Voktora v{core.APP_VERSION}</b><br><br>
Project Instance Manager pour Windows<br><br>
Auteur : <a href='https://github.com/yo-le-zz'>yo-le-zz</a><br><br>
Gestionnaire de projets avec intégration GitHub,<br>
personnalisation avancée et chiffrement.<br><br>
© 2026 - Tous droits réservés"""
        )
