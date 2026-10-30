"""
Voktora — ui_dialogs.encrypt_dialog
Fragment de ui_dialogs.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

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
_operation_in_progress = False   # une seule opération longue à la fois (chiffrement ou copie)


def _is_operation_running() -> bool:
    return _operation_in_progress



def _set_operation(state: bool) -> None:
    global _operation_in_progress
    _operation_in_progress = state


# ──────────────────────────────────────────────
# WORKER — Chiffrement en arrière-plan
# ──────────────────────────────────────────────


class EncryptWorker(QThread):
    """Chiffre/déchiffre récursivement un dossier dans un thread séparé.

    Chiffrement authentifié AES-256-GCM en flux (voir core.file_crypto) : la mémoire reste
    constante quelle que soit la taille des fichiers, et un mauvais mot de passe est détecté
    avant toute écriture définitive. Annulable proprement via requestInterruption().
    """

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
        self._done     = 0
        self._total    = 1
        self._last_pct = -1

    def run(self) -> None:
        try:
            msg = self._do_encrypt() if self._mode == "encrypt" else self._do_decrypt()
            self.finished.emit(True, msg)
        except core.OperationCancelled:
            self.finished.emit(False, "Opération annulée. Les fichiers déjà traités le sont entièrement ; "
                                      "relancez l'opération pour terminer.")
        except Exception as e:
            self.finished.emit(False, str(e))

    # ── Progression ────────────────────────────────

    def _cancelled(self) -> bool:
        return self.isInterruptionRequested()

    def _advance(self, nbytes: int) -> None:
        self._done += nbytes
        pct = min(99, self._done * 100 // max(self._total, 1))
        if pct != self._last_pct:      # n'émet que si le pourcentage change (pas de saturation de la boucle Qt)
            self._last_pct = pct
            self.progress_value.emit(pct)

    @staticmethod
    def _size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    # ── Chiffrement ────────────────────────────────

    def _do_encrypt(self) -> str:
        files = [f for f in self._path.rglob("*")
                 if f.is_file() and not f.is_symlink() and not f.name.startswith(".")
                 and not core.is_encrypted_name(f)]
        if not files:
            return "Aucun fichier à chiffrer."
        self._total = sum(self._size(f) for f in files) or 1

        self.progress_text.emit("Dérivation de la clé…")
        salt = core.new_salt()
        key  = core.derive_key(self._password, salt)

        failures = 0
        for file_path in files:
            if self._cancelled():
                raise core.OperationCancelled("Opération annulée.")
            self.progress_text.emit(f"Chiffrement : {file_path.name}")
            try:
                core.encrypt_file(file_path, file_path.with_name(file_path.name + core.SUFFIX),
                                  key, salt, self._advance, self._cancelled)
                file_path.unlink()          # l'original n'est supprimé qu'une fois la version chiffrée complète
            except core.OperationCancelled:
                raise
            except Exception as e:
                failures += 1
                self.progress_text.emit(f"⚠ Ignoré : {file_path.name} ({e})")

        (self._path / ".voktora_encrypted").write_text(
            f"Encrypted with Voktora v{core.APP_VERSION}\n"
            f"Format: AES-256-GCM (v2)\n"
            f"Date: {datetime.now().isoformat()}\n",
            encoding="utf-8",
        )
        self.progress_value.emit(100)
        if failures:
            return f"Terminé, mais {failures} fichier(s) n'ont pas pu être chiffrés (ils restent en clair)."
        return "Opération terminée avec succès."

    # ── Déchiffrement ──────────────────────────────

    def _do_decrypt(self) -> str:
        files = [f for f in self._path.rglob("*")
                 if f.is_file() and f.suffix in (core.SUFFIX, *core.LEGACY_SUFFIXES)]
        if not files:
            self.progress_value.emit(100)
            return "Aucun fichier chiffré trouvé."
        self._total = sum(self._size(f) for f in files) or 1

        keys: dict[bytes, bytes] = {}      # sel -> clé (scrypt n'est calculé qu'une fois par sel)
        failures = 0
        legacy = 0
        for file_path in files:
            if self._cancelled():
                raise core.OperationCancelled("Opération annulée.")
            self.progress_text.emit(f"Déchiffrement : {file_path.name}")
            try:
                if file_path.suffix == core.SUFFIX:
                    header = core.read_header(file_path)
                    if header is None:
                        raise core.DecryptionError(f"Format de chiffrement inconnu : {file_path.name}")
                    salt = header[0]
                    if salt not in keys:
                        keys[salt] = core.derive_key(self._password, salt)
                    core.decrypt_file(file_path, file_path.with_suffix(""), keys[salt],
                                      self._advance, self._cancelled)
                else:
                    legacy += 1
                    original = (file_path.with_suffix("") if file_path.suffix == ".menc"
                                else Path(str(file_path)[:-len(".encrypted")]))
                    core.legacy_decrypt_file(file_path, original, self._password,
                                             self._advance, self._cancelled)
                file_path.unlink()
            except core.DecryptionError as e:
                # Mauvais mot de passe : inutile (et dangereux) de continuer sur les autres fichiers.
                raise core.DecryptionError(str(e)) from e
            except core.OperationCancelled:
                raise
            except Exception as e:
                failures += 1
                self.progress_text.emit(f"⚠ Ignoré : {file_path.name} ({e})")

        if not failures:
            (self._path / ".voktora_encrypted").unlink(missing_ok=True)
        self.progress_value.emit(100)
        notes = []
        if failures:
            notes.append(f"{failures} fichier(s) n'ont pas pu être déchiffrés et restent chiffrés.")
        if legacy:
            notes.append(f"{legacy} fichier(s) étaient dans l'ancien format non authentifié : "
                         "vérifiez le résultat, puis rechiffrez le projet pour passer au nouveau format.")
        return "\n".join(notes) or "Opération terminée avec succès."


# ──────────────────────────────────────────────
# WORKER — Copie/backup avec progression
# ──────────────────────────────────────────────


class CopyWorker(QThread):
    """Copie un dossier (sauvegarde) en arrière-plan : atomique, annulable, progression réelle en octets."""

    progress_text  = Signal(str)
    progress_value = Signal(int)
    finished       = Signal(bool, str)

    def __init__(self, src: Path, dst: Path):
        super().__init__()
        self._src = src
        self._dst = dst
        self._last_pct = -1

    def _on_progress(self, done: int, total: int, current: str) -> None:
        pct = min(100, done * 100 // total) if total else 0
        if pct != self._last_pct:
            self._last_pct = pct
            self.progress_value.emit(pct)
            if current:
                self.progress_text.emit(f"Copie : {current}")

    def run(self) -> None:
        try:
            core.copy_tree(self._src, self._dst, self._on_progress, self.isInterruptionRequested)
            self.progress_value.emit(100)
            self.finished.emit(True, f"Copie terminée vers {self._dst}")
        except core.OperationCancelled:
            self.finished.emit(False, "Sauvegarde annulée.")
        except Exception as e:
            self.finished.emit(False, str(e))


# ──────────────────────────────────────────────
# DIALOGUE PRINCIPAL
# ──────────────────────────────────────────────


class EncryptProjectDialog(QDialog):
    """Dialogue pour chiffrer/déchiffrer un projet avec barre de progression."""

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path  = Path(project_path)
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
            algo = "AES-256-GCM (clé dérivée par scrypt)"
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
                "Les fichiers déjà traités restent intacts ; vous pourrez relancer ensuite.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            # Arrêt coopératif : les fichiers sont écrits dans un « .part » puis renommés, donc
            # interrompre entre deux fichiers (ou au milieu d'un bloc) ne corrompt rien.
            for worker in [self._worker, self._copy_worker]:
                if worker and worker.isRunning():
                    worker.requestInterruption()
                    worker.wait(15_000)
            _set_operation(False)
        self.reject()

    def closeEvent(self, event) -> None:
        if _is_operation_running():
            event.ignore()
            self._on_cancel()
        else:
            super().closeEvent(event)


