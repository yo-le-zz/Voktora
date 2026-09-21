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
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
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
    clone_dialog,
    create_dialog,
    diagnostic_dialog,
    git_dialog,
    github_dialog,
    github_login_dialog,
    import_dialog,
    push_dialog,
    storage_dialog,
    task_dialog,
    token_password_dialog,
    uninstall_dialog,
    workers,
)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Voktora — Project Manager")
        self.setAcceptDrops(True)   # glisser un dossier ou un .zip sur la fenêtre = importer
        self.setMinimumSize(1180, 720)
        
        # Appliquer le thème
        theme_manager.apply_theme_to_app(QApplication.instance())
        
        self._sel_path:   Path | None      = None
        self._worker:     workers.Worker | None    = None
        self._git_worker: workers.GitWorker | None = None
        self._delete_worker: workers.DeleteWorker | None = None
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.timeout.connect(self._auto_save_note)
        
        # Cache de performances pour la liste des projets
        self._projects_cache: list[dict] | None = None
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
        # Ctrl+N — Nouveau projet
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self.act_create)
        # Ctrl+I — Importer un dossier ou un ZIP
        QShortcut(QKeySequence("Ctrl+I"), self).activated.connect(self.act_import)
        # Ctrl+F — Focus recherche projets
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            self._show_project_switcher
        )
        # Escape — Effacer la recherche
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._clear_search)

    def _clear_search(self) -> None:
        self._browser.get_search_widget().clear()

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
        act_new      = QAction("📦 Nouveau projet", self)
        act_new.triggered.connect(self.act_create)
        act_import   = QAction("📥 Importer un dossier ou un ZIP...", self)
        act_import.triggered.connect(self.act_import)
        act_clone_repo = QAction("🐙 Cloner un dépôt GitHub...", self)
        act_clone_repo.triggered.connect(self.act_clone_repo)
        act_import_cfg = QAction("🔄 Importer config Meridian / Voktora...", self)
        act_import_cfg.setToolTip("Fusionne un config.json d'une ancienne version Meridian ou Voktora")
        act_import_cfg.triggered.connect(self.act_import_meridian_config)
        act_export   = QAction("📤 Exporter tout en ZIP...", self)
        act_export.triggered.connect(self.act_export_all)
        act_refresh  = QAction("↻ Actualiser", self)
        act_refresh.triggered.connect(self._refresh_all)
        act_quit     = QAction("✕ Quitter", self)
        act_quit.triggered.connect(self.close)
        
        menu_file.addAction(act_new)
        menu_file.addAction(act_import)
        menu_file.addAction(act_clone_repo)
        menu_file.addSeparator()
        menu_file.addAction(act_import_cfg)
        menu_file.addAction(act_export)
        menu_file.addSeparator()
        menu_file.addAction(act_refresh)
        menu_file.addSeparator()
        menu_file.addAction(act_quit)

        # Menu Git
        menu_git = menubar.addMenu("🐙 Git")
        act_clone    = QAction("📥 Cloner un dépôt...", self)
        act_clone.triggered.connect(self.act_clone_repo)
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
        act_gh_hub = QAction("🐙 Compte & organisations...", self)
        act_gh_hub.triggered.connect(self.act_github_hub)
        
        menu_gh.addAction(act_gh_login)
        menu_gh.addAction(act_gh_logout)
        menu_gh.addSeparator()
        menu_gh.addAction(act_gh_hub)

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
        self._browser.import_requested.connect(self.act_import)
        self._browser.clone_requested.connect(self.act_clone_repo)
        self._browser.manage_categories_requested.connect(self.act_manage_categories)
        self._browser.projects_modified.connect(self._on_projects_modified)
        self._browser.view_state_changed.connect(self._save_view_state)
        _cfg = core.get_app_config()
        self._browser.set_view_state(_cfg.get("browser_mode", "list"),
                                     _cfg.get("browser_group_by", core.DEFAULT_GROUP),
                                     _cfg.get("browser_sort", core.DEFAULT_SORT))
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

        lbl_s = QLabel("Project Manager")
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

        _stat_row("📁 Projets",    "_stat_projects")
        _stat_row("📂 Catégories", "_stat_categories")
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
            self._stat_projects.setText(str(len(core.list_projects())))
            self._stat_categories.setText(str(len(core.list_categories())))
        except Exception:
            self._stat_projects.setText("—")
            self._stat_categories.setText("—")

        try:
            self._stat_drives.setText(str(self.drive_combo.count()))
        except Exception:
            self._stat_drives.setText("—")

        try:
            from pathlib import Path as _P

            import dashboard as _dash
            cfg   = core._load_config()
            paths = [_P(e["path"]) for e in cfg.get("projects", [])]
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

    def _log(self, msg: str):
        # Déléguer au panneau projet si ouvert
        if hasattr(self, "_project_panel") and self._right_stack.currentIndex() == 1:
            self._project_panel.log(msg)

    def _need_sel(self) -> bool:
        if not self._sel_path:
            QMessageBox.warning(self, "Voktora",
                "Sélectionnez d'abord un projet.")
            return False
        return True

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(
            self, title, text, QMessageBox.Yes | QMessageBox.No
        ) == QMessageBox.Yes

    def _current_drive(self) -> str:
        return self.drive_combo.currentText()

    def _get_token_for_git(self) -> str:
        """
        Retourne le token le plus approprié pour une opération git.
        Priorité : PAT du projet > OAuth global.
        Demande le mot de passe si le PAT est protégé.
        """
        if not self._sel_path:
            return ""

        # Token PAT du projet depuis le vault
        token = core.get_project_token(self._sel_path)
        if token:
            return token

        # Token PAT du projet protégé
        if core.is_token_protected(self._sel_path):
            dlg = token_password_dialog.TokenPasswordDialog(mode="get", parent=self)
            if dlg.exec() == QDialog.Accepted:
                pwd   = dlg.get_password()
                token = core.get_project_token(self._sel_path, pwd)
                if not token:
                    QMessageBox.warning(self, "Voktora",
                        "Mot de passe incorrect — impossible de déchiffrer le token.")
                return token

        # Fallback : token OAuth global
        session = core.get_github_session()
        if session and session.get("token"):
            return session["token"]

        return ""

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

        self._project_panel.set_git_busy(True)

        self._git_worker = workers.GitWorker(fn, *args, **kwargs)
        self._git_worker.log_line.connect(self._log)
        self._git_worker.finished.connect(self._on_git_worker_finished)
        self._git_worker.start()

    def _on_git_worker_finished(self, success: bool) -> None:
        self._project_panel.set_git_busy(False)
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
        """Sauvegarde périodique de la note du projet affiché (si activée dans la config)."""
        if self._sel_path and self._right_stack.currentIndex() == 1:
            self._project_panel.autosave_note()

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
        self._projects_cache = None
        self._cache_timestamp = None

    def _get_cached_projects(self) -> list[dict]:
        """Retourne les projets depuis le cache ou les charge si nécessaire."""
        if not self._is_cache_valid() or self._projects_cache is None:
            self._projects_cache = list(core.list_projects())
            import time
            self._cache_timestamp = time.time()
        return self._projects_cache

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
        projects = self._get_cached_projects()
        n = len(projects)
        if hasattr(self, "_status_lbl"):
            self._set_status(f"{n} projet{'s' if n != 1 else ''}")
        self._browser.populate(projects)

    def _on_projects_modified(self) -> None:
        """Un classement (catégorie, ordre, statut) a changé : tout recharger."""
        self._invalidate_cache()
        self._refresh_all()

    def _on_drive_changed(self, _):
        pass

    def _refresh_project_panel(self) -> None:
        """Recharge le panneau projet s'il est affiché (après un changement de configuration)."""
        if self._sel_path and self._right_stack.currentIndex() == 1:
            self._project_panel.show_project(str(self._sel_path), on_action=self._dispatch_action)

    def _on_project_selected(self, path: str) -> None:
        """Appelé par ProjectBrowser quand l'utilisateur clique sur un projet."""
        self._sel_path = Path(path)
        self._project_panel.show_project(path, on_action=self._dispatch_action)
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
        if hasattr(self, "_status_lbl"):
            self._set_status("Pret")

    def _show_project_switcher(self) -> None:
        """Affiche le browser et met le focus sur la recherche."""
        self._right_stack.setCurrentIndex(0)
        self._browser.get_search_widget().setFocus()
        self._browser.get_search_widget().selectAll()

    def _dispatch_action(self, action: str, path: Path) -> None:
        """Pont entre ProjectPanel et les méthodes act_* de MainWindow."""
        self._sel_path = path
        dispatch = {
            "open_explorer":  self.act_open_explorer,
            "open_terminal":  self.act_open_terminal,
            "open_vscode":    self.act_open_vscode,
            "open_with":      self.act_open_with,
            "rename":         self.act_rename,
            "delete":         self.act_delete,
            "export":         self.act_export,
            "export_custom":  self.act_export_custom,
            "import_project": self.act_import,
            "clone_repo":     self.act_clone_repo,
            "run_builder":    self.act_run_builder,
            "git_init":       self.act_git_init,
            "git_configure":  self.act_git_configure,
            "git_status":     self.act_git_status,
            "git_pull":       self.act_git_pull,
            "git_push":       self.act_git_push,
            "git_log":        self.act_git_log,
            "git_checkout":   self.act_git_checkout,
            "git_commit_push": self.act_git_commit_push,
            "git_merge":      self.act_git_merge,
        }
        fn = dispatch.get(action)
        if fn:
            fn()

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
        self._refresh_project_panel()

    def act_github_logout(self) -> None:
        """Déconnecte le compte GitHub."""
        session = core.get_github_session()
        info    = core.get_github_account_info()

        login = (session.get("login") if session else None) or info.get("login") or "GitHub"

        if not self._confirm(
            "Déconnexion GitHub",
            f"Déconnecter le compte @{login} ?\n\n"
            "Le token OAuth sera supprimé de la configuration.\n"
            "Les tokens PAT spécifiques aux projets ne seront pas affectés.",
        ):
            return

        core.clear_github_account()
        self._log(f"🚪  Compte GitHub @{login} déconnecté.")
        self._update_github_account_card()
        self._refresh_project_panel()

    # ══════════════════════════════════════════════
    #  ACTIONS — Général
    # ══════════════════════════════════════════════

    def _after_project_added(self, path: Path, label: str) -> None:
        """Rafraîchit la liste, sélectionne le nouveau projet et l'annonce dans le journal."""
        self._log(f"{label}  →  <span style='color:#89dceb'>{path}</span>")
        self._invalidate_cache()
        self._refresh_all()
        self._browser.select(str(path))
        self._set_status(f"Projet ajouté : {Path(path).name}", 5000)

    def act_create(self, *_args) -> None:
        dlg = create_dialog.CreateDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            path = core.create_project(**dlg.get_data())
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e))
            return
        self._after_project_added(path, f"📦  <b>{path.name}</b> créé")

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
            new_path = core.rename_project(self._sel_path, new_name.strip())
            self._log(f"✏  Renommé : <b>{old_name}</b> → <b>{new_path.name}</b>")
            self._sel_path = new_path
            self._invalidate_cache()  # Invalider le cache pour refléter les changements
            self._refresh_lists()
            self._refresh_project_panel()
        except Exception as e:
            QMessageBox.critical(self, "Erreur renommage", str(e))

    def act_delete(self):
        if not self._need_sel():
            return
        path = self._sel_path
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Supprimer le projet")
        box.setText(f"Que faire de « {path.name} » ?")
        box.setInformativeText(
            f"{path}\n\n"
            "• Retirer de Voktora : le projet disparaît de la liste, ses fichiers restent sur le disque.\n"
            "• Supprimer le dossier : les fichiers sont effacés définitivement (irréversible)."
        )
        btn_forget = box.addButton("📤 Retirer de Voktora", QMessageBox.AcceptRole)
        btn_delete = box.addButton("🗑 Supprimer le dossier", QMessageBox.DestructiveRole)
        box.addButton("Annuler", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_forget:
            core.forget_project(path)
            self._log(f"📤  <b>{path.name}</b> retiré de Voktora (dossier conservé).")
            self._after_project_removed()
        elif clicked is btn_delete:
            if not self._confirm("Supprimer définitivement",
                                 f"Supprimer définitivement :\n\n{path}\n\nCette action est irréversible."):
                return
            done = task_dialog.run_task(
                self, "Suppression du projet",
                lambda ctx: core.delete_project(path, on_progress=ctx.progress, cancel=ctx.is_cancelled),
                headline=f"Suppression de {path.name}")
            if done.outcome == task_dialog.OUTCOME_ERROR:
                QMessageBox.critical(self, "Erreur suppression",
                                     f"Impossible de supprimer entièrement le dossier :\n{done.error}")
                self._log(f"<span style='color:#f38ba8;'>[ERREUR] Suppression échouée : {html.escape(done.error)}</span>")
            elif done.outcome == task_dialog.OUTCOME_OK:
                self._log(f"🗑  <b>{path.name}</b> supprimé.")
                self._after_project_removed()

    def _after_project_removed(self) -> None:
        self._sel_path = None
        self._invalidate_cache()
        self._refresh_all()
        self._show_welcome()

    def _run_export(self, job, title: str, headline: str, success_label: str) -> None:
        """Lance un export dans une fenêtre de progression (l'interface ne se fige pas)."""
        done = task_dialog.run_task(self, title, job, headline=headline)
        if done.outcome == task_dialog.OUTCOME_OK:
            self._log(f"💾  Exporté  →  <span style='color:#89dceb'>{done.result}</span>")
            QMessageBox.information(self, "Export réussi", f"{success_label} :\n{done.result}")
        elif done.outcome == task_dialog.OUTCOME_ERROR:
            QMessageBox.critical(self, "Erreur export", done.error)

    def act_export(self):
        if not self._need_sel():
            return
        folder = self._sel_path
        self._run_export(
            lambda ctx: core.export_to_zip(folder, None, on_progress=ctx.progress, cancel=ctx.is_cancelled),
            "Export du projet", f"Export de {folder.name}", "Archive sauvegardée")

    def act_export_custom(self):
        if not self._need_sel():
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Choisir le dossier de destination")
        if not out_dir:
            return
        folder = self._sel_path
        self._run_export(
            lambda ctx: core.export_to_zip(folder, Path(out_dir), on_progress=ctx.progress,
                                           cancel=ctx.is_cancelled),
            "Export du projet", f"Export de {folder.name}", "Archive créée")

    # ── Import / clone ───────────────────────────

    def act_import(self, *_args) -> None:
        """Importer un dossier ou une archive ZIP (dialogue avec progression)."""
        self._open_import_dialog()

    def _open_import_dialog(self, source_path: str = "", source_kind: str = import_dialog.SOURCE_FOLDER) -> None:
        dlg = import_dialog.ImportDialog(self._current_drive(), self, source_path, source_kind)
        if dlg.exec() == QDialog.Accepted and dlg.imported_path:
            self._after_project_added(dlg.imported_path, "📥  Import")

    def act_clone_repo(self, *_args) -> None:
        """Cloner un dépôt GitHub (liste de ses dépôts par organisation, ou URL)."""
        dlg = clone_dialog.CloneDialog(self._current_drive(), self)
        if dlg.exec() == QDialog.Accepted and dlg.cloned_path:
            self._after_project_added(dlg.cloned_path, "🐙  Cloné")

    @staticmethod
    def _dropped_sources(mime) -> list[tuple[str, str]]:
        """(chemin, type) des dossiers et archives ZIP d'un glisser-déposer externe."""
        found = []
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    local = url.toLocalFile()
                    kind = import_dialog.classify_path(local)
                    if kind:
                        found.append((local, kind))
        return found

    def dragEnterEvent(self, event) -> None:
        if self._dropped_sources(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        sources = self._dropped_sources(event.mimeData())
        if not sources:
            return
        event.acceptProposedAction()
        # Les dialogues sont ouverts après le retour du gestionnaire de dépôt,
        # un par un dans l'ordre : chacun peut être annulé séparément.
        QTimer.singleShot(0, lambda: [self._open_import_dialog(p, k) for p, k in sources])

    def _save_view_state(self, mode: str, group_by: str, sort: str) -> None:
        cfg = core.get_app_config()
        cfg.update(browser_mode=mode, browser_group_by=group_by, browser_sort=sort)
        core.set_app_config(cfg)

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
        current_url     = core.get_project_repo(self._sel_path)
        current_branch  = core.get_project_branch(self._sel_path)
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

        token_in_vault = core.get_project_token(self._sel_path)
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
            try:
                url = core.validate_clone_url(url)   # retire aussi d'éventuels identifiants de l'URL
            except ValueError as exc:
                QMessageBox.warning(self, "Voktora — Dépôt invalide", str(exc))
                return
            core.set_project_repo(self._sel_path, url)
            self._log(f"🔗  GitHub lié  →  {url}")

        core.set_project_branch(self._sel_path, branch)
        saved = core.get_project_branches(self._sel_path)
        if branch not in saved:
            core.set_project_branches(self._sel_path, [branch])
        self._log(f"🌿  Branche principale  →  <b>{branch}</b>")

        if token:
            if protect and token_password:
                core.set_project_token(self._sel_path, token, token_password)
                algo = "AES-256 (Fernet, PBKDF2-HMAC-SHA256)"
                self._log(f"🔐  Token PAT chiffré et sauvegardé  (algo : {algo})")
            elif not protect:
                core.set_project_token(self._sel_path, token, "")
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

        self._refresh_project_panel()

    def act_git_init(self):
        if not self._need_sel():
            return
        out = core.git_init(self._sel_path)
        self._log(f"⚙  git init : {html.escape(out)}")

    def act_git_push(self):
        if not self._need_sel():
            return
        url = core.get_project_repo(self._sel_path)
        if not url:
            QMessageBox.warning(self, "Voktora",
                "Aucun repo GitHub lié à ce projet.\nConfigurez GitHub d'abord.")
            return
        self._open_push_dialog(mode="initial")

    def act_git_commit_push(self):
        if not self._need_sel():
            return
        url = core.get_project_repo(self._sel_path)
        if not url:
            QMessageBox.warning(self, "Voktora", "Aucun repo GitHub lié à ce projet.")
            return
        self._open_push_dialog(mode="commit")

    def act_git_merge(self):
        if not self._need_sel():
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

        core.set_project_branches(self._sel_path, branches)

        url      = core.get_project_repo(self._sel_path)
        token    = self._get_token_for_git()

        # Log de la source du token utilisé
        pat_raw = core.get_project_token_raw(self._sel_path)
        session = core.get_github_session()
        if pat_raw:
            self._log("🔑  Authentification : token PAT du projet")
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
            url,
            branches,
            message=message,
            description=description,
            force=force,
            follow_tags=follow_tags,
            no_verify=no_verify,
            is_initial=(mode == "initial"),
            token=token,   # transmis par l'environnement de git : jamais dans l'URL du remote
        )

        self._refresh_project_panel()

    def act_git_pull(self):
        if not self._need_sel():
            return
        url = core.get_project_repo(self._sel_path)
        if not url:
            QMessageBox.warning(self, "Voktora", "Aucun repo GitHub lié à ce projet.")
            return
        branch = core.get_project_branch(self._sel_path)
        self._log(f"⬇  git pull → branche <b>{branch}</b>…")
        self._start_worker(core.git_pull, self._sel_path, branch, self._get_token_for_git())

    def act_git_status(self):
        if not self._need_sel():
            return
        self._start_worker(core.git_status, self._sel_path)   # peut être long sur un gros dépôt

    def act_git_log(self):
        if not self._need_sel():
            return
        self._start_worker(core.git_log, self._sel_path)

    def act_git_checkout(self):
        if not self._need_sel():
            return
        local_branches = core.git_list_local_branches(self._sel_path)
        current_branch = core.get_project_branch(self._sel_path)

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
        try:
            out = core.git_checkout(self._sel_path, branch)
        except ValueError as exc:
            QMessageBox.warning(self, "Voktora", str(exc))
            return
        self._log(f"🌿  git checkout <b>{branch}</b> : {html.escape(out)}")
        core.set_project_branch(self._sel_path, branch)
        self._refresh_project_panel()

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

    def act_import_meridian_config(self) -> None:
        """
        Importe un config.json provenant de l'ancienne version Meridian
        (ou d'une autre installation Voktora, ancien ou nouveau format) et
        fusionne les projets sans écraser les données existantes.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Importer une configuration Meridian / Voktora",
            "",
            "Fichiers JSON (*.json);;Tous les fichiers (*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, encoding="utf-8") as f:
                legacy_cfg = json.load(f)
            if not isinstance(legacy_cfg, dict):
                raise ValueError("la racine du fichier n'est pas un objet JSON")
        except Exception as e:
            QMessageBox.critical(self, "Erreur de lecture",
                                 f"Impossible de lire le fichier :\n{e}")
            return

        projects = core.extract_external_projects(legacy_cfg)
        if not projects:
            QMessageBox.warning(
                self, "Rien à importer",
                "Le fichier ne contient aucun projet ('projects', 'instances' ou 'intents').\n"
                "Vérifiez qu'il s'agit bien d'un config.json Meridian / Voktora."
            )
            return

        preview_lines = [f"  • {len(projects)} projet(s) :"]
        for e in projects[:5]:
            preview_lines.append(f"      - {e.get('name', '?')}  [{e.get('language') or '?'}]")
        if len(projects) > 5:
            preview_lines.append(f"      … +{len(projects) - 5} autres")
        categories = legacy_cfg.get("categories") or []
        if categories:
            preview_lines.append(f"  • {len(categories)} catégorie(s)")
        if legacy_cfg.get("custom_statuses"):
            preview_lines.append(f"  • {len(legacy_cfg['custom_statuses'])} statut(s) personnalisé(s)")

        msg = QMessageBox(self)
        msg.setWindowTitle("Confirmer l'import")
        msg.setIcon(QMessageBox.Question)
        msg.setText(
            f"<b>Fichier :</b> {html.escape(Path(file_path).name)}<br><br>"
            f"Contenu détecté :<br>"
            + "<br>".join(f"<code>{html.escape(ln)}</code>" for ln in preview_lines)
            + "<br><br>Les entrées déjà présentes (même chemin) seront <b>ignorées</b>.<br>"
              "Les nouvelles seront <b>ajoutées</b> sans rien supprimer."
        )
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.button(QMessageBox.Ok).setText("✅ Importer")
        msg.button(QMessageBox.Cancel).setText("Annuler")
        if msg.exec() != QMessageBox.Ok:
            return

        try:
            added = core.merge_external_config(legacy_cfg)
        except Exception as e:
            QMessageBox.critical(self, "Erreur de fusion",
                                 f"La fusion a échoué :\n{e}")
            return

        self._invalidate_cache()
        self._refresh_all()
        QMessageBox.information(
            self, "Import terminé",
            f"✅ Import réussi !\n\n"
            f"  +{added['projects']} projet(s) ajouté(s)\n"
            f"  +{added['categories']} catégorie(s) ajoutée(s)\n"
            f"  +{added['statuses']} statut(s) ajouté(s)"
        )

    def act_export_all(self):
        """Exporte tous les projets et la configuration (sans secrets) dans un ZIP."""
        self._run_export(
            lambda ctx: core.export_all_to_zip(on_progress=ctx.progress, cancel=ctx.is_cancelled),
            "Export complet", "Export de tous les projets",
            "Tous les projets et la configuration (sans compte GitHub ni tokens) ont été exportés")

    def act_customize_selection(self):
        """Action pour personnaliser la sélection."""
        if not self._need_sel():
            return
            
        dlg = CustomizeProjectDialog(str(self._sel_path), self)
        dlg.exec()
        self._invalidate_cache()
        self._refresh_all()
        self._refresh_project_panel()

    def act_encrypt_project(self):
        """Action pour chiffrer/déchiffrer un projet."""
        if not self._need_sel():
            return
            
        dlg = EncryptProjectDialog(str(self._sel_path), self)
        dlg.exec()
        self._refresh_all()

    def act_manage_categories(self, *_args) -> None:
        """Ouvre la gestion des catégories (création, couleur, ordre, classement GitHub)."""
        dlg = CategoriesDialog(self)
        dlg.exec()
        if dlg.has_changes():
            self._invalidate_cache()
            self._refresh_all()
            self._refresh_project_panel()

    def act_github_hub(self, *_args) -> None:
        """Compte GitHub, organisations et classement automatique des projets."""
        dlg = github_dialog.GitHubDialog(self)
        dlg.projects_changed.connect(self._on_projects_modified)
        dlg.exec()

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

    def act_open_docs(self):
        """Action pour ouvrir la documentation."""
        core.open_url_in_browser("https://github.com/yo-le-zz/voktora")

    def act_about(self):
        """Action pour afficher à propos."""
        QMessageBox.about(
            self,
            "À propos de Voktora",
            f"""<b>Voktora v{core.APP_VERSION}</b><br><br>
Project Manager pour Windows<br><br>
Auteur : <a href='https://github.com/yo-le-zz'>yo-le-zz</a><br><br>
Gestionnaire de projets avec intégration GitHub,<br>
personnalisation avancée et chiffrement.<br><br>
© 2026 - Tous droits réservés"""
        )
