"""
ui_project_view.py — Vues projets Voktora
Deux modes d'affichage switchables par l'utilisateur :
  • Liste  : QListWidget classique (compact, rapide)
  • Grille : cartes cliquables avec icône personnalisée, nom, statut, langage

Chaque carte en grille ouvre le panneau détaillé du projet via signal `project_selected`.

Classes publiques :
  ProjectCard        — widget carte individuelle (mode grille)
  ProjectGridView    — vue grille scrollable
  ProjectListView    — vue liste classique avec recherche
  ProjectBrowser     — conteneur switchable liste ↔ grille + barre de contrôle
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore    import Qt, Signal, QSize
from PySide6.QtGui     import QColor, QFont, QIcon, QPixmap, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

import core

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_LANG_COLORS: dict[str, str] = {
    "Python":     "#3572A5",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Rust":       "#dea584",
    "C++":        "#f34b7d",
    "C":          "#555555",
    "Java":       "#b07219",
    "Go":         "#00ADD8",
    "HTML":       "#e34c26",
    "CSS":        "#563d7c",
    "Kotlin":     "#A97BFF",
    "Swift":      "#F05138",
}


def _lang_color(lang: str) -> str:
    return _LANG_COLORS.get(lang, "#6c7086")


def _make_emoji_pixmap(emoji: str, size: int = 48) -> QPixmap:
    """Génère un QPixmap à partir d'un emoji."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    font = QFont()
    font.setPixelSize(int(size * 0.72))
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignCenter, emoji)
    painter.end()
    return pix


# ─────────────────────────────────────────────────────────────────────────────
# ProjectCard — une carte pour le mode grille
# ─────────────────────────────────────────────────────────────────────────────

class ProjectCard(QFrame):
    """
    Carte cliquable représentant un projet en mode grille.
    Affiche : icône, nom, langage, type (instance/intent), statut, couleur custom.
    Signal clicked(path, kind).
    """

    clicked = Signal(str, str)   # path, kind

    _CARD_W = 200
    _CARD_H = 175

    def __init__(self, entry: dict, kind: str, parent=None):
        super().__init__(parent)
        self._entry  = entry
        self._kind   = kind
        self._path   = entry.get("path", "")
        self._active = False

        # Couleur personnalisée de l'entrée (pour la bordure accentuée)
        self._custom_color = entry.get("color", "")

        self.setFixedSize(self._CARD_W, self._CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("projectCard")
        self._apply_style(active=False)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 8)
        v.setSpacing(3)
        v.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        # ── Icône ──
        self._icon_lbl = QLabel()
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        self._icon_lbl.setFixedSize(52, 52)
        self._refresh_icon()
        v.addWidget(self._icon_lbl, alignment=Qt.AlignHCenter)

        # ── Nom ──
        name = entry.get("name", Path(self._path).name)
        self._name_lbl = QLabel(name)
        self._name_lbl.setAlignment(Qt.AlignCenter)
        self._name_lbl.setWordWrap(True)
        self._name_lbl.setStyleSheet(
            "color:#cdd6f4; font-size:12px; font-weight:600; background:transparent;"
        )
        self._name_lbl.setMaximumWidth(self._CARD_W - 20)
        v.addWidget(self._name_lbl)

        # ── Badges ligne 1 : type + langage ──
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        row1.setAlignment(Qt.AlignHCenter)

        # Badge type instance/intent
        kind_text  = "intent" if kind == "intent" else "instance"
        kind_color = "#cba6f7" if kind == "intent" else "#74c7ec"
        kind_fg    = "#1e1e2e"
        lbl_kind = QLabel(kind_text)
        lbl_kind.setStyleSheet(
            f"background:{kind_color}; color:{kind_fg};"
            " border-radius:3px; font-size:9px; padding:1px 5px; font-weight:600;"
        )
        row1.addWidget(lbl_kind)

        # Badge langage
        lang = entry.get("language") or core.guess_project_language(Path(self._path))
        if lang:
            lbl_lang = QLabel(lang)
            lbl_lang.setStyleSheet(
                f"background:{_lang_color(lang)}; color:#fff;"
                " border-radius:3px; font-size:9px; padding:1px 5px;"
            )
            row1.addWidget(lbl_lang)

        v.addLayout(row1)

        # ── Badge ligne 2 : statut ──
        status = entry.get("status", "")
        if status:
            row2 = QHBoxLayout()
            row2.setSpacing(4)
            row2.setAlignment(Qt.AlignHCenter)
            lbl_status = QLabel(status)
            # Couleur selon le statut
            status_lower = status.lower()
            if any(w in status_lower for w in ("actif", "activ", "running", "en cours")):
                s_bg, s_fg = "#a6e3a1", "#1e1e2e"
            elif any(w in status_lower for w in ("pause", "stop", "inactif")):
                s_bg, s_fg = "#fab387", "#1e1e2e"
            elif any(w in status_lower for w in ("archiv", "done", "terminé")):
                s_bg, s_fg = "#45475a", "#cdd6f4"
            else:
                s_bg, s_fg = "#313244", "#a6adc8"
            lbl_status.setStyleSheet(
                f"background:{s_bg}; color:{s_fg};"
                " border-radius:3px; font-size:9px; padding:1px 5px;"
            )
            lbl_status.setAlignment(Qt.AlignCenter)
            row2.addWidget(lbl_status)
            v.addLayout(row2)

        v.addStretch()

    # ── Icône ────────────────────────────────────────────────────────────────

    def _refresh_icon(self) -> None:
        entry   = self._entry
        emoji   = entry.get("emoji", "")
        icon_p  = entry.get("icon_path", "")
        color   = entry.get("color", "#313244") or "#313244"
        name    = entry.get("name", "?")

        if icon_p and Path(icon_p).is_file():
            pix = QPixmap(icon_p).scaled(
                48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._icon_lbl.setPixmap(pix)
        elif emoji:
            self._icon_lbl.setPixmap(_make_emoji_pixmap(emoji, 48))
        else:
            pix = QPixmap(48, 48)
            pix.fill(QColor(color))
            painter = QPainter(pix)
            font = QFont()
            font.setPixelSize(22)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#cdd6f4"))
            painter.drawText(pix.rect(), Qt.AlignCenter, name[0].upper())
            painter.end()
            self._icon_lbl.setPixmap(pix)

    def set_icon_path(self, path: str) -> None:
        self._entry["icon_path"] = path
        self._refresh_icon()

    # ── État sélectionné ─────────────────────────────────────────────────────

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self._apply_style(active)

    def _apply_style(self, active: bool) -> None:
        # Priorité : couleur custom → accent sélection → défaut
        custom = self._custom_color if hasattr(self, "_custom_color") else ""
        if active:
            border = "#89b4fa"
            bg     = "#1e1e2e"
        elif custom:
            border = custom
            bg     = "#181825"
        else:
            border = "#313244"
            bg     = "#181825"

        self.setStyleSheet(
            f"QFrame#projectCard {{"
            f"  background:{bg}; border:2px solid {border};"
            f"  border-radius:10px;"
            f"}}"
            f"QFrame#projectCard:hover {{"
            f"  background:#1e1e2e; border-color:{'#89b4fa' if not active and not custom else border};"
            f"}}"
        )

    # ── Interaction ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._path, self._kind)
        super().mousePressEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# ProjectGridView — grille scrollable de ProjectCard
# ─────────────────────────────────────────────────────────────────────────────

class ProjectGridView(QScrollArea):
    """Vue grille : N cartes par ligne, scrollable."""

    project_selected = Signal(str, str)   # path, kind

    _COLS = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._grid      = QGridLayout(self._container)
        self._grid.setSpacing(16)
        self._grid.setContentsMargins(14, 14, 14, 14)
        self._grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setWidget(self._container)

        self._cards:    list[ProjectCard] = []
        self._active:   ProjectCard | None = None
        self._all_entries: list[tuple[dict, str]] = []

    def populate(self, instances: list[dict], intents: list[dict]) -> None:
        self._all_entries = (
            [(e, "instance") for e in instances] +
            [(e, "intent")   for e in intents]
        )
        self._render(self._all_entries)

    def filter(self, text: str) -> None:
        t = text.strip().lower()
        if not t:
            filtered = self._all_entries
        else:
            filtered = [
                (e, k) for e, k in self._all_entries
                if t in (e.get("name", "") + e.get("path", "")).lower()
            ]
        self._render(filtered)

    def _render(self, entries: list[tuple[dict, str]]) -> None:
        # Clear
        for card in self._cards:
            self._grid.removeWidget(card)
            card.deleteLater()
        self._cards   = []
        self._active  = None

        for i, (entry, kind) in enumerate(entries):
            card = ProjectCard(entry, kind)
            card.clicked.connect(self._on_card_click)
            self._grid.addWidget(card, i // self._COLS, i % self._COLS)
            self._cards.append(card)

    def _on_card_click(self, path: str, kind: str) -> None:
        # Désactiver l'ancienne sélection
        if self._active:
            self._active.set_active(False)
        # Activer la nouvelle
        for card in self._cards:
            if card._path == path:
                card.set_active(True)
                self._active = card
                break
        self.project_selected.emit(path, kind)

    def select(self, path: str) -> None:
        """Sélectionne programmatiquement une carte."""
        for card in self._cards:
            if card._path == path:
                card.set_active(True)
                if self._active and self._active._path != path:
                    self._active.set_active(False)
                self._active = card
                return

    def update_card_icon(self, path: str, icon_path: str) -> None:
        for card in self._cards:
            if card._path == path:
                card.set_icon_path(icon_path)
                break


# ─────────────────────────────────────────────────────────────────────────────
# ProjectListView — liste classique
# ─────────────────────────────────────────────────────────────────────────────

class ProjectListView(QWidget):
    """Vue liste : instances et intents dans deux QListWidgets avec recherche."""

    project_selected = Signal(str, str)   # path, kind

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # Recherche unique
        self._search = QLineEdit()
        self._search.setPlaceholderText("Rechercher…")
        self._search.setObjectName("searchBox")
        self._search.textChanged.connect(self._filter)
        v.addWidget(self._search)

        # Instances
        lbl_i = QLabel("INSTANCES")
        lbl_i.setObjectName("sectionLbl")
        v.addWidget(lbl_i)

        self._inst_list = QListWidget()
        self._inst_list.currentItemChanged.connect(
            lambda cur, _: self._on_sel(cur, "instance")
        )
        v.addWidget(self._inst_list)

        # Intents
        lbl_n = QLabel("INTENTS")
        lbl_n.setObjectName("sectionLbl")
        v.addWidget(lbl_n)

        self._int_list = QListWidget()
        self._int_list.currentItemChanged.connect(
            lambda cur, _: self._on_sel(cur, "intent")
        )
        v.addWidget(self._int_list)

        self._all_instances: list[dict] = []
        self._all_intents:   list[dict] = []

    def populate(self, instances: list[dict], intents: list[dict]) -> None:
        self._all_instances = instances
        self._all_intents   = intents
        self._render(instances, intents)

    def _render(self, instances: list[dict], intents: list[dict]) -> None:
        self._inst_list.clear()
        for e in instances:
            txt  = e.get("name", Path(e["path"]).name)
            em   = e.get("emoji", "")
            disp = f"{em} {txt}" if em else txt
            st   = e.get("status", "")
            if st and st != core.DEFAULT_PROJECT_STATUS:
                disp += f"  [{st}]"
            item = QListWidgetItem(disp)
            item.setData(Qt.UserRole, e["path"])
            if e.get("color"):
                item.setForeground(QColor(e["color"]))
            self._inst_list.addItem(item)

        self._int_list.clear()
        for e in intents:
            txt  = e.get("name", Path(e["path"]).name)
            em   = e.get("emoji", "")
            disp = f"{em} {txt}" if em else txt
            item = QListWidgetItem(disp)
            item.setData(Qt.UserRole, e["path"])
            if e.get("color"):
                item.setForeground(QColor(e["color"]))
            self._int_list.addItem(item)

    def _filter(self, text: str) -> None:
        t = text.strip().lower()
        inst = [e for e in self._all_instances
                if not t or t in (e.get("name","") + e.get("path","")).lower()]
        ints = [e for e in self._all_intents
                if not t or t in (e.get("name","") + e.get("path","")).lower()]
        self._render(inst, ints)

    def _on_sel(self, item: QListWidgetItem | None, kind: str) -> None:
        if item is None:
            return
        # Désélectionner l'autre liste
        if kind == "instance":
            self._int_list.blockSignals(True)
            self._int_list.clearSelection()
            self._int_list.setCurrentItem(None)
            self._int_list.blockSignals(False)
        else:
            self._inst_list.blockSignals(True)
            self._inst_list.clearSelection()
            self._inst_list.setCurrentItem(None)
            self._inst_list.blockSignals(False)
        self.project_selected.emit(item.data(Qt.UserRole), kind)

    def select(self, path: str, kind: str) -> None:
        lst = self._inst_list if kind == "instance" else self._int_list
        for i in range(lst.count()):
            item = lst.item(i)
            if item.data(Qt.UserRole) == path:
                lst.setCurrentItem(item)
                return

    def get_search_widget(self) -> QLineEdit:
        return self._search


# ─────────────────────────────────────────────────────────────────────────────
# ProjectBrowser — conteneur switchable + barre de contrôle
# ─────────────────────────────────────────────────────────────────────────────

class ProjectBrowser(QWidget):
    """
    Panneau latéral complet : barre switch liste/grille + vue active.
    Signal project_selected(path, kind) remonte vers MainWindow.
    """

    project_selected = Signal(str, str)
    create_requested = Signal(str)   # "instance" | "intent"

    _MODE_LIST = "list"
    _MODE_GRID = "grid"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = self._MODE_LIST
        self._instances: list[dict] = []
        self._intents:   list[dict] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # ── Barre switch ──────────────────────────────────────────────────────
        bar = QHBoxLayout()

        lbl = QLabel("Projets")
        lbl.setObjectName("sectionLbl")
        bar.addWidget(lbl)
        bar.addStretch()

        self._btn_list = QToolButton()
        self._btn_list.setText("☰")
        self._btn_list.setToolTip("Vue liste")
        self._btn_list.setCheckable(True)
        self._btn_list.setChecked(True)
        self._btn_list.setFixedSize(28, 28)
        self._btn_list.clicked.connect(lambda: self._switch(self._MODE_LIST))

        self._btn_grid = QToolButton()
        self._btn_grid.setText("⊞")
        self._btn_grid.setToolTip("Vue grille")
        self._btn_grid.setCheckable(True)
        self._btn_grid.setFixedSize(28, 28)
        self._btn_grid.clicked.connect(lambda: self._switch(self._MODE_GRID))

        self._btn_group = QButtonGroup(self)
        self._btn_group.addButton(self._btn_list)
        self._btn_group.addButton(self._btn_grid)
        self._btn_group.setExclusive(True)

        bar.addWidget(self._btn_list)
        bar.addWidget(self._btn_grid)
        v.addLayout(bar)

        # ── Vues ──────────────────────────────────────────────────────────────
        self._list_view = ProjectListView()
        self._list_view.project_selected.connect(self.project_selected)

        self._grid_view = ProjectGridView()
        self._grid_view.project_selected.connect(self.project_selected)

        v.addWidget(self._list_view)
        v.addWidget(self._grid_view)
        self._grid_view.setVisible(False)

        # ── Boutons créer ──────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #313244;")
        v.addWidget(sep)

        row = QHBoxLayout()
        btn_inst = QPushButton("+ Instance")
        btn_inst.setObjectName("primary")
        btn_inst.clicked.connect(lambda: self.create_requested.emit("instance"))
        btn_int  = QPushButton("+ Intent")
        btn_int.setObjectName("subtle")
        btn_int.clicked.connect(lambda: self.create_requested.emit("intent"))
        row.addWidget(btn_inst)
        row.addWidget(btn_int)
        v.addLayout(row)

    # ── Switch de mode ────────────────────────────────────────────────────────

    def _switch(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._list_view.setVisible(mode == self._MODE_LIST)
        self._grid_view.setVisible(mode == self._MODE_GRID)

    # ── Données ───────────────────────────────────────────────────────────────

    def populate(self, instances: list[dict], intents: list[dict]) -> None:
        self._instances = instances
        self._intents   = intents
        self._list_view.populate(instances, intents)
        self._grid_view.populate(instances, intents)

    def select(self, path: str, kind: str) -> None:
        self._list_view.select(path, kind)
        self._grid_view.select(path)

    def get_list_view(self) -> ProjectListView:
        return self._list_view

    def get_grid_view(self) -> ProjectGridView:
        return self._grid_view

    def filter(self, text: str) -> None:
        self._list_view._filter(text)
        self._grid_view.filter(text)
