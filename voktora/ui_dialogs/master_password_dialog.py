"""
Voktora — ui_dialogs.master_password_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

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


