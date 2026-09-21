"""
Voktora — ui_main.create_dialog
Création d'un projet : nom, emplacement, catégorie, git init et dépôt GitHub.
"""

from __future__ import annotations

import core
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
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
    def __init__(self, parent: QWidget | None = None, default_category: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Créer un projet — Voktora")
        self.setFixedWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("📦  Créer un projet")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(workers._make_sep())

        layout.addWidget(QLabel("Nom :"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("ex: MonProjet")
        layout.addWidget(self.name_edit)

        custom = core.get_storage_config().get("projects_root")
        self.drive_combo = QComboBox()
        self._lbl_drive = QLabel("Disque cible :")
        if custom:
            self._lbl_drive.setText(
                f"Dossier personnalisé : <span style='color:#89dceb'>{custom}</span>")
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

        layout.addWidget(QLabel("Catégorie :"))
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItem("")
        for cat in core.list_categories():
            self.category_combo.addItem(cat["name"])
        self.category_combo.lineEdit().setPlaceholderText("Aucune — tapez un nom pour en créer une")
        if default_category:
            self.category_combo.setCurrentText(default_category)
        layout.addWidget(self.category_combo)

        layout.addWidget(QLabel("Dépôt GitHub (facultatif) :"))
        self.repo_edit = QLineEdit()
        self.repo_edit.setPlaceholderText("https://github.com/organisation/depot")
        layout.addWidget(self.repo_edit)

        self.git_init_check = QCheckBox("Initialiser un dépôt Git dans le dossier")
        layout.addWidget(self.git_init_check)

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

    def _update_preview(self) -> None:
        name = self.name_edit.text().strip() or "<nom>"
        self.preview.setText(str(core.get_projects_root(self.drive_combo.currentText()) / name))

    def _validate(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Voktora", "Le nom ne peut pas être vide.")
            return
        try:
            core.validate_name(name)
        except ValueError as e:
            QMessageBox.warning(self, "Voktora — Nom invalide", str(e))
            return
        repo = self.repo_edit.text().strip()
        if repo:
            try:
                core.validate_clone_url(repo)
            except ValueError as e:
                QMessageBox.warning(self, "Voktora — Dépôt invalide", str(e))
                return
        if (core.get_projects_root(self.drive_combo.currentText()) / name).exists():
            QMessageBox.warning(self, "Voktora", f"Un projet nommé « {name} » existe déjà.")
            return
        self.accept()

    def get_data(self) -> dict:
        """Valeurs saisies, prêtes pour core.create_project(**data)."""
        category = self.category_combo.currentText().strip()
        return {
            "drive": self.drive_combo.currentText(),
            "name": self.name_edit.text().strip(),
            "category": category or None,
            "git_init": self.git_init_check.isChecked(),
            "github_repo": self.repo_edit.text().strip() or None,
        }
