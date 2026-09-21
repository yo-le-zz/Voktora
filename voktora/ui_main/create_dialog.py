"""
Voktora — ui_main.create_dialog
Fragment de ui_main.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

from pathlib import Path

import core
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
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
        layout.addWidget(workers._make_sep())

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

        layout.addWidget(workers._make_sep())

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

