"""
Voktora — ui_main.storage_dialog
Fragment de ui_main.py extrait lors du découpage v1.0.2 en package.
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
            "Par défaut, instances et intents sont créés dans\n"
            "<code>{Disque}\\Voktora\\Instances\\</code> et "
            "<code>{Disque}\\Voktora\\Intents\\</code>.\n\n"
            "Vous pouvez définir ici des chemins fixes, indépendants du disque sélectionné.\n"
            "Laissez un champ vide pour conserver le comportement par disque."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(hint)
        layout.addWidget(workers._make_sep())

        layout.addWidget(QLabel("📦  Dossier racine des Instances :"))
        inst_row = QHBoxLayout()
        self.inst_edit = QLineEdit(storage.get("instances_root") or "")
        self.inst_edit.setPlaceholderText(r"ex: D:\MesProjets\Instances  (laisser vide = disque)")
        btn_inst = QPushButton("📂")
        btn_inst.setFixedWidth(36)
        btn_inst.clicked.connect(lambda: self._browse(self.inst_edit))
        btn_inst_clr = QPushButton("✕")
        btn_inst_clr.setObjectName("subtle")
        btn_inst_clr.setFixedWidth(28)
        btn_inst_clr.clicked.connect(lambda: self.inst_edit.clear())
        inst_row.addWidget(self.inst_edit)
        inst_row.addWidget(btn_inst)
        inst_row.addWidget(btn_inst_clr)
        layout.addLayout(inst_row)

        layout.addWidget(QLabel("🧩  Dossier racine des Intents :"))
        int_row = QHBoxLayout()
        self.int_edit = QLineEdit(storage.get("intents_root") or "")
        self.int_edit.setPlaceholderText(r"ex: D:\MesProjets\Intents  (laisser vide = disque)")
        btn_int = QPushButton("📂")
        btn_int.setFixedWidth(36)
        btn_int.clicked.connect(lambda: self._browse(self.int_edit))
        btn_int_clr = QPushButton("✕")
        btn_int_clr.setObjectName("subtle")
        btn_int_clr.setFixedWidth(28)
        btn_int_clr.clicked.connect(lambda: self.int_edit.clear())
        int_row.addWidget(self.int_edit)
        int_row.addWidget(btn_int)
        int_row.addWidget(btn_int_clr)
        layout.addLayout(int_row)

        layout.addWidget(workers._make_sep())

        note = QLabel(
            "⚠  Modifier ces chemins n'affecte que les <b>nouvelles</b> créations.\n"
            "Les instances et intents existants gardent leur emplacement actuel."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #fab387; font-size: 12px;")
        layout.addWidget(note)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("✔  Enregistrer")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self._validate)
        btns.addWidget(btn_cancel)
        btns.addStretch()
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def _browse(self, edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier de stockage")
        if folder:
            edit.setText(folder)

    def _validate(self) -> None:
        inst_root = self.inst_edit.text().strip() or None
        int_root  = self.int_edit.text().strip()  or None

        for path_str, label in [(inst_root, "Instances"), (int_root, "Intents")]:
            if path_str:
                p = Path(path_str)
                if not p.is_absolute():
                    QMessageBox.warning(self, "Voktora",
                        f"Le chemin pour {label} doit être absolu.")
                    return

        core.set_storage_config(inst_root, int_root)
        self.accept()


# ══════════════════════════════════════════════════════
#  DIALOG — DIAGNOSTIC / RÉPARATION (v1.0.1)
# ══════════════════════════════════════════════════════

