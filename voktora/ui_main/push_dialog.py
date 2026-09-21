"""
Voktora — ui_main.push_dialog
Fragment de ui_main.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

from pathlib import Path

import core
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import workers


class PushDialog(QDialog):
    def __init__(
        self,
        instance_path: Path,
        mode: str = "commit",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._path = instance_path
        self._mode = mode

        title_str = "Push Initial" if mode == "initial" else "Commit & Push"
        self.setWindowTitle(f"{title_str} — Voktora")
        self.setMinimumWidth(520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)

        lbl_title = QLabel(
            f"{'🚀  Push Initial' if mode == 'initial' else '✔  Commit & Push'}"
        )
        lbl_title.setObjectName("appTitle")
        lbl_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_title)
        layout.addWidget(workers._make_sep())

        layout.addWidget(QLabel("Message de commit :"))
        self.msg_edit = QLineEdit()
        if mode == "initial":
            self.msg_edit.setText("Initial commit — Voktora")
        else:
            self.msg_edit.setPlaceholderText(
                "Titre du commit (laissez vide pour un message automatique)"
            )
        layout.addWidget(self.msg_edit)

        lbl_desc = QLabel("Description / corps du commit  (optionnel) :")
        lbl_desc.setObjectName("sectionLbl")
        layout.addWidget(lbl_desc)
        self.desc_edit = QTextEdit()
        self.desc_edit.setObjectName("noteEdit")
        self.desc_edit.setMaximumHeight(72)
        self.desc_edit.setPlaceholderText(
            "Explication détaillée, liste de changements, lien vers issue…"
        )
        layout.addWidget(self.desc_edit)
        layout.addWidget(workers._make_sep())

        lbl_br = QLabel("Branches cibles  (cochez celles où pusher) :")
        layout.addWidget(lbl_br)

        self.branch_list = QListWidget()
        self.branch_list.setMaximumHeight(110)
        saved = core.get_instance_branches(instance_path)
        for br in saved:
            self._add_branch_item(br, checked=True)
        layout.addWidget(self.branch_list)

        add_row = QHBoxLayout()
        self.new_branch_edit = QLineEdit()
        self.new_branch_edit.setPlaceholderText("Nouvelle branche…  ex: release/v2")
        self.new_branch_edit.returnPressed.connect(self._add_branch)
        btn_add = QPushButton("＋  Ajouter")
        btn_add.setFixedWidth(96)
        btn_add.clicked.connect(self._add_branch)
        btn_del = QPushButton("✕  Retirer")
        btn_del.setObjectName("subtle")
        btn_del.setFixedWidth(88)
        btn_del.clicked.connect(self._remove_selected_branch)
        add_row.addWidget(self.new_branch_edit)
        add_row.addWidget(btn_add)
        add_row.addWidget(btn_del)
        layout.addLayout(add_row)

        hint_br = QLabel("💡  Cochez plusieurs branches pour pousser en parallèle séquentiel.")
        hint_br.setObjectName("sectionLbl")
        layout.addWidget(hint_br)
        layout.addWidget(workers._make_sep())

        grp_opts = QGroupBox("⚙  Options de push")
        opts_v = QVBoxLayout(grp_opts)
        opts_v.setSpacing(6)

        self.chk_force = QCheckBox("--force  ⚠  Écraser l'historique distant (push forcé)")
        self.chk_force.setStyleSheet("color: #f38ba8;")
        if mode == "initial":
            self.chk_force.setChecked(True)

        self.chk_follow_tags = QCheckBox("--follow-tags  Inclure les tags annotés lors du push")
        self.chk_no_verify   = QCheckBox("--no-verify  Ignorer les hooks pre-push (ex : linters)")
        self.chk_no_verify.setStyleSheet("color: #fab387;")

        opts_v.addWidget(self.chk_force)
        opts_v.addWidget(self.chk_follow_tags)
        opts_v.addWidget(self.chk_no_verify)
        layout.addWidget(grp_opts)

        layout.addWidget(workers._make_sep())
        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        icon = "🚀" if mode == "initial" else "✔"
        self.btn_ok = QPushButton(f"{icon}  Lancer le push")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.clicked.connect(self._validate)
        btns.addWidget(btn_cancel)
        btns.addStretch()
        btns.addWidget(self.btn_ok)
        layout.addLayout(btns)

    def _add_branch_item(self, name: str, checked: bool = True) -> None:
        for i in range(self.branch_list.count()):
            if self.branch_list.item(i).text() == name:
                return
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.branch_list.addItem(item)

    def _add_branch(self) -> None:
        name = self.new_branch_edit.text().strip()
        if name:
            self._add_branch_item(name, checked=True)
            self.new_branch_edit.clear()

    def _remove_selected_branch(self) -> None:
        row = self.branch_list.currentRow()
        if row >= 0:
            self.branch_list.takeItem(row)

    def get_selected_branches(self) -> list[str]:
        return [
            self.branch_list.item(i).text()
            for i in range(self.branch_list.count())
            if self.branch_list.item(i).checkState() == Qt.Checked
        ]

    def _validate(self) -> None:
        if not self.get_selected_branches():
            QMessageBox.warning(self, "Voktora",
                "Cochez au moins une branche cible avant de lancer le push.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "message":     self.msg_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "branches":    self.get_selected_branches(),
            "force":       self.chk_force.isChecked(),
            "follow_tags": self.chk_follow_tags.isChecked(),
            "no_verify":   self.chk_no_verify.isChecked(),
        }


# ══════════════════════════════════════════════════════
#  DIALOGS PRINCIPAUX
# ══════════════════════════════════════════════════════

