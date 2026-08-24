"""
Voktora — ui_dialogs.json_config_editor_dialog
Édition directe de config.json en JSON lisible — fonctionnalité avancée,
réservée au dépannage. Une sauvegarde horodatée est créée automatiquement
avant toute écriture.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime

import core
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class JsonConfigEditorDialog(QDialog):
    """Édition manuelle avancée de config.json — réservée au dépannage."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🛠 Éditeur JSON avancé — config.json")
        self.setModal(True)
        self.setMinimumSize(720, 640)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)

        warning = QLabel(
            "⚠️  <b>Fonctionnalité avancée et dangereuse.</b><br>"
            "Ceci modifie directement le fichier de configuration de Voktora. "
            "Une erreur de syntaxe ou une valeur incohérente peut empêcher "
            "l'application de démarrer correctement.<br><br>"
            "N'utilisez cet éditeur <b>qu'en cas de problème</b> que les autres "
            "réglages ne permettent pas de résoudre. Une sauvegarde horodatée "
            "du fichier actuel sera créée automatiquement avant tout "
            "enregistrement."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "background:#3a2323; color:#f38ba8; border:1px solid #f38ba8;"
            " border-radius:6px; padding:10px; font-size:12px;"
        )
        v.addWidget(warning)

        self._editor = QTextEdit()
        self._editor.setFont(QFont("Consolas, Courier New, monospace", 11))
        self._editor.setLineWrapMode(QTextEdit.NoWrap)
        v.addWidget(self._editor, stretch=1)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("font-size: 11px;")
        v.addWidget(self._status_lbl)

        btn_row = QHBoxLayout()
        btn_reload = QPushButton("↺ Recharger depuis le disque")
        btn_reload.clicked.connect(self._reload)
        btn_validate = QPushButton("✓ Valider la syntaxe")
        btn_validate.clicked.connect(self._validate_only)
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("💾 Sauvegarder et appliquer")
        btn_save.setObjectName("danger")
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_reload)
        btn_row.addWidget(btn_validate)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        v.addLayout(btn_row)

        self._reload()

    def _reload(self) -> None:
        cfg = core._load_config()
        self._editor.setPlainText(json.dumps(cfg, indent=2, ensure_ascii=False))
        self._status_lbl.setText(f"Chargé depuis {core.get_config_path()}")
        self._status_lbl.setStyleSheet("font-size: 11px; color:#a6adc8;")

    def _parse(self) -> dict | None:
        try:
            data = json.loads(self._editor.toPlainText())
        except json.JSONDecodeError as e:
            self._status_lbl.setText(f"❌ JSON invalide : {e}")
            self._status_lbl.setStyleSheet("font-size: 11px; color:#f38ba8;")
            return None
        if not isinstance(data, dict):
            self._status_lbl.setText("❌ Le contenu doit être un objet JSON (dict) au premier niveau.")
            self._status_lbl.setStyleSheet("font-size: 11px; color:#f38ba8;")
            return None
        return data

    def _validate_only(self) -> None:
        data = self._parse()
        if data is not None:
            self._status_lbl.setText("✅ Syntaxe JSON valide.")
            self._status_lbl.setStyleSheet("font-size: 11px; color:#a6e3a1;")

    def _save(self) -> None:
        data = self._parse()
        if data is None:
            QMessageBox.warning(
                self, "JSON invalide",
                "Le contenu n'est pas un JSON valide — corrigez la syntaxe avant d'enregistrer."
            )
            return

        if QMessageBox.warning(
            self, "Confirmer l'écrasement de config.json",
            "Cette action va remplacer intégralement le fichier de configuration "
            "par le contenu affiché.\n\nUne sauvegarde sera créée automatiquement. "
            "Continuer ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return

        try:
            cfg_path = core.get_config_path()
            if cfg_path.exists():
                backup_dir = core.get_backups_dir()
                backup_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = backup_dir / f"config_before_manual_edit_{ts}.json"
                shutil.copy2(cfg_path, backup_path)

            core._save_config(data)
            QMessageBox.information(
                self, "Configuration enregistrée",
                "config.json a été mis à jour. Un redémarrage de Voktora est "
                "recommandé pour que tous les changements soient bien pris en compte."
            )
            self.accept()
        except OSError as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'enregistrer :\n{e}")
