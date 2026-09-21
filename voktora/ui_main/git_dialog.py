"""
Voktora — ui_main.git_dialog
Fragment de ui_main.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import html

import core
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import token_password_dialog, workers


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
        layout.addWidget(workers._make_sep())

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

        protect_sep = QFrame()
        protect_sep.setFrameShape(QFrame.HLine)
        token_v.addWidget(protect_sep)

        self.chk_protect = QCheckBox(
            "🔐  Protéger le token avec un mot de passe  (chiffrement AES-256)"
        )
        self.chk_protect.setChecked(token_protected)
        self.chk_protect.setStyleSheet("font-weight: 600; color: #cba6f7;")
        token_v.addWidget(self.chk_protect)

        lbl_protect_hint = QLabel(
            "Le token est chiffré via <b>AES-256 (Fernet, PBKDF2-HMAC-SHA256)</b> avant d'être stocké.\n"
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
        layout.addWidget(workers._make_sep())

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
        layout.addWidget(workers._make_sep())

        self.chk_init = QCheckBox("⚙  Initialiser git local (git init)")
        self.chk_push = QCheckBox("🚀  Push initial vers GitHub")
        self.chk_init.setChecked(not bool(current_url))
        layout.addWidget(self.chk_init)
        layout.addWidget(self.chk_push)

        note = QLabel("💡  Laisser 'Push initial' décoché pour lier sans pousser.")
        note.setObjectName("sectionLbl")
        layout.addWidget(note)
        layout.addWidget(workers._make_sep())

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
        dlg = token_password_dialog.TokenPasswordDialog(mode="set", parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._new_token_password = dlg.get_password()
            algo = "AES-256 (Fernet, PBKDF2-HMAC-SHA256)"
            self.lbl_pwd_status.setText(
                f"✅  Mot de passe défini — chiffrement via <b>{algo}</b>"
            )
            self.token_edit.setEnabled(True)

    def _unlock_token(self):
        dlg = token_password_dialog.TokenPasswordDialog(mode="get", parent=self)
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

