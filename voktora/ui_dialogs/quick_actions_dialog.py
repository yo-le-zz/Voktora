"""
Voktora — ui_dialogs.quick_actions_dialog
Éditeur d'actions rapides : ajouter, MODIFIER, supprimer, réordonner, choisir l'icône dans le menu d'icônes,
tester, et ajouter en un clic les programmes détectés sur la machine.
"""

from __future__ import annotations

import icons
import quick_actions as qa
from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class QuickActionEditDialog(QDialog):
    """Formulaire d'une action (création ou modification)."""

    def __init__(self, parent=None, action: qa.QuickAction | None = None):
        super().__init__(parent)
        self.setWindowTitle("Modifier l'action rapide" if action else "Nouvelle action rapide")
        self.setMinimumWidth(460)
        self._icon = action.icon if action else qa.DEFAULT_ICON

        form = QFormLayout()
        self.name = QLineEdit(action.name if action else "")
        self.name.setPlaceholderText("VS Code")
        self.cmd = QLineEdit(action.cmd if action else "")
        self.cmd.setPlaceholderText("code {path}")
        self.terminal = QCheckBox("Lancer dans un terminal")
        self.terminal.setChecked(bool(action and action.terminal))
        self.btn_icon = QPushButton(" Choisir une icône…")
        self.btn_icon.setMinimumHeight(34)
        self.btn_icon.clicked.connect(self._pick_icon)
        self._show_icon()
        form.addRow("Nom :", self.name)
        form.addRow("Commande :", self.cmd)
        form.addRow("Icône :", self.btn_icon)
        form.addRow("", self.terminal)

        hint = QLabel("{path} = dossier du projet, {name} = nom du projet. Aucun shell n'est utilisé.")
        hint.setStyleSheet("color:#6c7086; font-size:11px;")
        hint.setWordWrap(True)
        self.error = QLabel("")
        self.error.setStyleSheet("color:#f38ba8;")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)
        root.addLayout(form)
        root.addWidget(hint)
        root.addWidget(self.error)
        root.addWidget(buttons)

    def _show_icon(self) -> None:
        self.btn_icon.setIcon(icons.icon(self._icon))
        self.btn_icon.setIconSize(QSize(20, 20))

    def _pick_icon(self) -> None:
        from ui_dialogs.emoji_picker_dialog import IconPickerDialog
        chosen = IconPickerDialog.pick(self, self._icon)
        if chosen:
            self._icon = chosen
            self._show_icon()

    def _accept(self) -> None:
        self._result = qa.QuickAction(self.name.text().strip(), self.cmd.text().strip(), self._icon,
                                      self.terminal.isChecked())
        problem = qa.validate(self._result)
        if problem:
            self.error.setText(problem)
            return
        self.accept()

    def result_action(self) -> qa.QuickAction:
        return self._result


class QuickActionsDialog(QDialog):
    """Liste des actions rapides + boutons d'édition."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Actions rapides")
        self.setMinimumSize(520, 420)
        self._actions = qa.load()

        self._list = QListWidget()
        self._list.setIconSize(QSize(20, 20))
        self._list.itemDoubleClicked.connect(lambda *_: self._edit())
        self._list.currentRowChanged.connect(self._sync_buttons)

        def button(label: str, slot, icon: str = "") -> QPushButton:
            b = QPushButton(label)
            if icon:
                b.setIcon(icons.icon(icon))
            b.clicked.connect(slot)
            return b

        self.btn_add = button(" Ajouter", self._add, "mdi:plus")
        self.btn_edit = button(" Modifier", self._edit, "mdi:pencil")
        self.btn_remove = button(" Supprimer", self._remove, "mdi:delete-outline")
        self.btn_up = button("", lambda: self._move(-1), "mdi:arrow-up")
        self.btn_down = button("", lambda: self._move(1), "mdi:arrow-down")
        self.btn_up.setToolTip("Monter")
        self.btn_down.setToolTip("Descendre")
        self.btn_suggest = button(" Ajouter les programmes détectés", self._add_detected, "mdi:magnify")

        side = QVBoxLayout()
        for b in (self.btn_add, self.btn_edit, self.btn_remove, self.btn_up, self.btn_down):
            side.addWidget(b)
        side.addStretch()
        top = QHBoxLayout()
        top.addWidget(self._list, 1)
        top.addLayout(side)

        close = QPushButton("Fermer")
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_suggest)
        bottom.addStretch()
        bottom.addWidget(close)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.addWidget(QLabel("Ces actions apparaissent dans l'onglet « Actions » de chaque projet."))
        root.addLayout(top, 1)
        root.addLayout(bottom)
        self._refresh()

    def _refresh(self, select: int = -1) -> None:
        self._list.clear()
        for action in self._actions:
            item = QListWidgetItem(icons.icon(action.icon), f"{action.name}   —   {action.cmd}")
            self._list.addItem(item)
        if self._actions:
            self._list.setCurrentRow(min(max(select, 0), len(self._actions) - 1))
        self._sync_buttons()

    def _sync_buttons(self, *_args) -> None:
        row, count = self._list.currentRow(), len(self._actions)
        for b in (self.btn_edit, self.btn_remove):
            b.setEnabled(row >= 0)
        self.btn_up.setEnabled(row > 0)
        self.btn_down.setEnabled(0 <= row < count - 1)

    def _persist(self) -> None:
        qa.save(self._actions)

    def _add(self) -> None:
        dlg = QuickActionEditDialog(self)
        while dlg.exec() == QDialog.Accepted:
            action = dlg.result_action()
            problem = qa.validate(action, self._actions)
            if problem:
                dlg.error.setText(problem)
                continue
            self._actions.append(action)
            self._persist()
            self._refresh(len(self._actions) - 1)
            return

    def _edit(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        dlg = QuickActionEditDialog(self, self._actions[row])
        while dlg.exec() == QDialog.Accepted:
            action = dlg.result_action()
            problem = qa.validate(action, self._actions[:row] + self._actions[row + 1:])
            if problem:
                dlg.error.setText(problem)
                continue
            self._actions[row] = action
            self._persist()
            self._refresh(row)
            return

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        if QMessageBox.question(self, "Supprimer", f"Supprimer « {self._actions[row].name} » ?") == QMessageBox.Yes:
            del self._actions[row]
            self._persist()
            self._refresh(row)

    def _move(self, delta: int) -> None:
        row, target = self._list.currentRow(), self._list.currentRow() + delta
        if row < 0 or not 0 <= target < len(self._actions):
            return
        self._actions[row], self._actions[target] = self._actions[target], self._actions[row]
        self._persist()
        self._refresh(target)

    def _add_detected(self) -> None:
        known = {a.name.casefold() for a in self._actions}
        new = [a for a in qa.suggestions() if a.name.casefold() not in known]
        if not new:
            QMessageBox.information(self, "Actions rapides", "Aucun nouveau programme détecté.")
            return
        self._actions.extend(new)
        self._persist()
        self._refresh(len(self._actions) - 1)
