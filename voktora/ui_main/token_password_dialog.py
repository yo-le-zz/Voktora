"""
Voktora — ui_main.token_password_dialog
Fragment de ui_main.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import workers


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
                "via chiffrement <b>AES-256 (Fernet, PBKDF2-HMAC-SHA256)</b>.\n\n"
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
        layout.addWidget(workers._make_sep())
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

        layout.addWidget(workers._make_sep())

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
        if self._mode == "set" and self.pwd_confirm and pwd != self.pwd_confirm.text():
            QMessageBox.warning(self, "Voktora", "Les mots de passe ne correspondent pas.")
            return
        self.accept()

    def get_password(self) -> str:
        return self.pwd_edit.text()


# ══════════════════════════════════════════════════════
#  DIALOG PUSH AVANCÉ
# ══════════════════════════════════════════════════════

