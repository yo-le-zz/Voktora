"""
Voktora — ui_dialogs.emoji_picker_dialog
Sélecteur d'icônes (anciennement « menu d'emoji »), organisé par catégories avec recherche par
mot-clé. Les icônes sont dessinées avec la police Material Design Icons embarquée (voir icons.py) :
elles s'affichent partout, y compris sur les Linux sans police d'emoji.

Le nom de classe `EmojiPickerDialog` est conservé comme alias de `IconPickerDialog`.
La valeur choisie est un identifiant « mdi:nom ».
"""

from __future__ import annotations

import icon_catalog as catalog
import icons
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

_MAX_RAW_RESULTS = 120          # résultats « toute la bibliothèque » affichés pour une recherche


class IconPickerDialog(QDialog):
    """Menu de sélection d'icône par catégories, avec recherche (français, ou nom MDI en anglais)."""

    def __init__(self, parent=None, current: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Choisir une icône")
        self.setModal(True)
        self.setMinimumSize(440, 460)
        self._selected: str | None = None
        self._current = icons.resolve_id(current) or ""

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Rechercher (ex. « securise », « rapide », ou « rocket »)…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        v.addWidget(self._search)

        self._tabs = QTabWidget()
        self._grids: dict[str, QGridLayout] = {}
        for category, entries in catalog.CATEGORIES.items():
            page, grid = self._build_grid_page([(e.id, e.label) for e in entries])
            self._grids[category] = grid
            self._tabs.addTab(page, category)
        v.addWidget(self._tabs, stretch=1)

        self._search_page, self._search_grid = self._build_grid_page([])
        self._tabs.addTab(self._search_page, "Résultats")
        self._search_tab_index = self._tabs.count() - 1
        self._tabs.setTabVisible(self._search_tab_index, False)

        self._none_btn = QPushButton("Aucune icône")
        self._none_btn.clicked.connect(lambda: self._choose(""))
        v.addWidget(self._none_btn)

    def _build_grid_page(self, items: list[tuple[str, str]]) -> tuple[QWidget, QGridLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(4)
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._populate_grid(grid, items)
        scroll.setWidget(container)
        return scroll, grid

    def _populate_grid(self, grid: QGridLayout, items: list[tuple[str, str]]) -> None:
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        cols = 8
        for i, (icon_id, label) in enumerate(items):
            btn = QPushButton()
            btn.setIcon(icons.icon(icon_id))
            btn.setIconSize(QSize(22, 22))
            btn.setFixedSize(40, 40)
            btn.setToolTip(label)
            btn.setCheckable(True)
            btn.setChecked(icon_id == self._current)
            btn.clicked.connect(lambda checked=False, value=icon_id: self._choose(value))
            grid.addWidget(btn, i // cols, i % cols)

    def _on_search(self, text: str) -> None:
        needle = text.strip().lower()
        if not needle:
            self._tabs.setTabVisible(self._search_tab_index, False)
            self._tabs.setCurrentIndex(0)
            return
        matches = [(e.id, e.label) for e in catalog.all_entries()
                   if needle in e.keywords or needle in e.id]
        known = {icon_id for icon_id, _label in matches}
        if len(needle) >= 3:        # recherche dans toute la bibliothèque (noms MDI, en anglais)
            for name in icons.all_glyph_names():
                if needle in name and (catalog.PREFIX + name) not in known:
                    matches.append((catalog.PREFIX + name, name.replace("-", " ")))
                    if len(matches) >= _MAX_RAW_RESULTS:
                        break
        self._populate_grid(self._search_grid, matches)
        self._tabs.setTabVisible(self._search_tab_index, True)
        self._tabs.setCurrentIndex(self._search_tab_index)
        if not matches:
            self._search_grid.addWidget(QLabel("Aucun résultat."), 0, 0)

    def _choose(self, icon_id: str) -> None:
        self._selected = icon_id
        self.accept()

    def get_selected_icon(self) -> str | None:
        """Identifiant choisi (« mdi:… »), « » pour « aucune icône », None si annulé."""
        return self._selected

    get_selected_emoji = get_selected_icon        # nom historique

    @staticmethod
    def pick(parent=None, current: str = "") -> str | None:
        """Ouvre le sélecteur et renvoie l'identifiant choisi, ou None si annulé."""
        dlg = IconPickerDialog(parent, current)
        if dlg.exec() == QDialog.Accepted:
            return dlg.get_selected_icon()
        return None


EmojiPickerDialog = IconPickerDialog


class IconField(QWidget):
    """Champ « icône » : aperçu + bouton de choix. Remplace les anciens champs de saisie d'emoji.

    `text()` renvoie l'identifiant « mdi:… » (ou « » si aucune icône) ; `setText()` accepte aussi un
    emoji enregistré avant la 1.0.5, converti en icône.
    """

    def __init__(self, value: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout
        self._value = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self._button = QPushButton()
        self._button.setFixedSize(40, 40)
        self._button.setIconSize(QSize(24, 24))
        self._button.setToolTip("Choisir une icône")
        self._button.clicked.connect(self._pick)
        clear = QPushButton("Aucune")
        clear.clicked.connect(lambda: self.setText(""))
        row.addWidget(self._button)
        row.addWidget(clear)
        row.addStretch()
        self.setText(value)

    def _pick(self) -> None:
        chosen = IconPickerDialog.pick(self, self._value)
        if chosen is not None:
            self.setText(chosen)

    def setText(self, value: str) -> None:
        self._value = icons.resolve_id(value) or ""
        self._button.setIcon(icons.icon(self._value))
        self._button.setText("" if self._value else "—")

    def text(self) -> str:
        return self._value
