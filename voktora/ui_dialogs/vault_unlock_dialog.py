"""
Voktora — ui_dialogs.vault_unlock_dialog
Déverrouillage du vault (mot de passe maître). Proposé au démarrage (si le vault contient des secrets),
depuis la fenêtre du vault, et automatiquement quand une action a besoin d'un secret.
"""

from __future__ import annotations

import core
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout


class VaultUnlockDialog(QDialog):
    def __init__(self, parent=None, reason: str = "", allow_skip: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Déverrouiller le vault")
        self.setModal(True)
        self.setMinimumWidth(400)
        self._fails = 0

        title = QLabel("Mot de passe maître")
        title.setStyleSheet("font-size:14px; font-weight:bold;")
        info = QLabel(reason or "Entrez le mot de passe maître pour accéder à vos secrets (tokens, clés…).")
        info.setWordWrap(True)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Mot de passe maître")
        self.password.setMinimumHeight(34)
        self.password.returnPressed.connect(self._try)
        self.error = QLabel("")
        self.error.setStyleSheet("color:#f38ba8;")

        ok = QPushButton("Déverrouiller")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self._try)
        later = QPushButton("Plus tard" if allow_skip else "Annuler")
        later.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(later)
        row.addWidget(ok)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        for widget in (title, info, self.password, self.error):
            root.addWidget(widget)
        root.addLayout(row)
        self.password.setFocus()

    def _try(self) -> None:
        if core.vault_unlock(self.password.text()):
            self.accept()
            return
        self._fails += 1
        self.password.clear()
        self.error.setText("Mot de passe incorrect." + ("  (Il n'existe pas de récupération possible.)"
                                                        if self._fails >= 3 else ""))


def ensure_unlocked(parent=None, reason: str = "") -> bool:
    """True si le vault est (ou vient d'être) déverrouillé. Propose le mot de passe sinon."""
    if core.vault_is_unlocked():
        return True
    if not core.vault_is_initialized():
        return False
    return VaultUnlockDialog(parent, reason).exec() == QDialog.Accepted


def prompt_at_startup() -> None:
    """Au démarrage : propose le déverrouillage uniquement si le vault contient déjà des secrets."""
    if core.vault_is_unlocked() or not core.vault_is_initialized():
        return
    try:
        has_secrets = bool(core.vault_list_keys())
    except Exception:       # noqa: BLE001 - le démarrage ne doit jamais échouer à cause du vault
        has_secrets = False
    if has_secrets:
        VaultUnlockDialog(None, "Déverrouillez le vault pour utiliser vos tokens et secrets enregistrés.",
                          allow_skip=True).exec()
