"""
Voktora — ui_main.storage_dialog
Emplacement de stockage des projets.
"""

from __future__ import annotations

from pathlib import Path

import core
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import workers


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
            "Par défaut, les nouveaux projets sont créés dans "
            "<code>{Disque}\\Voktora\\Projects\\</code>.\n\n"
            "Vous pouvez définir ici un chemin fixe, indépendant du disque sélectionné. "
            "Laissez le champ vide pour conserver le comportement par disque.\n"
            "Les projets déjà existants ne sont pas déplacés."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(hint)
        layout.addWidget(workers._make_sep())

        layout.addWidget(QLabel("📦  Dossier racine des projets :"))
        row = QHBoxLayout()
        self.root_edit = QLineEdit(storage.get("projects_root") or "")
        self.root_edit.setPlaceholderText(r"ex: D:\MesProjets  (laisser vide = disque)")
        btn_browse = QPushButton("📂")
        btn_browse.setFixedWidth(36)
        btn_browse.clicked.connect(self._browse)
        btn_clear = QPushButton("✕")
        btn_clear.setObjectName("subtle")
        btn_clear.setFixedWidth(28)
        btn_clear.clicked.connect(self.root_edit.clear)
        row.addWidget(self.root_edit)
        row.addWidget(btn_browse)
        row.addWidget(btn_clear)
        layout.addLayout(row)

        layout.addWidget(workers._make_sep())
        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("✔  Enregistrer")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._validate)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier de stockage")
        if folder:
            self.root_edit.setText(folder)

    def _validate(self) -> None:
        root = self.root_edit.text().strip() or None
        if root and not Path(root).is_absolute():
            QMessageBox.warning(self, "Voktora", "Le chemin doit être absolu.")
            return
        core.set_storage_config(root)
        self.accept()
