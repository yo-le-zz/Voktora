"""
Voktora — ui_dialogs.categories_dialog
Gestion des catégories de projets : création, modification (nom, emoji,
couleur), ordre d'affichage, suppression, et création automatique à partir
des organisations GitHub. Les changements sont enregistrés immédiatement.
"""

from __future__ import annotations

import core
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class CategoryEditor(QDialog):
    """Petit formulaire : nom, emoji, couleur d'une catégorie."""

    def __init__(self, parent: QWidget | None = None, name: str = "", emoji: str = "", color: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Catégorie — Voktora")
        self.setModal(True)
        self.setMinimumWidth(380)
        self._color = color

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(name)
        self.name_edit.setMaxLength(core.MAX_CATEGORY_NAME_LENGTH)
        self.name_edit.setPlaceholderText("ex: Clients, Perso, Open source…")
        self.emoji_edit = QLineEdit(emoji)
        self.emoji_edit.setMaxLength(8)
        self.emoji_edit.setPlaceholderText("📁 (facultatif)")
        form.addRow("Nom :", self.name_edit)
        form.addRow("Emoji :", self.emoji_edit)

        color_row = QHBoxLayout()
        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self._pick_color)
        btn_clear = QPushButton("✕")
        btn_clear.setObjectName("subtle")
        btn_clear.setFixedWidth(28)
        btn_clear.clicked.connect(self._clear_color)
        color_row.addWidget(self.color_btn, 1)
        color_row.addWidget(btn_clear)
        form.addRow("Couleur :", color_row)
        layout.addLayout(form)
        self._refresh_color_button()

        buttons = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("✔  Valider")
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_ok)
        layout.addLayout(buttons)

    def _refresh_color_button(self) -> None:
        if self._color:
            self.color_btn.setText(self._color)
            self.color_btn.setStyleSheet(f"background: {self._color}; color: #11111b;")
        else:
            self.color_btn.setText("Aucune couleur")
            self.color_btn.setStyleSheet("")

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color or "#89b4fa"), self, "Couleur de la catégorie")
        if chosen.isValid():
            self._color = chosen.name()
            self._refresh_color_button()

    def _clear_color(self) -> None:
        self._color = ""
        self._refresh_color_button()

    def values(self) -> tuple[str, str, str]:
        return self.name_edit.text().strip(), self.emoji_edit.text().strip(), self._color


class CategoriesDialog(QDialog):
    """Dialogue pour gérer les catégories de projets."""

    categories_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("📂 Gestion des catégories — Voktora")
        self.setModal(True)
        self.setMinimumSize(520, 520)
        self._dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)

        intro = QLabel(
            "Créez vos propres catégories pour classer vos projets. Un projet appartient à une "
            "catégorie ; vous pouvez aussi les ranger automatiquement selon leur organisation GitHub."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(intro)

        self.categories_list = QListWidget()
        self.categories_list.itemDoubleClicked.connect(lambda _item: self._edit())
        layout.addWidget(self.categories_list, 1)

        row = QHBoxLayout()
        self.btn_add = QPushButton("➕ Nouvelle")
        self.btn_add.clicked.connect(self._add)
        self.btn_edit = QPushButton("✏  Modifier")
        self.btn_edit.clicked.connect(self._edit)
        self.btn_delete = QPushButton("🗑  Supprimer")
        self.btn_delete.clicked.connect(self._delete)
        self.btn_up = QPushButton("↑")
        self.btn_up.setFixedWidth(36)
        self.btn_up.setToolTip("Monter")
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down = QPushButton("↓")
        self.btn_down.setFixedWidth(36)
        self.btn_down.setToolTip("Descendre")
        self.btn_down.clicked.connect(lambda: self._move(1))
        for w in (self.btn_add, self.btn_edit, self.btn_delete, self.btn_up, self.btn_down):
            row.addWidget(w)
        layout.addLayout(row)

        auto = QVBoxLayout()
        self.chk_reclassify = QCheckBox("Inclure les projets qui ont déjà une catégorie")
        self.btn_github = QPushButton("🐙  Créer des catégories depuis les organisations GitHub")
        self.btn_github.clicked.connect(self._from_github)
        auto.addWidget(self.btn_github)
        auto.addWidget(self.chk_reclassify)
        layout.addLayout(auto)

        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

        self._reload()

    # ── affichage ────────────────────────────────

    def _reload(self, select: str | None = None) -> None:
        counts = core.category_counts()
        self.categories_list.clear()
        for cat in core.list_categories():
            n = counts.get(cat["name"], 0)
            item = QListWidgetItem(f"{cat['emoji']} {cat['name']}  —  {n} projet(s)".strip())
            item.setData(Qt.UserRole, cat["name"])
            if cat["color"]:
                item.setForeground(QBrush(QColor(cat["color"])))
            self.categories_list.addItem(item)
            if cat["name"] == select:
                self.categories_list.setCurrentItem(item)
        uncategorized = counts.get(None, 0)
        if uncategorized:
            info = QListWidgetItem(f"— Sans catégorie : {uncategorized} projet(s) —")
            info.setFlags(Qt.NoItemFlags)
            self.categories_list.addItem(info)

    def _selected_name(self) -> str | None:
        item = self.categories_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _changed(self, select: str | None = None) -> None:
        self._dirty = True
        self._reload(select)
        self.categories_changed.emit()

    # ── actions ──────────────────────────────────

    def _add(self) -> None:
        editor = CategoryEditor(self)
        if editor.exec() != QDialog.Accepted:
            return
        name, emoji, color = editor.values()
        try:
            core.add_category(name, emoji, color)
        except ValueError as exc:
            QMessageBox.warning(self, "Voktora", str(exc))
            return
        self._changed(name)

    def _edit(self) -> None:
        name = self._selected_name()
        if not name:
            return
        cat = core.get_category(name)
        editor = CategoryEditor(self, cat["name"], cat["emoji"], cat["color"])
        if editor.exec() != QDialog.Accepted:
            return
        new_name, emoji, color = editor.values()
        try:
            core.update_category(name, new_name=new_name, emoji=emoji, color=color)
        except ValueError as exc:
            QMessageBox.warning(self, "Voktora", str(exc))
            return
        self._changed(new_name)

    def _delete(self) -> None:
        name = self._selected_name()
        if not name:
            return
        count = core.category_counts().get(name, 0)
        detail = (f"Les {count} projet(s) qu'elle contient deviendront « sans catégorie » "
                  "(aucun projet n'est supprimé).") if count else "Elle ne contient aucun projet."
        answer = QMessageBox.question(self, "Voktora — Supprimer la catégorie",
                                      f"Supprimer la catégorie « {name} » ?\n\n{detail}")
        if answer == QMessageBox.Yes:
            core.delete_category(name)
            self._changed()

    def _move(self, offset: int) -> None:
        name = self._selected_name()
        if name:
            core.move_category(name, offset)
            self._changed(name)

    def _from_github(self) -> None:
        assigned = core.categorize_by_github_owner(only_uncategorized=not self.chk_reclassify.isChecked())
        if not assigned:
            QMessageBox.information(
                self, "Voktora",
                "Aucun projet à classer : aucun n'est lié à un dépôt GitHub, ou tous ont déjà une catégorie.")
            return
        detail = "\n".join(f"• {owner} : {n}" for owner, n in sorted(assigned.items()))
        QMessageBox.information(self, "Voktora", f"{sum(assigned.values())} projet(s) classé(s) :\n{detail}")
        self._changed()

    def has_changes(self) -> bool:
        return self._dirty
