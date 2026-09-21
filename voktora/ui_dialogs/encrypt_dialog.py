"""
Voktora — ui_dialogs.encrypt_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

import core
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


# ════════════ encrypt_dialog.py ════════════
def _is_operation_running() -> bool:
    return _operation_in_progress



def _set_operation(state: bool) -> None:
    global _operation_in_progress
    _operation_in_progress = state


# ──────────────────────────────────────────────
# WORKER — Chiffrement en arrière-plan
# ──────────────────────────────────────────────


class EncryptWorker(QThread):
    """Chiffre/déchiffre récursivement un dossier dans un thread séparé."""

    progress_text  = Signal(str)   # Message de statut
    progress_value = Signal(int)   # Pourcentage 0-100
    finished       = Signal(bool, str)  # (succès, message)

    def __init__(self, path: Path, password: str, mode: str):
        """
        mode : "encrypt" ou "decrypt"
        """
        super().__init__()
        self._path     = path
        self._password = password
        self._mode     = mode

    def run(self) -> None:
        try:
            if self._mode == "encrypt":
                self._do_encrypt()
            else:
                self._do_decrypt()
            self.finished.emit(True, "Opération terminée avec succès.")
        except Exception as e:
            self.finished.emit(False, str(e))

    # ── Dérivation de clé ──────────────────────────

    @staticmethod
    def _derive_key(password: str) -> bytes:
        return hashlib.sha512(password.encode("utf-8")).digest()

    # ── Chiffrement ────────────────────────────────

    def _do_encrypt(self) -> None:
        files = [f for f in self._path.rglob("*")
                 if f.is_file() and not f.name.startswith(".")]
        total = len(files)
        if total == 0:
            return

        key = self._derive_key(self._password)

        for i, file_path in enumerate(files):
            # Ignorer les fichiers déjà chiffrés
            if file_path.suffix == ".menc":
                continue
            self.progress_text.emit(f"Chiffrement : {file_path.name}")
            self.progress_value.emit(int(i / total * 90))

            try:
                with open(file_path, "rb") as f:
                    data = f.read()

                encrypted = bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])
                enc_path  = file_path.with_suffix(file_path.suffix + ".menc")

                with open(enc_path, "wb") as f:
                    f.write(encrypted)

                file_path.unlink()

            except Exception as e:
                self.progress_text.emit(f"⚠ Ignoré : {file_path.name} ({e})")

        # Marqueur de chiffrement
        marker = self._path / ".voktora_encrypted"
        marker.write_text(
            f"Encrypted with Voktora v{core.APP_VERSION}\n"
            f"Date: {datetime.now().isoformat()}\n"
        )
        self.progress_value.emit(100)

    # ── Déchiffrement ──────────────────────────────

    def _do_decrypt(self) -> None:
        files = [f for f in self._path.rglob("*.menc") if f.is_file()]
        total = len(files)
        if total == 0:
            # Tenter l'ancien format (.encrypted)
            files = [f for f in self._path.rglob("*.encrypted") if f.is_file()]
            total = len(files)

        if total == 0:
            self.progress_value.emit(100)
            return

        key = self._derive_key(self._password)

        for i, file_path in enumerate(files):
            self.progress_text.emit(f"Déchiffrement : {file_path.name}")
            self.progress_value.emit(int(i / total * 90))

            try:
                with open(file_path, "rb") as f:
                    encrypted_data = f.read()

                decrypted = bytes([b ^ key[i % len(key)] for i, b in enumerate(encrypted_data)])

                # Retirer l'extension .menc ou .encrypted
                if file_path.suffix == ".menc":
                    original_path = file_path.with_suffix("")
                elif file_path.suffix == ".encrypted":
                    original_path = Path(str(file_path)[:-10])
                else:
                    continue

                with open(original_path, "wb") as f:
                    f.write(decrypted)

                file_path.unlink()

            except Exception as e:
                self.progress_text.emit(f"⚠ Ignoré : {file_path.name} ({e})")

        # Supprimer le marqueur
        marker = self._path / ".voktora_encrypted"
        if marker.exists():
            marker.unlink()

        self.progress_value.emit(100)


# ──────────────────────────────────────────────
# WORKER — Copie/backup avec progression
# ──────────────────────────────────────────────


class CopyWorker(QThread):
    """Copie un dossier avec progression en arrière-plan."""

    progress_text  = Signal(str)
    progress_value = Signal(int)
    finished       = Signal(bool, str)

    def __init__(self, src: Path, dst: Path):
        super().__init__()
        self._src = src
        self._dst = dst

    def run(self) -> None:
        try:
            files = [f for f in self._src.rglob("*") if f.is_file()]
            total = len(files)
            self._dst.mkdir(parents=True, exist_ok=True)

            for i, src_file in enumerate(files):
                rel = src_file.relative_to(self._src)
                dst_file = self._dst / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)

                self.progress_text.emit(f"Copie : {src_file.name}")
                self.progress_value.emit(int(i / max(total, 1) * 100))

                shutil.copy2(src_file, dst_file)

            self.progress_value.emit(100)
            self.finished.emit(True, f"Copie terminée vers {self._dst}")
        except Exception as e:
            self.finished.emit(False, str(e))


# ──────────────────────────────────────────────
# DIALOGUE PRINCIPAL
# ──────────────────────────────────────────────


class EncryptProjectDialog(QDialog):
    """Dialogue pour chiffrer/déchiffrer un projet avec barre de progression."""

    def __init__(self, project_path: str, project_kind: str, parent=None):
        super().__init__(parent)
        self.project_path  = Path(project_path)
        self.project_kind  = project_kind
        self._worker: EncryptWorker | None = None
        self._copy_worker: CopyWorker | None = None

        self.setWindowTitle("🔐 Chiffrement de projet — Voktora")
        self.setModal(True)
        self.setMinimumSize(480, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ── Informations du projet ──
        info_group = QGroupBox("📋 Projet")
        info_layout = QFormLayout()

        path_label = QLabel(str(self.project_path))
        path_label.setWordWrap(True)
        info_layout.addRow("Chemin :", path_label)

        self.is_encrypted = self._check_if_encrypted()
        status_text  = "🔒 Chiffré" if self.is_encrypted else "🔓 Non chiffré"
        status_color = "#f38ba8" if self.is_encrypted else "#a6e3a1"
        status_lbl   = QLabel(f"<b>{status_text}</b>")
        status_lbl.setStyleSheet(f"color: {status_color}; font-size: 14px;")
        info_layout.addRow("État :", status_lbl)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # ── Mot de passe ──
        pwd_group = QGroupBox("🔑 Mot de passe")
        pwd_layout = QVBoxLayout()

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Entrez le mot de passe...")
        pwd_layout.addWidget(self.password_edit)

        if not self.is_encrypted:
            self.confirm_edit = QLineEdit()
            self.confirm_edit.setEchoMode(QLineEdit.Password)
            self.confirm_edit.setPlaceholderText("Confirmez le mot de passe...")
            pwd_layout.addWidget(self.confirm_edit)
        else:
            self.confirm_edit = None

        pwd_group.setLayout(pwd_layout)
        layout.addWidget(pwd_group)

        # ── Options ──
        if not self.is_encrypted:
            self.chk_backup = QCheckBox("Créer une sauvegarde avant chiffrement")
            self.chk_backup.setChecked(True)
            layout.addWidget(self.chk_backup)
        else:
            self.chk_backup = None

        # ── Progression ──
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # ── Boutons ──
        btn_layout = QHBoxLayout()

        if self.is_encrypted:
            self.btn_action = QPushButton("🔓 Déchiffrer")
            self.btn_action.setObjectName("success")
            self.btn_action.clicked.connect(self._start_decrypt)
        else:
            self.btn_action = QPushButton("🔒 Chiffrer")
            self.btn_action.setObjectName("primary")
            self.btn_action.clicked.connect(self._start_encrypt)

        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self._on_cancel)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_action)
        layout.addLayout(btn_layout)

    # ── Helpers ────────────────────────────────────

    def _check_if_encrypted(self) -> bool:
        return (self.project_path / ".voktora_encrypted").exists()

    def _lock_ui(self, locked: bool) -> None:
        """Active/désactive les contrôles pendant une opération."""
        self.btn_action.setEnabled(not locked)
        self.password_edit.setEnabled(not locked)
        if self.confirm_edit:
            self.confirm_edit.setEnabled(not locked)
        if self.chk_backup:
            self.chk_backup.setEnabled(not locked)
        self.progress_bar.setVisible(locked)

    # ── Chiffrement ────────────────────────────────

    def _start_encrypt(self) -> None:
        # Vérifier qu'aucune opération n'est déjà en cours
        if _is_operation_running():
            QMessageBox.warning(
                self, "Opération en cours",
                "Une opération de chiffrement ou de copie est déjà en cours.\n"
                "Attendez qu'elle se termine avant d'en lancer une autre."
            )
            return

        password = self.password_edit.text()
        confirm  = self.confirm_edit.text() if self.confirm_edit else password

        if not password:
            QMessageBox.warning(self, "Attention", "Veuillez entrer un mot de passe.")
            return
        if password != confirm:
            QMessageBox.warning(self, "Attention", "Les mots de passe ne correspondent pas.")
            return
        if len(password) < 8:
            QMessageBox.warning(self, "Attention", "Le mot de passe doit contenir au moins 8 caractères.")
            return

        # Backup si demandé
        if self.chk_backup and self.chk_backup.isChecked():
            backup_path = (self.project_path.parent /
                           f"{self.project_path.name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            self._lock_ui(True)
            self.lbl_status.setText("📦 Création de la sauvegarde...")
            _set_operation(True)

            self._copy_worker = CopyWorker(self.project_path, backup_path)
            self._copy_worker.progress_text.connect(self.lbl_status.setText)
            self._copy_worker.progress_value.connect(self.progress_bar.setValue)
            self._copy_worker.finished.connect(
                lambda ok, msg: self._on_backup_done(ok, msg, password)
            )
            self._copy_worker.start()
        else:
            _set_operation(True)
            self._run_encrypt(password)

    def _on_backup_done(self, ok: bool, msg: str, password: str) -> None:
        if not ok:
            _set_operation(False)
            self._lock_ui(False)
            QMessageBox.critical(self, "Erreur backup", f"Sauvegarde échouée :\n{msg}")
            return
        self._run_encrypt(password)

    def _run_encrypt(self, password: str) -> None:
        self._lock_ui(True)
        self.lbl_status.setText("🔒 Chiffrement en cours...")
        self.progress_bar.setValue(0)

        self._worker = EncryptWorker(self.project_path, password, "encrypt")
        self._worker.progress_text.connect(self.lbl_status.setText)
        self._worker.progress_value.connect(self.progress_bar.setValue)
        self._worker.finished.connect(self._on_encrypt_done)
        self._worker.start()

    def _on_encrypt_done(self, ok: bool, msg: str) -> None:
        _set_operation(False)
        self._lock_ui(False)

        if ok:
            algo = "AES-256 (Fernet, PBKDF2-HMAC-SHA256)"
            QMessageBox.information(
                self, "Chiffrement réussi",
                f"Le projet a été chiffré avec succès.\n\n"
                f"Algorithme : {algo}\n"
                "⚠ Ne perdez pas votre mot de passe !"
            )
            self.accept()
        else:
            QMessageBox.critical(self, "Erreur", f"Chiffrement échoué :\n{msg}")

    # ── Déchiffrement ──────────────────────────────

    def _start_decrypt(self) -> None:
        if _is_operation_running():
            QMessageBox.warning(
                self, "Opération en cours",
                "Une opération de chiffrement ou de copie est déjà en cours.\n"
                "Attendez qu'elle se termine avant d'en lancer une autre."
            )
            return

        password = self.password_edit.text()
        if not password:
            QMessageBox.warning(self, "Attention", "Veuillez entrer le mot de passe.")
            return

        _set_operation(True)
        self._lock_ui(True)
        self.lbl_status.setText("🔓 Déchiffrement en cours...")
        self.progress_bar.setValue(0)

        self._worker = EncryptWorker(self.project_path, password, "decrypt")
        self._worker.progress_text.connect(self.lbl_status.setText)
        self._worker.progress_value.connect(self.progress_bar.setValue)
        self._worker.finished.connect(self._on_decrypt_done)
        self._worker.start()

    def _on_decrypt_done(self, ok: bool, msg: str) -> None:
        _set_operation(False)
        self._lock_ui(False)

        if ok:
            QMessageBox.information(self, "Déchiffrement réussi",
                                    "Le projet a été déchiffré avec succès.")
            self.accept()
        else:
            QMessageBox.critical(self, "Erreur", f"Déchiffrement échoué :\n{msg}")

    # ── Fermeture ──────────────────────────────────

    def _on_cancel(self) -> None:
        if _is_operation_running():
            reply = QMessageBox.question(
                self, "Annuler ?",
                "Une opération est en cours. Voulez-vous vraiment annuler ?\n"
                "⚠ Annuler en cours de chiffrement peut corrompre les fichiers !",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            # Tenter d'arrêter les workers
            for worker in [self._worker, self._copy_worker]:
                if worker and worker.isRunning():
                    worker.terminate()
                    worker.wait(2000)
            _set_operation(False)
        self.reject()

    def closeEvent(self, event) -> None:
        if _is_operation_running():
            event.ignore()
            self._on_cancel()
        else:
            super().closeEvent(event)


