"""
ui_project_panel.py — Panneau détaillé d'un projet Voktora
Nouveau panneau centré, plein écran, avec :
  • Header : icône personnalisable, nom, badges, bouton retour
  • 5 onglets : Actions / Git / Outils / Snapshots / Profils
  • Chaque onglet a 5 boutons max par groupe visuel

Le panneau est instancié une fois dans MainWindow et affiché via show_project().
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore    import Qt, Signal, QTimer
from PySide6.QtGui     import QColor, QFont, QIcon, QPixmap, QPainter
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

import core
import git as git_module
import profiles
import snapshots
import dashboard
import hooks as hooks_module
from ui_dialogs import (
    ProfilesDialog, SnapshotDialog, HooksDialog,
    VaultDialog, DashboardDialog,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color:#313244; margin:2px 0;")
    return f


def _group(title: str, *buttons: QPushButton) -> QGroupBox:
    """Crée un QGroupBox avec une rangée de boutons (max 5)."""
    grp = QGroupBox(title)
    row = QHBoxLayout(grp)
    row.setSpacing(8)
    for btn in buttons[:5]:
        row.addWidget(btn)
    row.addStretch()
    return grp


def _btn(label: str, obj_name: str = "", tooltip: str = "") -> QPushButton:
    b = QPushButton(label)
    if obj_name:
        b.setObjectName(obj_name)
    if tooltip:
        b.setToolTip(tooltip)
    b.setFixedHeight(32)
    return b


# ─────────────────────────────────────────────────────────────────────────────
# ProjectPanel
# ─────────────────────────────────────────────────────────────────────────────

class ProjectPanel(QWidget):
    """
    Panneau plein écran d'un projet.
    Signaux :
      back_requested      — l'utilisateur veut revenir à la liste
      switch_requested    — l'utilisateur veut choisir un autre projet
      project_modified    — une action a modifié le projet (refresh liste)
    """

    back_requested   = Signal()
    switch_requested = Signal()
    project_modified = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: Path | None = None
        self._kind: str         = "instance"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────────────
        self._header = self._build_header()
        root.addWidget(self._header)

        # ── Corps principal : tabs à gauche + log à droite ─────────────────
        splitter = QSplitter(Qt.Horizontal)

        self._tabs  = self._build_tabs()
        self._log   = self._build_log()

        splitter.addWidget(self._tabs)
        splitter.addWidget(self._log)
        splitter.setSizes([700, 300])
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(4)

        root.addWidget(splitter, stretch=1)

    # =========================================================================
    # Header
    # =========================================================================

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("projectPanelHeader")
        w.setStyleSheet(
            "#projectPanelHeader {"
            "  background:#1e1e2e;"
            "  border-bottom: 1px solid #313244;"
            "}"
        )
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(14)

        # ── Bouton retour ──
        btn_back = _btn("← Retour", "subtle")
        btn_back.setFixedWidth(90)
        btn_back.clicked.connect(self.back_requested)
        h.addWidget(btn_back)

        # ── Icône projet ──
        self._icon_lbl = QLabel()
        self._icon_lbl.setFixedSize(52, 52)
        self._icon_lbl.setStyleSheet(
            "border-radius:8px; background:#313244; border:1px solid #45475a;"
        )
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        self._icon_lbl.setCursor(Qt.PointingHandCursor)
        self._icon_lbl.setToolTip("Cliquer pour changer l'icône")
        self._icon_lbl.mousePressEvent = lambda e: self._change_icon()
        h.addWidget(self._icon_lbl)

        # ── Infos ──
        info = QVBoxLayout()
        info.setSpacing(2)

        self._name_lbl = QLabel("—")
        self._name_lbl.setStyleSheet(
            "font-size:18px; font-weight:700; color:#cdd6f4;"
        )
        info.addWidget(self._name_lbl)

        self._sub_lbl = QLabel("—")
        self._sub_lbl.setStyleSheet("font-size:12px; color:#6c7086;")
        info.addWidget(self._sub_lbl)

        h.addLayout(info, stretch=1)

        # ── Badges droite ──
        badges = QHBoxLayout()
        badges.setSpacing(8)

        self._badge_kind = QLabel()
        self._badge_kind.setStyleSheet(
            "background:#89b4fa; color:#1e1e2e; border-radius:4px;"
            " font-size:11px; font-weight:600; padding:2px 8px;"
        )
        badges.addWidget(self._badge_kind)

        self._badge_lang = QLabel()
        self._badge_lang.setStyleSheet(
            "background:#313244; color:#cdd6f4; border-radius:4px;"
            " font-size:11px; padding:2px 8px;"
        )
        badges.addWidget(self._badge_lang)

        self._badge_status = QLabel()
        self._badge_status.setStyleSheet(
            "background:#a6e3a1; color:#1e1e2e; border-radius:4px;"
            " font-size:11px; padding:2px 8px;"
        )
        badges.addWidget(self._badge_status)

        h.addLayout(badges)

        # ── Bouton choisir autre projet ──
        btn_switch = _btn("⇄ Autre projet", "subtle",
                          "Choisir un autre projet sans revenir à la liste")
        btn_switch.setFixedWidth(140)
        btn_switch.clicked.connect(self.switch_requested)
        h.addWidget(btn_switch)

        return w

    # =========================================================================
    # Onglets
    # =========================================================================

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_tab_actions(),   "⚡  Actions")
        tabs.addTab(self._build_tab_git(),       "🐙  Git")
        tabs.addTab(self._build_tab_tools(),     "🧰  Outils")
        tabs.addTab(self._build_tab_snapshots(), "📸  Snapshots")
        tabs.addTab(self._build_tab_details(),   "📌  Détails")
        return tabs

    # ── Onglet Actions ────────────────────────────────────────────────────────

    def _build_tab_actions(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)
        v.setContentsMargins(14, 14, 14, 14)

        # Groupe : Ouvrir
        self._btn_explorer  = _btn("🗂 Explorateur")
        self._btn_terminal  = _btn("⬛ Terminal")
        self._btn_vscode    = _btn("💙 VS Code", "teal")
        self._btn_open_with = _btn("📂 Ouvrir avec…", "subtle")
        v.addWidget(_group("Ouvrir",
            self._btn_explorer, self._btn_terminal,
            self._btn_vscode, self._btn_open_with))

        # Groupe : Note
        self._note_edit = QTextEdit()
        self._note_edit.setPlaceholderText("Notes, to-do, remarques…")
        self._note_edit.setMinimumHeight(80)
        self._note_edit.setMaximumHeight(140)

        self._btn_save_note = _btn("💾 Sauvegarder", "subtle")

        grp_note = QGroupBox("📝 Note")
        gn = QVBoxLayout(grp_note)
        gn.addWidget(self._note_edit)
        gn.addWidget(self._btn_save_note, alignment=Qt.AlignRight)
        v.addWidget(grp_note)

        # Groupe : Profils d'exécution
        self._btn_profiles  = _btn("⚙ Gérer les profils", "primary")
        self._btn_run_prof  = _btn("▶ Lancer profil par défaut", "success")
        v.addWidget(_group("⚡ Profils d'exécution",
            self._btn_profiles, self._btn_run_prof))

        # Groupe : Hooks
        self._btn_hooks = _btn("🪝 Gérer les hooks")
        v.addWidget(_group("🪝 Hooks", self._btn_hooks))

        # Groupe : Gestion
        self._btn_rename  = _btn("✏ Renommer", "subtle")
        self._btn_delete  = _btn("🗑 Supprimer définitivement", "danger")
        self._delete_prog = QProgressBar()
        self._delete_prog.setRange(0, 100)
        self._delete_prog.setVisible(False)

        grp_mgmt = QGroupBox("⚠ Gestion")
        gm = QVBoxLayout(grp_mgmt)
        row_mgmt = QHBoxLayout()
        row_mgmt.addWidget(self._btn_rename)
        row_mgmt.addWidget(self._btn_delete)
        row_mgmt.addStretch()
        gm.addLayout(row_mgmt)
        gm.addWidget(self._delete_prog)
        v.addWidget(grp_mgmt)

        v.addStretch()
        scroll.setWidget(w)
        return scroll

    # ── Onglet Git ────────────────────────────────────────────────────────────

    def _build_tab_git(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)
        v.setContentsMargins(14, 14, 14, 14)

        # Infos repo
        grp_info = QGroupBox("Dépôt")
        gi = QFormLayout(grp_info)
        self._lbl_repo   = QLabel("—")
        self._lbl_branch = QLabel("—")
        self._lbl_token  = QLabel("—")
        self._lbl_token.setStyleSheet("color:#6c7086; font-size:11px;")
        gi.addRow("Repo :",   self._lbl_repo)
        gi.addRow("Branche :", self._lbl_branch)
        gi.addRow("Token :",  self._lbl_token)
        v.addWidget(grp_info)

        # Groupe : Initialisation
        self._btn_git_init  = _btn("⚙ git init")
        self._btn_git_clone = _btn("📥 Clone")
        self._btn_git_cfg   = _btn("🔗 Configurer remote", "subtle")
        v.addWidget(_group("Initialisation",
            self._btn_git_init, self._btn_git_clone, self._btn_git_cfg))

        # Groupe : Quotidien
        self._btn_git_status  = _btn("📋 Status")
        self._btn_git_pull    = _btn("⬇ Pull")
        self._btn_git_push_i  = _btn("⬆ Push initial…")
        self._btn_git_log     = _btn("📜 Log")
        self._btn_git_co      = _btn("🌿 Checkout")
        v.addWidget(_group("Quotidien",
            self._btn_git_status, self._btn_git_pull,
            self._btn_git_push_i, self._btn_git_log, self._btn_git_co))

        # Groupe : Commit & Push
        self._btn_commit_push = _btn("✔ Commit & Push…", "success")
        self._btn_smart_msg   = _btn("🧠 Message auto", "subtle",
                                     "Génère un message Conventional Commits")
        self._btn_auto_push   = _btn("⚡ Auto-push", "subtle",
                                     "Push silencieux sans dialog")
        v.addWidget(_group("Commit & Push",
            self._btn_commit_push, self._btn_smart_msg, self._btn_auto_push))

        # Groupe : Merge
        self._btn_merge   = _btn("🔀 Merge")
        v.addWidget(_group("Merge", self._btn_merge))

        v.addStretch()
        scroll.setWidget(w)
        return scroll

    # ── Onglet Outils ─────────────────────────────────────────────────────────

    def _build_tab_tools(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)
        v.setContentsMargins(14, 14, 14, 14)

        # Groupe : Export / Import
        self._btn_export_auto   = _btn("💾 Exporter .zip (auto)")
        self._btn_export_custom = _btn("💾 Exporter .zip (choisir dossier)", "subtle")
        self._btn_import_inst   = _btn("📂 Importer instance .zip")
        self._btn_import_int    = _btn("📂 Importer intent .zip")
        v.addWidget(_group("Export / Import",
            self._btn_export_auto, self._btn_export_custom,
            self._btn_import_inst, self._btn_import_int))

        # Groupe : Vault
        self._btn_vault = _btn("🔐 Vault — secrets", "subtle")
        v.addWidget(_group("Vault", self._btn_vault))

        # Groupe : Dashboard
        self._btn_dashboard = _btn("📊 Dashboard — santé & usage")
        v.addWidget(_group("Dashboard", self._btn_dashboard))

        # Groupe : Builder externe
        self._btn_builder = _btn("🔨 Project Builder", "success")
        v.addWidget(_group("Builder", self._btn_builder))

        # Groupe : Plugins
        self._plugin_grp_layout = QVBoxLayout()
        grp_plugins = QGroupBox("🧩 Plugins")
        grp_plugins.setLayout(self._plugin_grp_layout)
        v.addWidget(grp_plugins)

        v.addStretch()
        scroll.setWidget(w)
        return scroll

    # ── Onglet Snapshots ──────────────────────────────────────────────────────

    def _build_tab_snapshots(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)
        v.setContentsMargins(14, 14, 14, 14)

        desc = QLabel(
            "Les snapshots capturent l'état complet du projet (fichiers + config).\n"
            "Vous pouvez comparer deux snapshots pour voir les différences."
        )
        desc.setStyleSheet("color:#a6adc8; font-size:12px;")
        desc.setWordWrap(True)
        v.addWidget(desc)

        self._btn_snapshot_manage = _btn("📸 Gérer les snapshots", "primary")
        self._btn_snapshot_create = _btn("📸 Créer snapshot rapide", "subtle")
        row = QHBoxLayout()
        row.addWidget(self._btn_snapshot_manage)
        row.addWidget(self._btn_snapshot_create)
        row.addStretch()
        v.addWidget(QWidget())   # spacer
        v.addLayout(row)
        v.addStretch()
        return w

    # ── Onglet Détails ────────────────────────────────────────────────────────

    def _build_tab_details(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 14, 14, 14)

        grp = QGroupBox("Informations du projet")
        form = QFormLayout(grp)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(16)

        def _info_lbl() -> QLabel:
            lbl = QLabel("—")
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lbl.setWordWrap(True)
            return lbl

        self._det_type     = _info_lbl()
        self._det_status   = _info_lbl()
        self._det_lang     = _info_lbl()
        self._det_cat      = _info_lbl()
        self._det_repo     = _info_lbl()
        self._det_branch   = _info_lbl()
        self._det_token_s  = _info_lbl()
        self._det_created  = _info_lbl()
        self._det_path     = _info_lbl()
        self._det_path.setStyleSheet("font-family:Consolas,'DejaVu Sans Mono',monospace; font-size:11px;")

        for label, widget in [
            ("Type :",          self._det_type),
            ("Statut :",        self._det_status),
            ("Langage :",       self._det_lang),
            ("Catégorie :",     self._det_cat),
            ("Repo Git :",      self._det_repo),
            ("Branche :",       self._det_branch),
            ("Source token :",  self._det_token_s),
            ("Créé le :",       self._det_created),
            ("Chemin :",        self._det_path),
        ]:
            form.addRow(label, widget)

        v.addWidget(grp)
        v.addStretch()
        scroll.setWidget(w)
        return scroll

    # ── Log ───────────────────────────────────────────────────────────────────

    def _build_log(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        lbl = QLabel("Journal")
        lbl.setObjectName("sectionLbl")
        v.addWidget(lbl)

        self._log_area = QTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setStyleSheet(
            "font-family:Consolas,'DejaVu Sans Mono',monospace; font-size:11px;"
        )
        v.addWidget(self._log_area, stretch=1)

        btn_clear = QPushButton("Effacer")
        btn_clear.setObjectName("subtle")
        btn_clear.setFixedWidth(80)
        btn_clear.clicked.connect(self._log_area.clear)
        v.addWidget(btn_clear, alignment=Qt.AlignRight)

        return w

    # =========================================================================
    # API publique
    # =========================================================================

    def show_project(self, path: str, kind: str,
                     on_action: "callable | None" = None) -> None:
        """
        Charge un projet dans le panneau.
        `on_action` est un callback(action_name, path, kind) fourni par MainWindow
        pour déléguer les actions Git/FS sans dupliquer la logique.
        """
        self._path     = Path(path)
        self._kind     = kind
        self._on_action = on_action

        self._refresh_header()
        self._refresh_details()
        self._wire_buttons()
        self._refresh_plugin_buttons()

    def log(self, msg: str) -> None:
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_area.append(
            f'<span style="color:#6c7086">[{ts}]</span>  {msg}'
        )
        sb = self._log_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    # =========================================================================
    # Refresh
    # =========================================================================

    def _refresh_header(self) -> None:
        entry = self._get_entry()
        name  = entry.get("name", self._path.name) if entry else self._path.name
        lang  = (entry.get("language") or
                 core.guess_project_language(self._path) if entry else "")
        em    = entry.get("emoji", "") if entry else ""

        self._name_lbl.setText(name)
        self._sub_lbl.setText(str(self._path))

        # Icône
        icon_p = entry.get("icon_path", "") if entry else ""
        self._render_icon(em, icon_p, entry.get("color","#313244") if entry else "#313244", name)

        # Badges
        self._badge_kind.setText(self._kind.upper())
        self._badge_kind.setStyleSheet(
            f"background:{'#89b4fa' if self._kind=='instance' else '#cba6f7'};"
            " color:#1e1e2e; border-radius:4px; font-size:11px;"
            " font-weight:600; padding:2px 8px;"
        )
        self._badge_lang.setText(lang or "—")
        self._badge_lang.setVisible(bool(lang))

        # Statut
        status = ""
        if entry:
            sid = entry.get("status", "")
            so  = core.get_project_status_by_id(sid)
            status = so.name if so else ""
        self._badge_status.setText(status)
        self._badge_status.setVisible(bool(status))

    def _render_icon(self, emoji: str, icon_path: str, color: str, name: str) -> None:
        from ui_project_view import _make_emoji_pixmap
        size = 48
        if icon_path and Path(icon_path).is_file():
            pix = QPixmap(icon_path).scaled(
                size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        elif emoji:
            pix = _make_emoji_pixmap(emoji, size)
        else:
            pix = QPixmap(size, size)
            pix.fill(QColor(color))
            painter = QPainter(pix)
            font = QFont(); font.setPixelSize(22); font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#cdd6f4"))
            painter.drawText(pix.rect(), Qt.AlignCenter, name[0].upper())
            painter.end()
        self._icon_lbl.setPixmap(pix)

    def _refresh_details(self) -> None:
        if not self._path:
            return
        entry = self._get_entry()

        # Note
        if self._kind == "instance":
            note = core.get_instance_note(self._path)
        else:
            note = core.get_intent_note(self._path) if hasattr(core, "get_intent_note") else ""
        self._note_edit.setPlainText(note or "")

        # Infos git
        if self._kind == "instance":
            repo     = core.get_instance_repo(self._path)
            branches = core.get_instance_branches(self._path)
            self._lbl_repo.setText(repo or "(non lié)")
            self._lbl_branch.setText(", ".join(branches) if branches else "—")
            session = core.get_github_session()
            pat_raw = core.get_instance_token_raw(self._path)
            if pat_raw:
                token_src = "Token PAT spécifique"
            elif session and session.get("token"):
                token_src = f"OAuth @{session.get('login','')}"
            else:
                token_src = "Aucun token"
            self._lbl_token.setText(token_src)

        # Détails
        lang  = (entry.get("language") or core.guess_project_language(self._path)) if entry else ""
        cat   = entry.get("category", "—") if entry else "—"
        repo  = core.get_instance_repo(self._path) if self._kind == "instance" else "—"
        brs   = core.get_instance_branches(self._path) if self._kind == "instance" else []
        crd   = entry.get("created", "—") if entry else "—"

        sid    = entry.get("status", "") if entry else ""
        so     = core.get_project_status_by_id(sid)
        status = so.name if so else "—"

        self._det_type.setText(self._kind.capitalize())
        self._det_status.setText(status)
        self._det_lang.setText(lang or "—")
        self._det_cat.setText(cat or "—")
        self._det_repo.setText(repo or "—")
        self._det_branch.setText(brs[0] if brs else "—")
        self._det_token_s.setText(self._lbl_token.text() if self._kind == "instance" else "—")
        self._det_created.setText(crd)
        self._det_path.setText(str(self._path))

    def _refresh_plugin_buttons(self) -> None:
        import plugins
        # Clear previous plugin buttons
        while self._plugin_grp_layout.count():
            item = self._plugin_grp_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        all_btns = plugins.all_buttons()
        if not all_btns:
            lbl = QLabel("Aucun plugin chargé — ajoutez un .py dans data/plugins/")
            lbl.setStyleSheet("color:#6c7086; font-size:11px;")
            self._plugin_grp_layout.addWidget(lbl)
            return

        row = QHBoxLayout()
        for i, (info, btn_info) in enumerate(all_btns[:5]):
            b = QPushButton(btn_info.label)
            b.setToolTip(btn_info.tooltip or f"Plugin : {info.name}")
            import plugins as _p
            from plugins import PluginContext
            handler = btn_info.handler
            path    = self._path
            b.clicked.connect(
                lambda _checked, h=handler, p=path:
                h(PluginContext(project_path=p, log_cb=self.log))
            )
            row.addWidget(b)
        row.addStretch()
        self._plugin_grp_layout.addLayout(row)

    # =========================================================================
    # Wiring
    # =========================================================================

    def _wire_buttons(self) -> None:
        # Déconnecter tous les signaux avant de reconnecter (évite les doublons)
        _all_btns = [
            self._btn_explorer, self._btn_terminal, self._btn_vscode,
            self._btn_open_with, self._btn_save_note, self._btn_rename,
            self._btn_delete, self._btn_profiles, self._btn_run_prof,
            self._btn_hooks, self._btn_git_init, self._btn_git_clone,
            self._btn_git_cfg, self._btn_git_status, self._btn_git_pull,
            self._btn_git_push_i, self._btn_git_log, self._btn_git_co,
            self._btn_commit_push, self._btn_merge, self._btn_smart_msg,
            self._btn_auto_push, self._btn_export_auto, self._btn_export_custom,
            self._btn_import_inst, self._btn_import_int, self._btn_vault,
            self._btn_dashboard, self._btn_builder,
            self._btn_snapshot_manage, self._btn_snapshot_create,
        ]
        for b in _all_btns:
            try:
                b.clicked.disconnect()
            except RuntimeError:
                pass  # pas encore connecté

        def act(name):
            def _slot(*_):
                if self._on_action:
                    self._on_action(name, self._path, self._kind)
            return _slot

        # Actions
        self._btn_explorer.clicked.connect(act("open_explorer"))
        self._btn_terminal.clicked.connect(act("open_terminal"))
        self._btn_vscode.clicked.connect(act("open_vscode"))
        self._btn_open_with.clicked.connect(act("open_with"))
        self._btn_save_note.clicked.connect(self._save_note)
        self._btn_rename.clicked.connect(act("rename"))
        self._btn_delete.clicked.connect(act("delete"))
        self._btn_profiles.clicked.connect(self._open_profiles)
        self._btn_run_prof.clicked.connect(self._run_default_profile)
        self._btn_hooks.clicked.connect(self._open_hooks)

        # Git
        self._btn_git_init.clicked.connect(act("git_init"))
        self._btn_git_clone.clicked.connect(act("git_clone"))
        self._btn_git_cfg.clicked.connect(act("git_configure"))
        self._btn_git_status.clicked.connect(act("git_status"))
        self._btn_git_pull.clicked.connect(act("git_pull"))
        self._btn_git_push_i.clicked.connect(act("git_push"))
        self._btn_git_log.clicked.connect(act("git_log"))
        self._btn_git_co.clicked.connect(act("git_checkout"))
        self._btn_commit_push.clicked.connect(act("git_commit_push"))
        self._btn_merge.clicked.connect(act("git_merge"))
        self._btn_smart_msg.clicked.connect(self._show_smart_message)
        self._btn_auto_push.clicked.connect(self._auto_push)

        # Outils
        self._btn_export_auto.clicked.connect(act("export"))
        self._btn_export_custom.clicked.connect(act("export_custom"))
        self._btn_import_inst.clicked.connect(lambda: act("import_instance")())
        self._btn_import_int.clicked.connect(lambda: act("import_intent")())
        self._btn_vault.clicked.connect(lambda: VaultDialog(self).exec())
        self._btn_dashboard.clicked.connect(lambda: DashboardDialog(self).exec())
        self._btn_builder.clicked.connect(act("run_builder"))

        # Snapshots
        self._btn_snapshot_manage.clicked.connect(self._open_snapshots)
        self._btn_snapshot_create.clicked.connect(self._quick_snapshot)

    # =========================================================================
    # Slots locaux
    # =========================================================================

    def _save_note(self) -> None:
        if not self._path:
            return
        note = self._note_edit.toPlainText()
        if self._kind == "instance":
            core.set_instance_note(self._path, note)
        else:
            if hasattr(core, "set_intent_note"):
                core.set_intent_note(self._path, note)
        self.log("Note sauvegardée.")

    def _change_icon(self) -> None:
        if not self._path:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir une icône",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.ico *.svg *.webp)",
        )
        if not path:
            return
        # Sauvegarder dans la config de l'entrée
        cfg = core._load_config()
        entry = core._find_entry(cfg, f"{self._kind}s", self._path)
        if entry:
            entry["icon_path"] = path
            core._save_config(cfg)
        # Rafraîchir l'icône dans le header
        entry2 = self._get_entry()
        em     = entry2.get("emoji", "") if entry2 else ""
        name   = entry2.get("name", self._path.name) if entry2 else self._path.name
        self._render_icon(em, path, entry2.get("color","#313244") if entry2 else "#313244", name)
        self.project_modified.emit()
        self.log(f"Icône mise à jour : {path}")

    def _open_profiles(self) -> None:
        if self._path:
            ProfilesDialog(self._path, self).exec()

    def _run_default_profile(self) -> None:
        if not self._path:
            return
        pr = profiles.get_default_profile(self._path)
        if not pr:
            QMessageBox.information(self, "Profils",
                "Aucun profil par défaut. Créez-en un dans Gérer les profils.")
            return
        proc = profiles.launch(self._path, pr, log_cb=self.log)
        if proc:
            self.log(f"Profil '{pr.name}' lancé (PID {proc.pid})")

    def _open_hooks(self) -> None:
        HooksDialog(self).exec()

    def _open_snapshots(self) -> None:
        if self._path:
            SnapshotDialog(self._path, self).exec()

    def _quick_snapshot(self) -> None:
        if not self._path:
            return
        try:
            out = snapshots.create(self._path, "rapide")
            self.log(f"Snapshot créé : {out.name} ({out.stat().st_size // 1024} KB)")
        except Exception as e:
            self.log(f"Erreur snapshot : {e}")

    def _show_smart_message(self) -> None:
        if not self._path:
            return
        msg = git_module.smart_commit_message(self._path)
        QMessageBox.information(self, "Message de commit suggéré", msg)
        self.log(f"Message suggéré : {msg}")

    def _auto_push(self) -> None:
        if not self._path:
            return
        token = core.get_effective_token(self._path)
        ok = git_module.push(self._path, log_cb=self.log, token=token)
        self.log("Push OK" if ok else "Push échoué (voir terminal)")

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_entry(self) -> dict | None:
        if not self._path:
            return None
        cfg = core._load_config()
        return core._find_entry(cfg, f"{self._kind}s", self._path)
