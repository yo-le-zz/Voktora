"""
Voktora — Project Instance Manager
Voktora v1.0.1
ui_main.py : Interface graphique PySide6
Version : 1.0.1
"""

from __future__ import annotations

import html
import json
import sys
import threading
from pathlib import Path
from datetime import datetime

from PySide6.QtCore    import Qt, QThread, Signal, QTimer
from PySide6.QtGui     import QColor, QFont, QIcon, QPixmap, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QButtonGroup, QCheckBox, QComboBox,
    QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter,
    QStackedWidget, QStatusBar, QTabWidget, QTextEdit, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QFrame,
    QInputDialog, QProgressBar,
)
from PySide6.QtCore import QUrl

import core
import git as git_module
import plugins
import hooks as hooks_module
import theme_manager
from ui_dialogs import (
    ThemeSettingsDialog, CustomizeProjectDialog, EncryptProjectDialog,
    ConfigDialog, CategoriesDialog, StatusDialog,
    VaultDialog, ProfilesDialog, HooksDialog, SnapshotDialog,
    DashboardDialog, PluginsDialog, MasterPasswordSetupDialog,
    MigrateDialog,
)
from ui_project_view import ProjectBrowser
from ui_project_panel import ProjectPanel


# ══════════════════════════════════════════════════════
#  STYLESHEET
# ══════════════════════════════════════════════════════

STYLE = """
* { font-family: 'Segoe UI', 'Noto Sans', 'DejaVu Sans', Ubuntu, sans-serif; font-size: 13px; }

QMainWindow, QDialog, QWidget { background-color: #1e1e2e; color: #cdd6f4; }

/* ── Sidebar ── */
#sidebar { background-color: #181825; border-right: 1px solid #313244; }

/* ── Labels ── */
#appTitle   { font-size: 19px; font-weight: 700; color: #89b4fa; letter-spacing: 1px; }
#appSub     { font-size: 11px; color: #6c7086; }
#sectionLbl { font-size: 11px; color: #6c7086; letter-spacing: 1px; }

#pathLabel {
    font-family: Consolas, 'DejaVu Sans Mono', 'Courier New', monospace;
    font-size: 12px;
    color: #89dceb;
    background-color: #11111b;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 8px 12px;
}
#kindTag {
    font-size: 11px; font-weight: 700; color: #1e1e2e;
    background-color: #a6e3a1; border-radius: 4px; padding: 2px 8px;
}
#kindTagIntent {
    font-size: 11px; font-weight: 700; color: #1e1e2e;
    background-color: #cba6f7; border-radius: 4px; padding: 2px 8px;
}

#selTitle { font-size: 15px; font-weight: 700; color: #cdd6f4; }
#repoLine { font-size: 11px; color: #a6adc8; font-family: Consolas, 'DejaVu Sans Mono', monospace; }
#noSel    { font-size: 14px; color: #45475a; }

/* ── GitHub Account Card ── */
#githubCard {
    background-color: #11111b;
    border: 1px solid #313244;
    border-radius: 8px;
    padding: 8px;
}
#githubCardConnected {
    background-color: #11111b;
    border: 1px solid #a6e3a1;
    border-radius: 8px;
    padding: 8px;
}
#githubLogin {
    font-size: 12px; font-weight: 700; color: #a6e3a1;
}
#githubLoginName {
    font-size: 11px; color: #6c7086;
}

/* ── Buttons ── */
QPushButton {
    background-color: #313244; color: #cdd6f4;
    border: none; border-radius: 6px;
    padding: 7px 14px; text-align: left;
}
QPushButton:hover    { background-color: #45475a; }
QPushButton:pressed  { background-color: #585b70; }
QPushButton:disabled { background-color: #1e1e2e; color: #45475a; }

QPushButton#primary {
    background-color: #89b4fa; color: #1e1e2e;
    font-weight: 700; text-align: center;
}
QPushButton#primary:hover  { background-color: #b4d0fb; }
QPushButton#primary:pressed{ background-color: #74a9f9; }

QPushButton#danger  { background-color: #f38ba8; color: #1e1e2e; font-weight: 700; }
QPushButton#danger:hover  { background-color: #f5a3b8; }

QPushButton#success { background-color: #a6e3a1; color: #1e1e2e; font-weight: 700; }
QPushButton#success:hover { background-color: #c0edbb; }

QPushButton#warn    { background-color: #fab387; color: #1e1e2e; font-weight: 700; }
QPushButton#warn:hover    { background-color: #fcc9a8; }

QPushButton#subtle  {
    background-color: transparent; color: #6c7086;
    font-size: 11px; padding: 4px 8px;
}
QPushButton#subtle:hover  { color: #cdd6f4; background-color: #313244; }

QPushButton#teal    { background-color: #94e2d5; color: #1e1e2e; font-weight: 700; }
QPushButton#teal:hover    { background-color: #b0ece5; }

QPushButton#github  {
    background-color: #30363d; color: #f0f6fc;
    font-weight: 700; text-align: center;
    border: 1px solid #484f58;
}
QPushButton#github:hover  { background-color: #484f58; }

/* ── Inputs ── */
QLineEdit, QComboBox {
    background-color: #181825; border: 1px solid #313244;
    border-radius: 6px; padding: 6px 10px; color: #cdd6f4;
}
QLineEdit:focus, QComboBox:focus { border-color: #89b4fa; }

QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background-color: #181825; border: 1px solid #313244;
    selection-background-color: #313244; color: #cdd6f4;
}

/* ── List ── */
QListWidget {
    background-color: #181825; border: 1px solid #313244;
    border-radius: 8px; padding: 4px; outline: none;
}
QListWidget::item { padding: 9px 12px; border-radius: 6px; margin: 1px; }
QListWidget::item:selected { background-color: #89b4fa; color: #1e1e2e; }
QListWidget::item:hover:!selected { background-color: #313244; }

/* ── GroupBox ── */
QGroupBox {
    border: 1px solid #313244; border-radius: 8px;
    margin-top: 14px; padding: 10px 10px 8px 10px;
    font-weight: 600; color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 12px;
    padding: 0 6px; color: #89b4fa;
}

/* ── Tabs ── */
QTabWidget::pane {
    border: 1px solid #313244; border-radius: 8px;
    background: #1e1e2e; margin-top: -1px;
}
QTabBar::tab {
    background: #181825; color: #6c7086;
    border: 1px solid #313244; border-bottom: none;
    border-radius: 6px 6px 0 0;
    padding: 7px 20px; margin-right: 2px;
}
QTabBar::tab:selected { background: #1e1e2e; color: #89b4fa; border-bottom: 1px solid #1e1e2e; }
QTabBar::tab:hover:!selected { background: #313244; color: #cdd6f4; }

/* ── TextEdit (log) ── */
QTextEdit {
    background-color: #11111b; border: 1px solid #313244;
    border-radius: 8px; color: #a6e3a1;
    font-family: Consolas, 'DejaVu Sans Mono', 'Courier New', monospace;
    font-size: 12px; padding: 6px;
}
QTextEdit#noteEdit {
    color: #cdd6f4; font-family: 'Segoe UI', sans-serif; font-size: 13px;
}

/* ── Scrollbar ── */
QScrollBar:vertical {
    background: #1e1e2e; width: 8px; border-radius: 4px; margin: 0;
}
QScrollBar::handle:vertical { background: #45475a; border-radius: 4px; min-height: 20px; }
QScrollBar::handle:vertical:hover { background: #585b70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* ── Separator ── */
QFrame[frameShape="4"], QFrame[frameShape="5"] { color: #313244; }

/* ── CheckBox ── */
QCheckBox { color: #cdd6f4; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #45475a; border-radius: 4px; background: #181825;
}
QCheckBox::indicator:checked { background-color: #89b4fa; border-color: #89b4fa; }

/* ── Splitter ── */
QSplitter::handle { 
    background-color: #313244; 
    width: 3px; 
    border-radius: 2px; 
}
QSplitter::handle:hover { 
    background-color: #585b70; 
}
QSplitter::handle:pressed { 
    background-color: #89b4fa; 
}

/* ── Progress ── */
QProgressBar {
    background-color: #181825; border: 1px solid #313244;
    border-radius: 4px; height: 6px; text-align: center;
}
QProgressBar::chunk { background-color: #89b4fa; border-radius: 4px; }

/* ── Search box ── */
QLineEdit#searchBox {
    background-color: #11111b;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 5px 10px;
    color: #cdd6f4;
    font-size: 12px;
}
QLineEdit#searchBox:focus { border-color: #89b4fa; }

/* ── Project grid cards ── */
QFrame#projectCard {
    background: #181825;
    border: 2px solid #313244;
    border-radius: 10px;
}
QFrame#projectCard:hover { border-color: #585b70; background: #1e1e2e; }

/* ── Project panel header ── */
#projectPanelHeader { background: #1e1e2e; }

/* ── Switch buttons list/grid ── */
QToolButton {
    background: #313244; border: 1px solid #45475a;
    border-radius: 5px; color: #cdd6f4; font-size: 14px;
}
QToolButton:checked { background: #89b4fa; color: #1e1e2e; border-color: #89b4fa; }
QToolButton:hover:!checked { background: #45475a; }

/* ── StatusBar ── */
QStatusBar {
    background-color: #181825;
    color: #6c7086;
    border-top: 1px solid #313244;
    font-size: 11px;
    padding: 2px 8px;
}
QStatusBar::item { border: none; }
"""


# ══════════════════════════════════════════════════════
#  WORKER THREADS
# ══════════════════════════════════════════════════════

class Worker(QThread):
    """Worker générique — émet le résultat final en une seule fois."""
    finished = Signal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self._fn, self._args = fn, args

    def run(self):
        try:
            self.finished.emit(self._fn(*self._args))
        except Exception as e:
            self.finished.emit(f"[ERREUR] {e}")


class GitWorker(QThread):
    """Worker spécialisé pour les opérations git avancées."""
    log_line = Signal(str)
    finished = Signal(bool)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs

    def run(self):
        try:
            self._fn(*self._args, on_step=self._on_step, **self._kwargs)
            self.finished.emit(True)
        except Exception as e:
            safe = html.escape(str(e))
            self.log_line.emit(
                f'<span style="color:#f38ba8; font-weight:600">[ERREUR] {safe}</span>'
            )
            self.finished.emit(False)

    def _on_step(self, cmd: str, output: str) -> None:
        self.log_line.emit(
            f'<span style="color:#89b4fa; font-family:Consolas,monospace">'
            f'$ git {html.escape(cmd)}</span>'
        )
        if output.strip():
            self.log_line.emit(
                f'<pre style="color:#cdd6f4; margin:1px 0 6px 12px; '
                f'white-space:pre-wrap; font-size:11px">'
                f'{html.escape(output.strip())}</pre>'
            )


class DeleteWorker(QThread):
    """Worker non bloquant pour la suppression de gros dossiers."""
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, path: Path):
        super().__init__()
        self._path = path

    def run(self):
        try:
            if not self._path.exists():
                self.finished.emit(True, "")
                return

            paths = [p for p in self._path.rglob("*")]
            total = len(paths) + 1
            removed = 0

            for child in sorted(paths, key=lambda p: p.is_dir(), reverse=True):
                try:
                    if child.is_file() or child.is_symlink():
                        child.unlink()
                    elif child.is_dir():
                        child.rmdir()
                except Exception:
                    pass
                removed += 1
                self.progress.emit(int(removed / total * 100))

            try:
                self._path.rmdir()
            except Exception:
                pass
            removed += 1
            self.progress.emit(100)
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class UpdateCheckWorker(QThread):
    """Vérifie en arrière-plan si une mise à jour Voktora est disponible."""
    result = Signal(bool, str, str)   # available, latest_version, url

    def run(self):
        available, latest, url = core.check_for_update()
        self.result.emit(available, latest, url)


class OAuthPollWorker(QThread):
    """
    Worker qui sonde l'API GitHub toutes les N secondes jusqu'à obtenir le token.
    Émet success(token) ou error(message).
    """
    success = Signal(str)   # token OAuth en clair
    error   = Signal(str)   # message d'erreur

    def __init__(self, pending: core.DeviceFlowPending):
        super().__init__()
        self._pending    = pending
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        core.poll_device_flow(
            self._pending,
            on_success = lambda token: self.success.emit(token),
            on_error   = lambda msg:   self.error.emit(msg),
            stop_event = self._stop_event,
        )


# ══════════════════════════════════════════════════════
#  HELPERS COMMUNS
# ══════════════════════════════════════════════════════

def _make_sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    return f


# ══════════════════════════════════════════════════════
#  DIALOG — CONNEXION GITHUB OAUTH (Device Flow) — v1.0.1
# ══════════════════════════════════════════════════════

class GitHubLoginDialog(QDialog):
    """
    Dialog de connexion GitHub.

    Modes :
      • OAuth App  — Device Flow (rétrocompat) : Client ID requis
      • GitHub App — Installation token (JWT RS256) : App ID + clé privée PEM + Installation ID

    Si l'utilisateur a déjà une config OAuth, on lui propose de migrer vers GitHub App.
    Signal connected(login, name, token) émis en cas de succès.
    """

    connected = Signal(str, str, str)   # login, name, token

    # ── Pages du QStackedWidget interne ──────────
    _PAGE_METHOD   = 0   # choix OAuth / GitHub App
    _PAGE_OAUTH    = 1   # config OAuth App
    _PAGE_APP      = 2   # config GitHub App
    _PAGE_CODE     = 3   # affichage du device code
    _PAGE_WAIT     = 4   # attente OAuth
    _PAGE_MIGRATE  = 5   # proposition de migration

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("🔑  Connexion GitHub — Voktora")
        self.setFixedWidth(540)
        self.setModal(True)

        self._poll_worker: OAuthPollWorker | None = None
        self._pending:     core.DeviceFlowPending | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(12)

        # ── En-tête ──
        title = QLabel("🐙  Connexion à GitHub")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self._sub_lbl = QLabel()
        self._sub_lbl.setAlignment(Qt.AlignCenter)
        self._sub_lbl.setWordWrap(True)
        self._sub_lbl.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self._sub_lbl)

        layout.addWidget(_make_sep())

        # ── Stack ──
        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._build_page_method()
        self._build_page_oauth()
        self._build_page_app()
        self._build_page_code()
        self._build_page_wait()
        self._build_page_migrate()

        layout.addWidget(_make_sep())

        # ── Barre de boutons ──
        btns = QHBoxLayout()
        self._btn_back = QPushButton("◀  Retour")
        self._btn_back.clicked.connect(self._go_back)
        self._btn_cancel = QPushButton("Annuler")
        self._btn_cancel.clicked.connect(self._on_cancel)
        btns.addWidget(self._btn_back)
        btns.addStretch()
        btns.addWidget(self._btn_cancel)
        layout.addLayout(btns)

        # ── État initial ──
        self._history: list[int] = []
        self._goto(self._PAGE_METHOD)

    # ── Navigation ───────────────────────────────────────────────────────────

    def _goto(self, page: int) -> None:
        if self._stack.currentIndex() != page:
            self._history.append(self._stack.currentIndex())
        self._stack.setCurrentIndex(page)
        self._btn_back.setVisible(len(self._history) > 0 and page != self._PAGE_WAIT)

        subtitles = {
            self._PAGE_METHOD:  "Choisissez la méthode d'authentification.",
            self._PAGE_OAUTH:   "OAuth App — Device Flow (méthode classique).",
            self._PAGE_APP:     "GitHub App — Token d'installation sécurisé (recommandé).",
            self._PAGE_CODE:    "Copiez le code ci-dessous et autorisez l'accès sur GitHub.",
            self._PAGE_WAIT:    "En attente de l'autorisation GitHub…",
            self._PAGE_MIGRATE: "Migration vers GitHub App disponible.",
        }
        self._sub_lbl.setText(subtitles.get(page, ""))
        self.adjustSize()

    def _go_back(self) -> None:
        if self._history:
            self._goto(self._history.pop())
            if self._history:
                self._history.pop()

    # ── Page 0 : choix de méthode ────────────────────────────────────────────

    def _build_page_method(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)

        current = core.get_auth_method()
        has_oauth = core.is_github_client_id_configured()
        has_app   = core.is_github_app_configured()

        # Carte GitHub App (recommandée)
        card_app = self._make_method_card(
            "⭐  GitHub App",
            "Méthode recommandée. Utilise une clé privée RSA et un token d'installation.\n• Permissions granulaires par repo\n• Token renouvelé automatiquement (1h)\n• Aucun compte personnel exposé",
            active=(current == core.AUTH_METHOD_GITHUB_APP),
            configured=has_app,
        )
        btn_app = QPushButton("Configurer / Utiliser GitHub App  →")
        btn_app.setObjectName("primary")
        btn_app.clicked.connect(self._open_app_config)
        card_app.layout().addWidget(btn_app)
        v.addWidget(card_app)

        # Carte OAuth App
        card_oauth = self._make_method_card(
            "OAuth App — Device Flow",
            "Méthode classique. Nécessite un Client ID d'une OAuth App GitHub.\n• Accès au compte personnel\n• Simple à configurer",
            active=(current == core.AUTH_METHOD_OAUTH),
            configured=has_oauth,
        )
        btn_oauth = QPushButton("Configurer / Utiliser OAuth App  →")
        btn_oauth.clicked.connect(lambda: self._goto(self._PAGE_OAUTH))
        card_oauth.layout().addWidget(btn_oauth)
        v.addWidget(card_oauth)

        # Bannière de migration si OAuth configuré sans GitHub App
        if has_oauth and not has_app:
            banner = QLabel(
                "💡  Vous utilisez OAuth App. Migrez vers GitHub App pour plus de sécurité."
            )
            banner.setWordWrap(True)
            banner.setStyleSheet(
                "background:#1e1e2e; border:1px solid #89b4fa; border-radius:6px;"
                " color:#89b4fa; padding:8px; font-size:11px;"
            )
            btn_migrate = QPushButton("Voir comment migrer  →")
            btn_migrate.setStyleSheet("font-size:11px; padding:4px 10px;")
            btn_migrate.clicked.connect(lambda: self._goto(self._PAGE_MIGRATE))
            v.addWidget(banner)
            v.addWidget(btn_migrate)

        self._stack.addWidget(w)

    def _make_method_card(self, title: str, desc: str,
                          active: bool, configured: bool) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background:#{'1e1e2e' if active else '11111b'};"
            f" border:1px solid #{'89b4fa' if active else '313244'};"
            " border-radius:8px; padding:12px;"
        )
        v = QVBoxLayout(card)
        v.setSpacing(6)

        h = QHBoxLayout()
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-weight:bold; font-size:13px; color:#cdd6f4;")
        h.addWidget(lbl_title)
        h.addStretch()
        if active:
            badge = QLabel("● Actif")
            badge.setStyleSheet("color:#a6e3a1; font-size:11px;")
            h.addWidget(badge)
        elif configured:
            badge = QLabel("✓ Configuré")
            badge.setStyleSheet("color:#6c7086; font-size:11px;")
            h.addWidget(badge)
        v.addLayout(h)

        lbl_desc = QLabel(desc)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color:#a6adc8; font-size:11px; line-height:1.5;")
        v.addWidget(lbl_desc)
        return card

    # ── Page 1 : OAuth App ───────────────────────────────────────────────────

    def _build_page_oauth(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)

        lbl = QLabel("Client ID de votre OAuth App GitHub :")
        lbl.setStyleSheet("color:#cdd6f4; font-weight:bold;")
        v.addWidget(lbl)

        self._oauth_client_id = QLineEdit()
        self._oauth_client_id.setPlaceholderText("Iv1.xxxxxxxxxxxxxxxx  ou  20-char Oauth2 client ID")
        self._oauth_client_id.setText(core.get_github_client_id())
        self._oauth_client_id.setStyleSheet(
            "background:#313244; border:1px solid #45475a; border-radius:6px;"
            " padding:10px; color:#cdd6f4; font-size:13px;"
            " QLineEdit:focus { border:1px solid #89b4fa; }"
        )
        v.addWidget(self._oauth_client_id)

        hint = QLabel(
            "Créez une OAuth App sur github.com/settings/applications/new\n→ cochez \"Device authorization flow\" → copiez le Client ID."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6c7086; font-size:11px;")
        v.addWidget(hint)

        row = QHBoxLayout()
        btn_save = QPushButton("💾  Sauvegarder")
        btn_save.clicked.connect(self._save_oauth_client_id)
        btn_connect = QPushButton("🔑  Connecter avec GitHub")
        btn_connect.setObjectName("primary")
        btn_connect.clicked.connect(self._start_oauth)
        row.addWidget(btn_save)
        row.addStretch()
        row.addWidget(btn_connect)
        v.addLayout(row)

        self._stack.addWidget(w)

    def _save_oauth_client_id(self) -> None:
        cid = self._oauth_client_id.text().strip()
        if len(cid) < 10:
            QMessageBox.warning(self, "Erreur", "Client ID trop court.")
            return
        core.set_github_client_id(cid)
        core.set_auth_method(core.AUTH_METHOD_OAUTH)
        QMessageBox.information(self, "Sauvegardé", "Client ID OAuth sauvegardé.")

    # ── Page 2 : GitHub App ──────────────────────────────────────────────────

    def _build_page_app(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(8)

        def _row(label: str, placeholder: str, password: bool = False) -> QLineEdit:
            lbl = QLabel(label)
            lbl.setStyleSheet("color:#cdd6f4; font-weight:bold; font-size:12px;")
            v.addWidget(lbl)
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            if password:
                edit.setEchoMode(QLineEdit.Password)
            edit.setStyleSheet(
                "background:#313244; border:1px solid #45475a; border-radius:6px;"
                " padding:8px; color:#cdd6f4; font-size:12px;"
            )
            v.addWidget(edit)
            return edit

        self._app_id_edit      = _row("App ID :", "123456")
        self._install_id_edit  = _row("Installation ID :", "12345678")

        lbl_key = QLabel("Clé privée PEM :")
        lbl_key.setStyleSheet("color:#cdd6f4; font-weight:bold; font-size:12px;")
        v.addWidget(lbl_key)

        self._pem_edit = QTextEdit()
        self._pem_edit.setPlaceholderText("-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----")
        self._pem_edit.setFixedHeight(90)
        self._pem_edit.setStyleSheet(
            "background:#11111b; border:1px solid #45475a; border-radius:6px;"
            " padding:8px; color:#cdd6f4; font-family:Consolas,'DejaVu Sans Mono',monospace;"
            " font-size:11px;"
        )
        v.addWidget(self._pem_edit)

        self._app_protect_chk = QCheckBox("🔐  Chiffrer la clé privée avec un mot de passe")
        self._app_protect_chk.setStyleSheet("color:#a6adc8; font-size:12px;")
        v.addWidget(self._app_protect_chk)

        hint = QLabel(
            "Créez une GitHub App sur github.com/settings/apps/new\n→ générez une clé privée → installez-la sur votre compte / orga\n→ copiez l'App ID et l'Installation ID (URL de l'installation)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6c7086; font-size:11px;")
        v.addWidget(hint)

        # Pré-remplir si déjà configuré
        cfg = core.get_github_app_config()
        if cfg["app_id"]:
            self._app_id_edit.setText(cfg["app_id"])
        if cfg["installation_id"]:
            self._install_id_edit.setText(cfg["installation_id"])

        row = QHBoxLayout()
        btn_save = QPushButton("💾  Sauvegarder & Connecter")
        btn_save.setObjectName("primary")
        btn_save.setFixedHeight(38)
        btn_save.clicked.connect(self._save_github_app)
        row.addStretch()
        row.addWidget(btn_save)
        v.addLayout(row)

        self._stack.addWidget(w)

    def _open_app_config(self) -> None:
        # Pré-remplir les champs depuis la config existante
        cfg = core.get_github_app_config()
        if cfg["app_id"]:
            self._app_id_edit.setText(cfg["app_id"])
        if cfg["installation_id"]:
            self._install_id_edit.setText(cfg["installation_id"])
        self._goto(self._PAGE_APP)

    def _save_github_app(self) -> None:
        app_id      = self._app_id_edit.text().strip()
        install_id  = self._install_id_edit.text().strip()
        pem         = self._pem_edit.toPlainText().strip()

        if not app_id or not install_id:
            QMessageBox.warning(self, "Erreur", "App ID et Installation ID sont requis.")
            return
        if not pem:
            # Autoriser la sauvegarde sans clé si déjà configurée (maj partielle)
            cfg = core.get_github_app_config()
            if not cfg["private_key"]:
                QMessageBox.warning(self, "Erreur", "La clé privée PEM est requise.")
                return
            pem = None  # conserver la clé existante

        password = ""
        if self._app_protect_chk.isChecked():
            password, ok = QInputDialog.getText(
                self, "Mot de passe", "Mot de passe pour chiffrer la clé privée :",
                QLineEdit.Password
            )
            if not ok or not password:
                return

        try:
            if pem:
                core.set_github_app_config(app_id, pem, install_id, password)
            else:
                # Mise à jour partielle : conserver la clé existante
                cfg = core.get_github_app_config()
                existing_key = cfg["private_key"]
                core.set_github_app_config(app_id, existing_key, install_id, password)

            # Test : obtenir un token
            token = core.get_github_app_token(password)
            user  = core.fetch_github_app_user(token)

            login = user.get("login", "github-app")
            name  = user.get("name", "GitHub App")

            core.save_github_account(token, user, password)
            core.set_auth_method(core.AUTH_METHOD_GITHUB_APP)
            self.connected.emit(login, name, token)
            QMessageBox.information(
                self, "✅ GitHub App connectée",
                f"GitHub App configurée avec succès.\n\n{name}\n\nLe token d'installation sera renouvelé automatiquement."
            )
            self.accept()
        except core.OAuthError as exc:
            QMessageBox.critical(self, "Erreur GitHub App", str(exc))

    # ── Page 3 : Device Code ─────────────────────────────────────────────────

    def _build_page_code(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)

        lbl_instr = QLabel("Entrez ce code sur GitHub :")
        lbl_instr.setAlignment(Qt.AlignCenter)
        lbl_instr.setStyleSheet("color:#a6adc8; font-size:12px;")
        v.addWidget(lbl_instr)

        self._lbl_code = QLabel("••••-••••")
        self._lbl_code.setAlignment(Qt.AlignCenter)
        self._lbl_code.setStyleSheet(
            "font-size:32px; font-weight:700; color:#89b4fa;"
            " letter-spacing:6px; font-family:Consolas,'DejaVu Sans Mono',monospace;"
            " background:#11111b; border:1px solid #313244; border-radius:8px; padding:12px;"
        )
        self._lbl_code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self._lbl_code)

        btn_gh = QPushButton("🌐  Ouvrir GitHub dans le navigateur")
        btn_gh.setObjectName("github")
        btn_gh.setFixedHeight(38)
        btn_gh.clicked.connect(self._open_github)
        v.addWidget(btn_gh)

        hint = QLabel("💡  Copiez le code, collez-le sur GitHub, autorisez l'accès.")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color:#6c7086; font-size:11px;")
        v.addWidget(hint)

        self._stack.addWidget(w)

    # ── Page 4 : Attente OAuth ────────────────────────────────────────────────

    def _build_page_wait(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)

        self._lbl_code_wait = QLabel("••••-••••")
        self._lbl_code_wait.setAlignment(Qt.AlignCenter)
        self._lbl_code_wait.setStyleSheet(
            "font-size:28px; font-weight:700; color:#89b4fa;"
            " letter-spacing:6px; font-family:Consolas,'DejaVu Sans Mono',monospace;"
            " background:#11111b; border:1px solid #313244; border-radius:8px; padding:10px;"
        )
        self._lbl_code_wait.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self._lbl_code_wait)

        self._lbl_wait = QLabel("⏳  En attente de l'autorisation GitHub…")
        self._lbl_wait.setAlignment(Qt.AlignCenter)
        self._lbl_wait.setStyleSheet("color:#fab387; font-size:13px;")
        v.addWidget(self._lbl_wait)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        v.addWidget(self._progress)

        hint = QLabel("Validez le code sur GitHub. Cette fenêtre se fermera automatiquement.")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color:#6c7086; font-size:11px;")
        v.addWidget(hint)

        self._stack.addWidget(w)

    # ── Page 5 : Migration OAuth → GitHub App ────────────────────────────────

    def _build_page_migrate(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)

        title = QLabel("🔄  Migrer vers GitHub App")
        title.setStyleSheet("font-weight:bold; font-size:14px; color:#cdd6f4;")
        v.addWidget(title)

        steps_text = (
            "La migration ne supprime pas votre OAuth App — vous pouvez revenir à tout moment.<br><br>"
            "<b>Étapes :</b><br>"
            "1. Allez sur <b>github.com/settings/apps/new</b><br>"
            "2. Remplissez :<br>"
            "&nbsp;&nbsp;&nbsp;• <b>GitHub App name</b> : Voktora (ou votre nom)<br>"
            "&nbsp;&nbsp;&nbsp;• <b>Homepage URL</b> : https://github.com/yo-le-zz/Voktora<br>"
            "&nbsp;&nbsp;&nbsp;• Décochez <i>Webhook active</i><br>"
            "&nbsp;&nbsp;&nbsp;• Permissions → Contents : Read &amp; Write<br>"
            "3. Cliquez <b>Create GitHub App</b> → notez l'<b>App ID</b><br>"
            "4. Générez une <b>Private key</b> (bouton en bas de la page)<br>"
            "5. Installez l'app sur votre compte ou orga → notez l'<b>Installation ID</b><br>"
            "&nbsp;&nbsp;&nbsp;(visible dans l'URL : github.com/settings/installations/<b>XXXXXXXX</b>)<br>"
            "6. Revenez ici et configurez GitHub App avec ces informations."
        )
        steps = QLabel(steps_text)
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        steps.setStyleSheet("color:#a6adc8; font-size:12px; line-height:1.6;")
        v.addWidget(steps)

        btn_configure = QPushButton("▶  Configurer GitHub App maintenant")
        btn_configure.setObjectName("primary")
        btn_configure.clicked.connect(self._open_app_config)
        v.addWidget(btn_configure)

        btn_keep = QPushButton("Garder OAuth App pour l'instant")
        btn_keep.setStyleSheet("color:#6c7086; font-size:11px;")
        btn_keep.clicked.connect(lambda: self._goto(self._PAGE_METHOD))
        v.addWidget(btn_keep)

        self._stack.addWidget(w)

    # ── OAuth flow ────────────────────────────────────────────────────────────

    def _start_oauth(self) -> None:
        cid = self._oauth_client_id.text().strip()
        if cid:
            core.set_github_client_id(cid)
        if not core.is_github_client_id_configured():
            QMessageBox.warning(self, "Erreur", "Entrez et sauvegardez un Client ID d'abord.")
            return
        try:
            pending = core.start_device_flow()
        except core.OAuthError as exc:
            QMessageBox.critical(self, "Erreur OAuth", str(exc))
            return

        self._pending = pending
        self._lbl_code.setText(pending.user_code)
        self._lbl_code_wait.setText(pending.user_code)
        self._goto(self._PAGE_CODE)

        self._poll_worker = OAuthPollWorker(pending)
        self._poll_worker.success.connect(self._on_oauth_success)
        self._poll_worker.error.connect(self._on_oauth_error)
        self._poll_worker.start()

        QTimer.singleShot(3000, lambda: (
            self._goto(self._PAGE_WAIT) if self._poll_worker else None
        ))

    def _open_github(self) -> None:
        if self._pending:
            core.open_url_in_browser(self._pending.verification_uri)
            self._goto(self._PAGE_WAIT)

    def _on_oauth_success(self, token: str) -> None:
        self._poll_worker = None
        try:
            user_info = core.fetch_github_user(token)
        except core.OAuthError as exc:
            self._on_oauth_error(str(exc))
            return

        login = user_info.get("login", "")
        name  = user_info.get("name") or login

        reply = QMessageBox.question(
            self, "🔐 Sécuriser le token ?",
            f"Compte connecté : <b>{login}</b><br><br>"
            "Voulez-vous chiffrer ce token avec un mot de passe ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        password = ""
        if reply == QMessageBox.Yes:
            password, ok = QInputDialog.getText(
                self, "Mot de passe", "Mot de passe :", QLineEdit.Password
            )
            if not ok or not password:
                return

        core.set_auth_method(core.AUTH_METHOD_OAUTH)
        core.save_github_account(token, user_info, password)
        self.connected.emit(login, name, token)
        self.accept()

    def _on_oauth_error(self, msg: str) -> None:
        self._poll_worker = None
        QMessageBox.critical(self, "Erreur OAuth", msg)
        self._goto(self._PAGE_OAUTH)

    def _on_cancel(self) -> None:
        if self._poll_worker:
            self._poll_worker.stop_event.set()
            self._poll_worker = None
        self.reject()


class TokenPasswordDialog(QDialog):
    def __init__(self, mode: str = "get", parent: QWidget | None = None):
        super().__init__(parent)
        assert mode in ("set", "get")
        self._mode = mode
        self.setWindowTitle("🔐  Protection token — Voktora")
        self.setFixedWidth(440)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        if mode == "set":
            title = QLabel("🔐  Définir un mot de passe de protection")
            desc  = QLabel(
                "Le token PAT sera chiffré avec ce mot de passe\n"
                "via une dérivation <b>Whirlpool + XOR</b>.\n\n"
                "⚠  Sans ce mot de passe, le token ne pourra pas être\n"
                "utilisé pour les opérations Git."
            )
        else:
            title = QLabel("🔐  Entrez le mot de passe du token")
            desc  = QLabel(
                "Ce token est protégé par mot de passe.\n"
                "Entrez votre mot de passe pour le déverrouiller."
            )

        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a6adc8; font-size: 12px;")

        layout.addWidget(title)
        layout.addWidget(_make_sep())
        layout.addWidget(desc)
        layout.addWidget(QLabel("Mot de passe :"))

        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        self.pwd_edit.setPlaceholderText("Votre mot de passe…")
        layout.addWidget(self.pwd_edit)

        if mode == "set":
            layout.addWidget(QLabel("Confirmer le mot de passe :"))
            self.pwd_confirm = QLineEdit()
            self.pwd_confirm.setEchoMode(QLineEdit.Password)
            self.pwd_confirm.setPlaceholderText("Confirmation…")
            layout.addWidget(self.pwd_confirm)
        else:
            self.pwd_confirm = None

        btn_show = QPushButton("👁  Afficher / Masquer")
        btn_show.setObjectName("subtle")
        btn_show.clicked.connect(self._toggle_visibility)
        layout.addWidget(btn_show)

        layout.addWidget(_make_sep())

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("✔  Valider")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._validate)
        btns.addWidget(btn_cancel)
        btns.addStretch()
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def _toggle_visibility(self):
        mode = (QLineEdit.Normal if self.pwd_edit.echoMode() == QLineEdit.Password
                else QLineEdit.Password)
        self.pwd_edit.setEchoMode(mode)
        if self.pwd_confirm:
            self.pwd_confirm.setEchoMode(mode)

    def _validate(self):
        pwd = self.pwd_edit.text()
        if not pwd:
            QMessageBox.warning(self, "Voktora", "Le mot de passe ne peut pas être vide.")
            return
        if self._mode == "set" and self.pwd_confirm:
            if pwd != self.pwd_confirm.text():
                QMessageBox.warning(self, "Voktora", "Les mots de passe ne correspondent pas.")
                return
        self.accept()

    def get_password(self) -> str:
        return self.pwd_edit.text()


# ══════════════════════════════════════════════════════
#  DIALOG PUSH AVANCÉ
# ══════════════════════════════════════════════════════

class PushDialog(QDialog):
    def __init__(
        self,
        instance_path: Path,
        mode: str = "commit",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._path = instance_path
        self._mode = mode

        title_str = "Push Initial" if mode == "initial" else "Commit & Push"
        self.setWindowTitle(f"{title_str} — Voktora")
        self.setMinimumWidth(520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)

        lbl_title = QLabel(
            f"{'🚀  Push Initial' if mode == 'initial' else '✔  Commit & Push'}"
        )
        lbl_title.setObjectName("appTitle")
        lbl_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_title)
        layout.addWidget(_make_sep())

        layout.addWidget(QLabel("Message de commit :"))
        self.msg_edit = QLineEdit()
        if mode == "initial":
            self.msg_edit.setText("Initial commit — Voktora")
        else:
            self.msg_edit.setPlaceholderText(
                "Titre du commit (laissez vide pour un message automatique)"
            )
        layout.addWidget(self.msg_edit)

        lbl_desc = QLabel("Description / corps du commit  (optionnel) :")
        lbl_desc.setObjectName("sectionLbl")
        layout.addWidget(lbl_desc)
        self.desc_edit = QTextEdit()
        self.desc_edit.setObjectName("noteEdit")
        self.desc_edit.setMaximumHeight(72)
        self.desc_edit.setPlaceholderText(
            "Explication détaillée, liste de changements, lien vers issue…"
        )
        layout.addWidget(self.desc_edit)
        layout.addWidget(_make_sep())

        lbl_br = QLabel("Branches cibles  (cochez celles où pusher) :")
        layout.addWidget(lbl_br)

        self.branch_list = QListWidget()
        self.branch_list.setMaximumHeight(110)
        saved = core.get_instance_branches(instance_path)
        for br in saved:
            self._add_branch_item(br, checked=True)
        layout.addWidget(self.branch_list)

        add_row = QHBoxLayout()
        self.new_branch_edit = QLineEdit()
        self.new_branch_edit.setPlaceholderText("Nouvelle branche…  ex: release/v2")
        self.new_branch_edit.returnPressed.connect(self._add_branch)
        btn_add = QPushButton("＋  Ajouter")
        btn_add.setFixedWidth(96)
        btn_add.clicked.connect(self._add_branch)
        btn_del = QPushButton("✕  Retirer")
        btn_del.setObjectName("subtle")
        btn_del.setFixedWidth(88)
        btn_del.clicked.connect(self._remove_selected_branch)
        add_row.addWidget(self.new_branch_edit)
        add_row.addWidget(btn_add)
        add_row.addWidget(btn_del)
        layout.addLayout(add_row)

        hint_br = QLabel("💡  Cochez plusieurs branches pour pousser en parallèle séquentiel.")
        hint_br.setObjectName("sectionLbl")
        layout.addWidget(hint_br)
        layout.addWidget(_make_sep())

        grp_opts = QGroupBox("⚙  Options de push")
        opts_v = QVBoxLayout(grp_opts)
        opts_v.setSpacing(6)

        self.chk_force = QCheckBox("--force  ⚠  Écraser l'historique distant (push forcé)")
        self.chk_force.setStyleSheet("color: #f38ba8;")
        if mode == "initial":
            self.chk_force.setChecked(True)

        self.chk_follow_tags = QCheckBox("--follow-tags  Inclure les tags annotés lors du push")
        self.chk_no_verify   = QCheckBox("--no-verify  Ignorer les hooks pre-push (ex : linters)")
        self.chk_no_verify.setStyleSheet("color: #fab387;")

        opts_v.addWidget(self.chk_force)
        opts_v.addWidget(self.chk_follow_tags)
        opts_v.addWidget(self.chk_no_verify)
        layout.addWidget(grp_opts)

        layout.addWidget(_make_sep())
        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        icon = "🚀" if mode == "initial" else "✔"
        self.btn_ok = QPushButton(f"{icon}  Lancer le push")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.clicked.connect(self._validate)
        btns.addWidget(btn_cancel)
        btns.addStretch()
        btns.addWidget(self.btn_ok)
        layout.addLayout(btns)

    def _add_branch_item(self, name: str, checked: bool = True) -> None:
        for i in range(self.branch_list.count()):
            if self.branch_list.item(i).text() == name:
                return
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.branch_list.addItem(item)

    def _add_branch(self) -> None:
        name = self.new_branch_edit.text().strip()
        if name:
            self._add_branch_item(name, checked=True)
            self.new_branch_edit.clear()

    def _remove_selected_branch(self) -> None:
        row = self.branch_list.currentRow()
        if row >= 0:
            self.branch_list.takeItem(row)

    def get_selected_branches(self) -> list[str]:
        return [
            self.branch_list.item(i).text()
            for i in range(self.branch_list.count())
            if self.branch_list.item(i).checkState() == Qt.Checked
        ]

    def _validate(self) -> None:
        if not self.get_selected_branches():
            QMessageBox.warning(self, "Voktora",
                "Cochez au moins une branche cible avant de lancer le push.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "message":     self.msg_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "branches":    self.get_selected_branches(),
            "force":       self.chk_force.isChecked(),
            "follow_tags": self.chk_follow_tags.isChecked(),
            "no_verify":   self.chk_no_verify.isChecked(),
        }


# ══════════════════════════════════════════════════════
#  DIALOGS PRINCIPAUX
# ══════════════════════════════════════════════════════

class CreateDialog(QDialog):
    def __init__(self, kind: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._kind = kind
        label = "Instance" if kind == "instance" else "Intent"
        self.setWindowTitle(f"Créer une {label} — Voktora")
        self.setFixedWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel(f"{'📦' if kind == 'instance' else '🧩'}  Créer une {label}")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(_make_sep())

        layout.addWidget(QLabel("Nom :"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(
            f"ex: {'MonProjet' if kind == 'instance' else 'SearchIntent'}"
        )
        layout.addWidget(self.name_edit)

        storage = core.get_storage_config()
        custom  = (storage.get("instances_root") if kind == "instance"
                   else storage.get("intents_root"))

        self.drive_combo = QComboBox()
        self._lbl_drive  = QLabel("Disque cible :")

        if custom:
            self._lbl_drive.setText(
                f"Dossier personnalisé : <span style='color:#89dceb'>{custom}</span>"
            )
            self._lbl_drive.setTextFormat(Qt.RichText)
            self.drive_combo.setVisible(False)
        else:
            drives = core.get_available_drives()
            if drives:
                self.drive_combo.addItems(drives)
            else:
                self.drive_combo.addItem("(aucun disque externe détecté)")
                self.drive_combo.setEnabled(False)

        layout.addWidget(self._lbl_drive)
        if not custom:
            layout.addWidget(self.drive_combo)

        self.preview = QLabel()
        self.preview.setObjectName("pathLabel")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        self.name_edit.textChanged.connect(self._update_preview)
        if not custom:
            self.drive_combo.currentTextChanged.connect(self._update_preview)
        self._update_preview()

        layout.addWidget(_make_sep())

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("✔  Créer")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._validate)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def _update_preview(self):
        name    = self.name_edit.text().strip() or "<nom>"
        storage = core.get_storage_config()
        custom  = (storage.get("instances_root") if self._kind == "instance"
                   else storage.get("intents_root"))
        if custom:
            self.preview.setText(str(Path(custom) / name))
        else:
            drive  = self.drive_combo.currentText()
            subdir = core.INSTANCES_DIR if self._kind == "instance" else core.INTENTS_DIR
            self.preview.setText(f"{drive}\\{core.CONTAINER_NAME}\\{subdir}\\{name}\\")

    def _validate(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Voktora", "Le nom ne peut pas être vide.")
            return
        try:
            core.validate_name(name)
        except ValueError as e:
            QMessageBox.warning(self, "Voktora — Nom invalide", str(e))
            return
        self.accept()

    def get_data(self) -> tuple[str, str]:
        return self.drive_combo.currentText(), self.name_edit.text().strip()


# ══════════════════════════════════════════════════════
#  DIALOG — EMPLACEMENT DE STOCKAGE (v1.0.1)
# ══════════════════════════════════════════════════════

class StorageDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("⚙  Emplacement de stockage — Voktora")
        self.setFixedWidth(580)
        self.setModal(True)

        storage = core.get_storage_config()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("⚙  Emplacement de stockage")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        hint = QLabel(
            "Par défaut, instances et intents sont créés dans\n"
            "<code>{Disque}\\Voktora\\Instances\\</code> et "
            "<code>{Disque}\\Voktora\\Intents\\</code>.\n\n"
            "Vous pouvez définir ici des chemins fixes, indépendants du disque sélectionné.\n"
            "Laissez un champ vide pour conserver le comportement par disque."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(hint)
        layout.addWidget(_make_sep())

        layout.addWidget(QLabel("📦  Dossier racine des Instances :"))
        inst_row = QHBoxLayout()
        self.inst_edit = QLineEdit(storage.get("instances_root") or "")
        self.inst_edit.setPlaceholderText(r"ex: D:\MesProjets\Instances  (laisser vide = disque)")
        btn_inst = QPushButton("📂")
        btn_inst.setFixedWidth(36)
        btn_inst.clicked.connect(lambda: self._browse(self.inst_edit))
        btn_inst_clr = QPushButton("✕")
        btn_inst_clr.setObjectName("subtle")
        btn_inst_clr.setFixedWidth(28)
        btn_inst_clr.clicked.connect(lambda: self.inst_edit.clear())
        inst_row.addWidget(self.inst_edit)
        inst_row.addWidget(btn_inst)
        inst_row.addWidget(btn_inst_clr)
        layout.addLayout(inst_row)

        layout.addWidget(QLabel("🧩  Dossier racine des Intents :"))
        int_row = QHBoxLayout()
        self.int_edit = QLineEdit(storage.get("intents_root") or "")
        self.int_edit.setPlaceholderText(r"ex: D:\MesProjets\Intents  (laisser vide = disque)")
        btn_int = QPushButton("📂")
        btn_int.setFixedWidth(36)
        btn_int.clicked.connect(lambda: self._browse(self.int_edit))
        btn_int_clr = QPushButton("✕")
        btn_int_clr.setObjectName("subtle")
        btn_int_clr.setFixedWidth(28)
        btn_int_clr.clicked.connect(lambda: self.int_edit.clear())
        int_row.addWidget(self.int_edit)
        int_row.addWidget(btn_int)
        int_row.addWidget(btn_int_clr)
        layout.addLayout(int_row)

        layout.addWidget(_make_sep())

        note = QLabel(
            "⚠  Modifier ces chemins n'affecte que les <b>nouvelles</b> créations.\n"
            "Les instances et intents existants gardent leur emplacement actuel."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #fab387; font-size: 12px;")
        layout.addWidget(note)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("✔  Enregistrer")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._validate)
        btns.addWidget(btn_cancel)
        btns.addStretch()
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def _browse(self, edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier de stockage")
        if folder:
            edit.setText(folder)

    def _validate(self) -> None:
        inst_root = self.inst_edit.text().strip() or None
        int_root  = self.int_edit.text().strip()  or None

        for path_str, label in [(inst_root, "Instances"), (int_root, "Intents")]:
            if path_str:
                p = Path(path_str)
                if not p.is_absolute():
                    QMessageBox.warning(self, "Voktora",
                        f"Le chemin pour {label} doit être absolu.")
                    return

        core.set_storage_config(inst_root, int_root)
        self.accept()


# ══════════════════════════════════════════════════════
#  DIALOG — DIAGNOSTIC / RÉPARATION (v1.0.1)
# ══════════════════════════════════════════════════════

class DiagnosticDialog(QDialog):
    def __init__(self, result: "core.HealthCheckResult", parent: QWidget | None = None):
        super().__init__(parent)
        self._result = result
        self.setWindowTitle("🔍  Diagnostic — Voktora")
        self.setMinimumWidth(620)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        has_errors = result.has_errors
        color      = "#f38ba8" if has_errors else "#fab387"
        icon_str   = "⛔" if has_errors else "⚠"

        title = QLabel(f"{icon_str}  Problèmes détectés au démarrage")
        title.setStyleSheet(f"font-size: 17px; font-weight: 700; color: {color};")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        sub = QLabel(
            "Voktora a détecté des anomalies. "
            "Cliquez sur « Réparer » pour tenter une correction automatique."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(sub)
        layout.addWidget(_make_sep())

        scroll  = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        vbox    = QVBoxLayout(content)
        vbox.setSpacing(10)
        vbox.setContentsMargins(0, 0, 0, 0)

        self._fix_buttons: list[tuple[QPushButton, QLabel, "core.DiagnosticIssue"]] = []

        for issue in result.issues:
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background-color: #181825; border: 1px solid "
                + ("#f38ba8" if issue.level == "error" else "#fab387")
                + "; border-radius: 8px; padding: 10px; }"
            )
            cv = QVBoxLayout(card)
            cv.setSpacing(6)

            lbl_title = QLabel(
                f"{'⛔' if issue.level == 'error' else '⚠'}"
                f"  <b>{html.escape(issue.title)}</b>"
                f"  <span style='color:#6c7086; font-size:11px'>[{issue.category}]</span>"
            )
            lbl_title.setTextFormat(Qt.RichText)
            cv.addWidget(lbl_title)

            lbl_detail = QLabel(html.escape(issue.detail).replace("\n", "<br>"))
            lbl_detail.setWordWrap(True)
            lbl_detail.setStyleSheet("color: #a6adc8; font-size: 12px;")
            lbl_detail.setTextFormat(Qt.RichText)
            cv.addWidget(lbl_detail)

            if issue.can_fix:
                row = QHBoxLayout()
                btn_fix = QPushButton(f"🔧  {issue.fix_label}")
                btn_fix.setObjectName("warn")
                btn_fix.setFixedWidth(260)
                lbl_status = QLabel("")
                lbl_status.setStyleSheet("font-size: 12px; color: #a6e3a1;")
                row.addWidget(btn_fix)
                row.addWidget(lbl_status)
                row.addStretch()
                cv.addLayout(row)
                self._fix_buttons.append((btn_fix, lbl_status, issue))
                btn_fix.clicked.connect(
                    lambda checked=False, b=btn_fix, l=lbl_status, iss=issue:
                        self._run_fix(b, l, iss)
                )

            vbox.addWidget(card)

        vbox.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        layout.addWidget(_make_sep())

        btns = QHBoxLayout()
        btn_ignore = QPushButton("Ignorer et continuer")
        btn_ignore.setObjectName("subtle")
        btn_ignore.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(btn_ignore)
        layout.addLayout(btns)

    def _run_fix(self, btn, lbl, issue):
        btn.setEnabled(False)
        lbl.setText("⏳  Réparation en cours…")
        lbl.setStyleSheet("color: #fab387; font-size: 12px;")
        QApplication.processEvents()

        success, msg = False, "Réparation non implémentée."

        if issue.category == "config":
            success, msg = core.repair_config()
        elif issue.category == "data":
            success, msg = core.repair_orphans()
        elif issue.category == "dependency":
            success, msg = core.reinstall_dependencies()

        if success:
            lbl.setText(f"✅  {msg[:80]}")
            lbl.setStyleSheet("color: #a6e3a1; font-size: 12px;")
            btn.setText("✅  Réparé")
        else:
            lbl.setText(f"❌  Échec : {msg[:120]}")
            lbl.setStyleSheet("color: #f38ba8; font-size: 12px;")
            btn.setEnabled(True)
            btn.setText("↺  Réessayer")


# ══════════════════════════════════════════════════════
#  DIALOG DÉSINSTALLATION
# ══════════════════════════════════════════════════════

class UninstallDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Désinstaller Voktora")
        self.setFixedWidth(560)
        self.setModal(True)

        self._backup_dir: Path | None = None
        self._do_backup: bool = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(28, 28, 28, 28)
        self._layout.setSpacing(0)

        self._pages: list[QWidget] = []
        self._current_page = 0

        for page in [self._build_page1(), self._build_page2(), self._build_page3()]:
            self._layout.addWidget(page)
            self._pages.append(page)

        self._show_page(0)

    def _build_page1(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(16)
        lbl_title = QLabel("⚠  Désinstaller Voktora")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f38ba8;")
        lbl_title.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl_title)
        v.addWidget(_make_sep())
        warn_box = QLabel(
            "<b>Les éléments suivants seront supprimés définitivement :</b><br><br>"
            "• Le dossier entier de l'application Voktora<br>"
            "• Les fichiers de configuration (<code>data/config.json</code>)<br>"
            "• Les backups automatiques (<code>data/backups/</code>)<br>"
            "• Les assets de l'application (<code>assets/</code>)<br><br>"
            "<b>Les instances et intents sur vos disques externes ne sont PAS supprimés</b><br>"
            "sauf si vous les avez stockés dans le dossier de l'application.<br><br>"
            "<span style='color:#f38ba8;'>⚠  Assurez-vous d'avoir fait des backups avant de continuer.</span>"
        )
        warn_box.setWordWrap(True)
        warn_box.setStyleSheet(
            "background-color: #11111b; border: 1px solid #f38ba8;"
            "border-radius: 8px; padding: 14px; color: #cdd6f4; line-height: 1.6;"
        )
        v.addWidget(warn_box)
        v.addSpacing(12)
        btns = QHBoxLayout()
        btn_cancel = QPushButton("✕  Annuler — Garder Voktora")
        btn_cancel.setObjectName("primary")
        btn_cancel.clicked.connect(self.reject)
        btn_next = QPushButton("Continuer →")
        btn_next.setObjectName("danger")
        btn_next.clicked.connect(lambda: self._show_page(1))
        btns.addWidget(btn_cancel)
        btns.addStretch()
        btns.addWidget(btn_next)
        v.addLayout(btns)
        return w

    def _build_page2(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(16)
        lbl_title = QLabel("💾  Sauvegarder avant de partir ?")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #fab387;")
        lbl_title.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl_title)
        v.addWidget(_make_sep())
        info = QLabel(
            "Voktora peut exporter <b>toutes vos instances et intents</b> en .zip<br>"
            "et déplacer vos backups existants vers un dossier de votre choix.<br><br>"
            "Cette étape est <b>facultative</b> mais fortement recommandée."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #cdd6f4; line-height: 1.6;")
        v.addWidget(info)
        self.chk_backup = QCheckBox("✔  Oui, exporter mes données vers un dossier de sauvegarde")
        self.chk_backup.setChecked(True)
        self.chk_backup.setStyleSheet("font-weight: 600; color: #a6e3a1;")
        v.addWidget(self.chk_backup)
        dir_row = QHBoxLayout()
        self.lbl_backup_dir = QLabel("(aucun dossier sélectionné)")
        self.lbl_backup_dir.setObjectName("pathLabel")
        self.lbl_backup_dir.setWordWrap(True)
        self.lbl_backup_dir.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        btn_choose = QPushButton("📂  Choisir…")
        btn_choose.setFixedWidth(110)
        btn_choose.clicked.connect(self._choose_backup_dir)
        dir_row.addWidget(self.lbl_backup_dir)
        dir_row.addWidget(btn_choose)
        v.addLayout(dir_row)
        self.chk_backup.toggled.connect(lambda checked: btn_choose.setEnabled(checked))
        v.addSpacing(8)
        v.addWidget(_make_sep())
        btns = QHBoxLayout()
        btn_back = QPushButton("← Retour")
        btn_back.setObjectName("subtle")
        btn_back.clicked.connect(lambda: self._show_page(0))
        btn_next = QPushButton("Continuer →")
        btn_next.setObjectName("warn")
        btn_next.clicked.connect(self._validate_page2)
        btns.addWidget(btn_back)
        btns.addStretch()
        btns.addWidget(btn_next)
        v.addLayout(btns)
        return w

    def _build_page3(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(16)
        lbl_title = QLabel("🗑  Confirmation finale")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f38ba8;")
        lbl_title.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl_title)
        v.addWidget(_make_sep())
        self.lbl_summary = QLabel()
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(
            "background-color: #11111b; border: 1px solid #313244;"
            "border-radius: 8px; padding: 14px; color: #cdd6f4; line-height: 1.6;"
        )
        v.addWidget(self.lbl_summary)
        v.addSpacing(8)
        btns = QHBoxLayout()
        btn_back    = QPushButton("← Retour")
        btn_back.setObjectName("subtle")
        btn_back.clicked.connect(lambda: self._show_page(1))
        btn_cancel  = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_confirm = QPushButton("🗑  Confirmer la désinstallation")
        btn_confirm.setObjectName("danger")
        btn_confirm.clicked.connect(self.accept)
        btns.addWidget(btn_back)
        btns.addWidget(btn_cancel)
        btns.addStretch()
        btns.addWidget(btn_confirm)
        v.addLayout(btns)
        return w

    def _show_page(self, index: int):
        for i, p in enumerate(self._pages):
            p.setVisible(i == index)
        self._current_page = index
        self.adjustSize()

    def _choose_backup_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier de sauvegarde")
        if folder:
            self._backup_dir = Path(folder)
            self.lbl_backup_dir.setText(str(self._backup_dir))

    def _validate_page2(self):
        self._do_backup = self.chk_backup.isChecked()
        if self._do_backup and self._backup_dir is None:
            QMessageBox.warning(self, "Voktora",
                "Veuillez choisir un dossier de sauvegarde,\nou décochez l'option de backup.")
            return
        lines: list[str] = []
        if self._do_backup and self._backup_dir:
            lines.append(
                f"✅  Backup de toutes les instances et intents vers :<br>"
                f"<code>{self._backup_dir}</code>"
            )
        else:
            lines.append("⚠  <b>Aucun backup</b> ne sera effectué.")
        lines.append(
            f"<br>🗑  Suppression du dossier de l'application :<br>"
            f"<code>{core.get_app_dir()}</code>"
        )
        lines.append(
            "<br>Voktora se fermera immédiatement après avoir lancé le script de nettoyage."
        )
        self.lbl_summary.setText("<br>".join(lines))
        self._show_page(2)

    def get_options(self) -> tuple[bool, Path | None]:
        return self._do_backup, self._backup_dir


# ══════════════════════════════════════════════════════
#  DIALOG GITHUB (configuration instance)
# ══════════════════════════════════════════════════════

class GitDialog(QDialog):
    def __init__(
        self,
        current_url: str = "",
        current_branch: str = "main",
        token_protected: bool = False,
        has_global_account: bool = False,
        global_login: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("GitHub — Voktora")
        self.setFixedWidth(580)

        self._token_protected   = token_protected
        self._token_in_clear:   str = ""
        self._new_token_password: str = ""
        self._has_global        = has_global_account
        self._global_login      = global_login

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("🐙  Configuration GitHub")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(_make_sep())

        # ── Bannière compte connecté (si session OAuth active) ──
        if has_global_account and global_login:
            banner = QFrame()
            banner.setObjectName("githubCardConnected")
            banner_h = QHBoxLayout(banner)
            banner_h.setContentsMargins(8, 6, 8, 6)
            lbl_gh = QLabel(f"🐙  Compte connecté : <b>{html.escape(global_login)}</b>")
            lbl_gh.setTextFormat(Qt.RichText)
            lbl_gh.setStyleSheet("color: #a6e3a1; font-size: 12px;")
            lbl_hint = QLabel("Le token OAuth sera utilisé automatiquement.")
            lbl_hint.setStyleSheet("color: #6c7086; font-size: 11px;")
            banner_h.addWidget(lbl_gh)
            banner_h.addStretch()
            banner_h.addWidget(lbl_hint)
            layout.addWidget(banner)

        layout.addWidget(QLabel("URL du repository :"))
        self.url_edit = QLineEdit(current_url)
        self.url_edit.setPlaceholderText("https://github.com/user/repo.git")
        layout.addWidget(self.url_edit)

        self.chk_private = QCheckBox("🔒  Ce repository est privé")
        self.chk_private.setChecked(token_protected or (not has_global_account))
        layout.addWidget(self.chk_private)

        # ── Token PAT (optionnel si compte global connecté) ──
        self.token_container = QWidget()
        token_v = QVBoxLayout(self.token_container)
        token_v.setContentsMargins(0, 0, 0, 0)
        token_v.setSpacing(6)

        if has_global_account and global_login:
            lbl_pat_or = QLabel(
                "👤  <b>Token OAuth du compte connecté</b> utilisé par défaut.<br>"
                "Vous pouvez aussi renseigner un PAT spécifique à cette instance\n"
                "(il sera prioritaire sur le compte connecté)."
            )
            lbl_pat_or.setWordWrap(True)
            lbl_pat_or.setTextFormat(Qt.RichText)
            lbl_pat_or.setStyleSheet("color: #a6adc8; font-size: 12px;")
            token_v.addWidget(lbl_pat_or)

        lbl_token = QLabel("Personal Access Token (PAT) — optionnel si compte connecté :" if has_global_account else "Personal Access Token (PAT) :")
        lbl_token_hint = QLabel(
            "💡  GitHub → Settings → Developer settings → "
            "Fine-grained tokens<br>"
            "Permission requise : <b>Contents</b> = Read & Write"
        )
        lbl_token_hint.setObjectName("sectionLbl")
        lbl_token_hint.setWordWrap(True)

        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText(
            "ghp_xxxx… (laisser vide = utiliser le compte GitHub connecté)"
            if has_global_account
            else "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        )
        self.token_edit.setEchoMode(QLineEdit.Password)

        if token_protected:
            self.token_edit.setPlaceholderText(
                "🔐  Token protégé — entrez le mdp ci-dessous pour modifier"
            )
            self.token_edit.setEnabled(False)

        self.btn_show_token = QPushButton("👁  Afficher")
        self.btn_show_token.setObjectName("subtle")
        self.btn_show_token.setFixedWidth(110)
        self.btn_show_token.clicked.connect(self._toggle_token_visibility)

        token_row = QHBoxLayout()
        token_row.addWidget(self.token_edit)
        token_row.addWidget(self.btn_show_token)

        token_v.addWidget(lbl_token)
        token_v.addLayout(token_row)
        token_v.addWidget(lbl_token_hint)

        protect_sep = QFrame(); protect_sep.setFrameShape(QFrame.HLine)
        token_v.addWidget(protect_sep)

        self.chk_protect = QCheckBox(
            "🔐  Protéger le token avec un mot de passe  (chiffrement Whirlpool)"
        )
        self.chk_protect.setChecked(token_protected)
        self.chk_protect.setStyleSheet("font-weight: 600; color: #cba6f7;")
        token_v.addWidget(self.chk_protect)

        lbl_protect_hint = QLabel(
            "Le token est chiffré via <b>Whirlpool + XOR</b> avant d'être stocké.\n"
            "Sans le mot de passe, les opérations Git demandent une confirmation."
        )
        lbl_protect_hint.setObjectName("sectionLbl")
        lbl_protect_hint.setWordWrap(True)
        token_v.addWidget(lbl_protect_hint)

        self.btn_set_pwd = QPushButton("🔑  Définir / Modifier le mot de passe du token")
        self.btn_set_pwd.setObjectName("warn")
        self.btn_set_pwd.clicked.connect(self._set_token_password)
        token_v.addWidget(self.btn_set_pwd)

        self.lbl_pwd_status = QLabel("")
        self.lbl_pwd_status.setObjectName("sectionLbl")
        token_v.addWidget(self.lbl_pwd_status)

        if token_protected:
            btn_unlock = QPushButton("🔓  Déverrouiller le token (entrer le mot de passe)")
            btn_unlock.setObjectName("subtle")
            btn_unlock.clicked.connect(self._unlock_token)
            token_v.addWidget(btn_unlock)

        layout.addWidget(self.token_container)

        # Vérification repo
        verify_row = QHBoxLayout()
        self.btn_verify = QPushButton("🔍  Vérifier l'accès au repo")
        self.btn_verify.setObjectName("warn")
        self.btn_verify.clicked.connect(self._verify_repo)
        self.lbl_verify_result = QLabel("")
        self.lbl_verify_result.setWordWrap(True)
        self.lbl_verify_result.setObjectName("sectionLbl")
        verify_row.addWidget(self.btn_verify)
        verify_row.addWidget(self.lbl_verify_result, 1)
        layout.addLayout(verify_row)
        layout.addWidget(_make_sep())

        # Branche principale
        branch_row = QHBoxLayout()
        lbl_branch = QLabel("Branche principale :")
        lbl_branch.setFixedWidth(130)
        self.branch_combo = QComboBox()
        self.branch_combo.setEditable(True)
        self.branch_combo.addItems(["main", "master", "develop", "staging"])
        idx = self.branch_combo.findText(current_branch)
        if idx >= 0:
            self.branch_combo.setCurrentIndex(idx)
        else:
            self.branch_combo.setCurrentText(current_branch)

        self.btn_load_branches = QPushButton("↻  Charger depuis GitHub")
        self.btn_load_branches.setObjectName("subtle")
        self.btn_load_branches.clicked.connect(self._load_remote_branches)
        branch_row.addWidget(lbl_branch)
        branch_row.addWidget(self.branch_combo, 1)
        branch_row.addWidget(self.btn_load_branches)
        layout.addLayout(branch_row)

        lbl_branch_hint = QLabel(
            "💡  Branche principale utilisée par défaut. "
            "Vous pouvez pousser vers plusieurs branches dans le dialog de push."
        )
        lbl_branch_hint.setObjectName("sectionLbl")
        lbl_branch_hint.setWordWrap(True)
        layout.addWidget(lbl_branch_hint)
        layout.addWidget(_make_sep())

        self.chk_init = QCheckBox("⚙  Initialiser git local (git init)")
        self.chk_push = QCheckBox("🚀  Push initial vers GitHub")
        self.chk_init.setChecked(not bool(current_url))
        layout.addWidget(self.chk_init)
        layout.addWidget(self.chk_push)

        note = QLabel("💡  Laisser 'Push initial' décoché pour lier sans pousser.")
        note.setObjectName("sectionLbl")
        layout.addWidget(note)
        layout.addWidget(_make_sep())

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("✔  Appliquer")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.clicked.connect(self._validate)
        btns.addWidget(btn_cancel)
        btns.addStretch()
        btns.addWidget(self.btn_ok)
        layout.addLayout(btns)

        self.chk_private.toggled.connect(self._on_private_toggled)
        self.chk_protect.toggled.connect(self._on_protect_toggled)
        self.url_edit.textChanged.connect(self._reset_verify)
        self.token_edit.textChanged.connect(self._reset_verify)
        self._on_private_toggled(self.chk_private.isChecked())
        self._repo_verified: bool = False

    def _on_private_toggled(self, checked: bool):
        self.token_container.setVisible(checked)
        self.adjustSize()
        self._reset_verify()

    def _on_protect_toggled(self, checked: bool):
        self.btn_set_pwd.setVisible(checked)
        if not checked:
            self._new_token_password = ""
            self.lbl_pwd_status.setText("")
        self.token_edit.setEnabled(True)

    def _toggle_token_visibility(self):
        if self.token_edit.echoMode() == QLineEdit.Password:
            self.token_edit.setEchoMode(QLineEdit.Normal)
            self.btn_show_token.setText("🙈  Masquer")
        else:
            self.token_edit.setEchoMode(QLineEdit.Password)
            self.btn_show_token.setText("👁  Afficher")

    def _set_token_password(self):
        dlg = TokenPasswordDialog(mode="set", parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._new_token_password = dlg.get_password()
            algo = "Whirlpool" if core._whirlpool_available() else "SHA-512 (fallback)"
            self.lbl_pwd_status.setText(
                f"✅  Mot de passe défini — chiffrement via <b>{algo}</b>"
            )
            self.token_edit.setEnabled(True)

    def _unlock_token(self):
        dlg = TokenPasswordDialog(mode="get", parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._new_token_password = dlg.get_password()
            self.token_edit.setEnabled(True)
            self.token_edit.setPlaceholderText(
                "Token déverrouillé — vérification au moment de l'application"
            )
            self.lbl_pwd_status.setText("🔓  Déverrouillage en attente…")

    def _reset_verify(self):
        self._repo_verified = False
        self.lbl_verify_result.setText("")

    def _get_current_token(self) -> str:
        typed = self.token_edit.text().strip()
        if typed:
            # Vérifier le token saisi manuellement
            is_valid, message = core.verify_github_token(typed)
            if is_valid:
                return typed
            else:
                # Token invalide, on l'indique à l'utilisateur
                self.lbl_verify_result.setText(f"❌ {message}")
                return ""
        if self._token_in_clear:
            return self._token_in_clear
        # Vérifier la session GitHub globale
        if self._has_global:
            session = core.get_github_session()
            if session and session.get("token"):
                # Vérifier que le token OAuth est toujours valide
                is_valid, message = core.verify_github_token(session["token"])
                if is_valid:
                    return session["token"]
                else:
                    # Token OAuth invalide
                    self.lbl_verify_result.setText(f"❌ Session GitHub expirée : {message}")
                    return ""
        return ""

    def _verify_repo(self):
        url   = self.url_edit.text().strip()
        token = self._get_current_token() if self.chk_private.isChecked() else ""
        if not url:
            self.lbl_verify_result.setText("⚠  Entrez d'abord une URL.")
            return
        self.btn_verify.setEnabled(False)
        self.lbl_verify_result.setText("⏳  Vérification…")
        QApplication.processEvents()
        ok, msg = core.verify_github_repo(url, token)
        self._repo_verified = ok
        self.lbl_verify_result.setText(msg)
        self.btn_verify.setEnabled(True)

    def _load_remote_branches(self):
        url   = self.url_edit.text().strip()
        token = self._get_current_token() if self.chk_private.isChecked() else ""
        if not url:
            QMessageBox.warning(self, "Voktora", "Entrez d'abord une URL de repo.")
            return
        self.btn_load_branches.setEnabled(False)
        self.btn_load_branches.setText("⏳  Chargement…")
        QApplication.processEvents()
        branches = core.list_github_branches(url, token)
        self.btn_load_branches.setEnabled(True)
        self.btn_load_branches.setText("↻  Charger depuis GitHub")
        if not branches:
            QMessageBox.warning(self, "Voktora",
                "Impossible de charger les branches.\n"
                "Vérifiez l'URL et le token si le repo est privé.")
            return
        current = self.branch_combo.currentText()
        self.branch_combo.clear()
        self.branch_combo.addItems(branches)
        idx = self.branch_combo.findText(current)
        if idx >= 0:
            self.branch_combo.setCurrentIndex(idx)
        elif current:
            self.branch_combo.setCurrentText(current)

    def _validate(self):
        url = self.url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Voktora", "Entrez une URL de repository.")
            return

        if not self._repo_verified:
            token = self._get_current_token() if self.chk_private.isChecked() else ""
            self.btn_verify.setEnabled(False)
            self.lbl_verify_result.setText("⏳  Vérification…")
            QApplication.processEvents()
            ok, msg = core.verify_github_repo(url, token)
            self.lbl_verify_result.setText(msg)
            self.btn_verify.setEnabled(True)
            self._repo_verified = ok
            if not ok:
                QMessageBox.warning(
                    self, "Voktora — Repo inaccessible",
                    f"{msg}\n\nVérifiez l'URL et le token."
                )
                return

        self.accept()

    def get_data(self) -> dict:
        typed_token = self.token_edit.text().strip()
        token = typed_token if typed_token else self._token_in_clear
        if not token and self.chk_private.isChecked() and self._has_global:
            token = ""   # Sera récupéré via get_effective_token() lors du push

        return {
            "url":            self.url_edit.text().strip(),
            "token":          token if self.chk_private.isChecked() else "",
            "branch":         self.branch_combo.currentText().strip() or "main",
            "do_init":        self.chk_init.isChecked(),
            "do_push":        self.chk_push.isChecked(),
            "protect":        self.chk_protect.isChecked() and self.chk_private.isChecked(),
            "token_password": self._new_token_password,
        }


# ══════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Voktora — Project Instance Manager")
        self.setMinimumSize(1180, 720)
        
        # Appliquer le thème
        theme_manager.apply_theme_to_app(QApplication.instance())
        
        self._sel_path:   Path | None      = None
        self._sel_kind:   str              = ""
        self._worker:     Worker | None    = None
        self._git_worker: GitWorker | None = None
        self._delete_worker: DeleteWorker | None = None
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
        self._update_worker: UpdateCheckWorker | None = None
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
            dlg = TokenPasswordDialog(mode="get", parent=self)
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
        self._update_worker = UpdateCheckWorker()
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
            dlg = DiagnosticDialog(result, parent=self)
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
        title = "📋 Migration de configuration v1.0.1"
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
        self.instance_search.clear()
        self.intent_search.clear()

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
        v.addWidget(_make_sep())
        v.addSpacing(2)

        self._github_card = self._build_github_account_card()
        v.addWidget(self._github_card)

        v.addSpacing(2)
        v.addWidget(_make_sep())
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
            dlg = TokenPasswordDialog(mode="get", parent=self)
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
            login = session.get("login", "")
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
        self._worker = Worker(fn, *args)
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

        self._git_worker = GitWorker(fn, *args, **kwargs)
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
        import hooks as _h; _h.fire("on_open", self._sel_path, log_cb=self._project_panel.log)
        import dashboard as _d; _d.record_open(self._sel_path)

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
        self._browser.get_list_view().get_search_widget().setFocus()
        self._browser.get_list_view().get_search_widget().selectAll()

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
                "🔐  Token PAT protégé par mot de passe (Whirlpool)" if protected else ""
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
        dlg = GitHubLoginDialog(parent=self)
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
            pwd_dlg = TokenPasswordDialog(mode="set", parent=self)
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
        dlg = CreateDialog(kind, self)
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
        self._delete_worker = DeleteWorker(self._sel_path)
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
        zip_file, _ = QFileDialog.getOpenFileName(
            self, f"Sélectionner le .zip ({label})",
            filter="Archives ZIP (*.zip)"
        )
        if not zip_file:
            return
        drive = self._current_drive()
        if drive.startswith("("):
            QMessageBox.warning(self, "Voktora", "Aucun disque externe sélectionné.")
            return
        try:
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
        dlg = StorageDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._log("⚙  Emplacements de stockage mis à jour.")

    def act_run_diagnostic(self):
        result = core.run_health_check()
        if result.is_healthy:
            QMessageBox.information(self, "Voktora — Diagnostic",
                "✅  Aucun problème détecté.\nL'application et les données sont en bonne santé.")
        else:
            dlg = DiagnosticDialog(result, parent=self)
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

        dlg = GitDialog(
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
                algo = "Whirlpool" if core._whirlpool_available() else "SHA-512"
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
        dlg = PushDialog(instance_path=self._sel_path, mode=mode, parent=self)
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
        dlg = UninstallDialog(self)
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
            + "<br>".join(f"<code>{l}</code>" for l in preview_lines)
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

    def act_open_terminal(self):
        """Action pour ouvrir un terminal."""
        if not self._need_sel():
            return
        core.open_terminal(self._sel_path)
        self._log(f"💻 Terminal ouvert → {self._sel_path}")

    def act_open_explorer(self):
        """Action pour ouvrir l'explorateur."""
        if not self._need_sel():
            return
        core.open_explorer(self._sel_path)
        self._log(f"📁 Explorateur ouvert → {self._sel_path}")

    def act_open_vscode(self):
        """Ouvre VS Code dans le dossier sélectionné."""
        if not self._need_sel():
            return
        core.open_vscode(self._sel_path)
        self._log(f"💙 VS Code ouvert → {self._sel_path}")

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