"""
Voktora — ui_main.github_login_dialog
Fragment de ui_main.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import core
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import workers


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

        self._poll_worker: workers.OAuthPollWorker | None = None
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

        layout.addWidget(workers._make_sep())

        # ── Stack ──
        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._build_page_method()
        self._build_page_oauth()
        self._build_page_app()
        self._build_page_code()
        self._build_page_wait()
        self._build_page_migrate()

        layout.addWidget(workers._make_sep())

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

        self._poll_worker = workers.OAuthPollWorker(pending)
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


