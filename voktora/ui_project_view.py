"""
ui_project_view.py — Vues projets Voktora
Version : 1.0.1
Voktora v1.0.1
Deux modes d'affichage switchables :
  • Liste  : QListWidget avec drag-and-drop + recherche + tri
  • Grille : cartes ProjectCard, colonnes dynamiques (2–7), tri, ping

Nouvelles fonctionnalités v1.0.1 :
  - Colonnes dynamiques en grille (s'adapte à la largeur de la fenêtre)
  - Tri multi-critères : Nom, Date, Langage, Statut, Type
  - Ping : indicateur visuel d'accessibilité de chaque projet
  - Drag-and-drop dans la liste pour réordonner (persisté via core.reorder_entries)
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore    import Qt, Signal, QSize, QMimeData, QTimer
from PySide6.QtGui     import QColor, QFont, QIcon, QPixmap, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

import core

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

_CARD_W   = 170
_CARD_H   = 165
_CARD_GAP = 12
_COLS_MIN = 2
_COLS_MAX = 7

_SORT_OPTIONS = [
    ("name_asc",   "Nom A → Z"),
    ("name_desc",  "Nom Z → A"),
    ("date_desc",  "Date (récent)"),
    ("date_asc",   "Date (ancien)"),
    ("lang",       "Langage"),
    ("status",     "Statut"),
    ("type",       "Type"),
]

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


def _make_emoji_pixmap(emoji: str, size: int = 44) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    font = QFont()
    font.setPixelSize(int(size * 0.72))
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignCenter, emoji)
    painter.end()
    return pix


def _sort_key(entry: dict, kind: str, sort: str):
    """Retourne la clé de tri pour une entrée."""
    if sort == "name_asc":
        return (entry.get("name", "").lower(), kind)
    if sort == "name_desc":
        return (entry.get("name", "").lower(), kind)
    if sort in ("date_desc", "date_asc"):
        return entry.get("created", "")
    if sort == "lang":
        return (entry.get("language") or "").lower()
    if sort == "status":
        return (entry.get("status") or "").lower()
    if sort == "type":
        return (0 if kind == "instance" else 1, entry.get("name", "").lower())
    return entry.get("name", "").lower()


def _apply_sort(entries: list[tuple[dict, str]], sort: str) -> list[tuple[dict, str]]:
    reverse = sort in ("name_desc", "date_desc")
    return sorted(entries, key=lambda t: _sort_key(t[0], t[1], sort), reverse=reverse)


# ─────────────────────────────────────────────────────────────────────────────
# ProjectCard — carte individuelle mode grille
# ─────────────────────────────────────────────────────────────────────────────

class ProjectCard(QFrame):
    """
    Carte cliquable représentant un projet.
    Signal clicked(path, kind).
    Point de ping en coin supérieur droit :
      ● gris   = non pingé
      ● vert   = dossier OK + Git
      ● jaune  = dossier OK, pas de Git
      ● rouge  = dossier introuvable
    """

    clicked = Signal(str, str)   # path, kind

    def __init__(self, entry: dict, kind: str, parent=None):
        super().__init__(parent)
        self._entry        = entry
        self._kind         = kind
        self._path         = entry.get("path", "")
        self._active       = False
        self._custom_color = entry.get("color", "") or ""

        self.setFixedSize(_CARD_W, _CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("projectCard")
        self._apply_style(active=False)

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 6)
        v.setSpacing(3)
        v.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        # ── Icône ──
        self._icon_lbl = QLabel()
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        self._icon_lbl.setFixedSize(44, 44)
        self._refresh_icon()
        v.addWidget(self._icon_lbl, alignment=Qt.AlignHCenter)

        # ── Nom ──
        name = entry.get("name", Path(self._path).name)
        self._name_lbl = QLabel(name)
        self._name_lbl.setAlignment(Qt.AlignCenter)
        self._name_lbl.setWordWrap(True)
        self._name_lbl.setStyleSheet(
            "color:#cdd6f4; font-size:11px; font-weight:600; background:transparent;"
        )
        self._name_lbl.setMaximumWidth(_CARD_W - 16)
        v.addWidget(self._name_lbl)

        # ── Badges ligne 1 : type + langage ──
        row1 = QHBoxLayout()
        row1.setSpacing(3)
        row1.setAlignment(Qt.AlignHCenter)

        kind_text  = "intent" if kind == "intent" else "instance"
        kind_color = "#cba6f7" if kind == "intent" else "#74c7ec"
        lbl_kind = QLabel(kind_text)
        lbl_kind.setStyleSheet(
            f"background:{kind_color}; color:#1e1e2e;"
            " border-radius:3px; font-size:8px; padding:1px 4px; font-weight:600;"
        )
        row1.addWidget(lbl_kind)

        lang = entry.get("language") or ""
        if lang:
            lbl_lang = QLabel(lang)
            lbl_lang.setStyleSheet(
                f"background:{_lang_color(lang)}; color:#fff;"
                " border-radius:3px; font-size:8px; padding:1px 4px;"
            )
            row1.addWidget(lbl_lang)
        v.addLayout(row1)

        # ── Badge statut ──
        status = entry.get("status", "")
        if status:
            row2 = QHBoxLayout()
            row2.setAlignment(Qt.AlignHCenter)
            lbl_s = QLabel(status)
            sl = status.lower()
            if any(w in sl for w in ("actif", "activ", "running", "en cours")):
                s_bg, s_fg = "#a6e3a1", "#1e1e2e"
            elif any(w in sl for w in ("pause", "stop", "inactif")):
                s_bg, s_fg = "#fab387", "#1e1e2e"
            elif any(w in sl for w in ("archiv", "done", "terminé", "fini")):
                s_bg, s_fg = "#45475a", "#cdd6f4"
            else:
                s_bg, s_fg = "#313244", "#a6adc8"
            lbl_s.setStyleSheet(
                f"background:{s_bg}; color:{s_fg};"
                " border-radius:3px; font-size:8px; padding:1px 4px;"
            )
            lbl_s.setAlignment(Qt.AlignCenter)
            row2.addWidget(lbl_s)
            v.addLayout(row2)

        v.addStretch()

        # ── Point de ping (coin supérieur droit) ──
        self._ping_dot = QLabel("●", self)
        self._ping_dot.setFixedSize(14, 14)
        self._ping_dot.setAlignment(Qt.AlignCenter)
        self._ping_dot.setStyleSheet(
            "color:#45475a; font-size:10px; background:transparent;"
        )
        self._ping_dot.setToolTip("Cliquer pour vérifier l'accessibilité")
        self._ping_dot.setCursor(Qt.PointingHandCursor)
        self._ping_dot.move(_CARD_W - 16, 4)
        self._ping_dot.mousePressEvent = lambda _: self.ping()

    # ── Ping ─────────────────────────────────────────────────────────────────

    def ping(self) -> None:
        """Vérifie l'accessibilité du dossier et met à jour le point de ping."""
        self._ping_dot.setStyleSheet(
            "color:#89b4fa; font-size:10px; background:transparent;"
        )
        self._ping_dot.setToolTip("Vérification…")

        def _check():
            p = Path(self._path)
            if not p.exists():
                return "red", "❌ Dossier introuvable"
            if (p / ".git").exists():
                return "green", "✅ Dossier OK — dépôt Git présent"
            return "yellow", "⚠️ Dossier OK — pas de dépôt Git"

        def _apply(result):
            color_key, tip = result
            colors = {"green": "#a6e3a1", "yellow": "#f9e2af", "red": "#f38ba8"}
            self._ping_dot.setStyleSheet(
                f"color:{colors[color_key]}; font-size:10px; background:transparent;"
            )
            self._ping_dot.setToolTip(tip)

        t = threading.Thread(target=lambda: _apply(_check()), daemon=True)
        t.start()

    # ── Icône ─────────────────────────────────────────────────────────────────

    def _refresh_icon(self) -> None:
        entry  = self._entry
        emoji  = entry.get("emoji", "")
        icon_p = entry.get("icon_path", "")
        color  = entry.get("color", "#313244") or "#313244"
        name   = entry.get("name", "?")
        if icon_p and Path(icon_p).is_file():
            pix = QPixmap(icon_p).scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._icon_lbl.setPixmap(pix)
        elif emoji:
            self._icon_lbl.setPixmap(_make_emoji_pixmap(emoji, 44))
        else:
            pix = QPixmap(44, 44)
            pix.fill(QColor(color))
            painter = QPainter(pix)
            font = QFont()
            font.setPixelSize(20)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#cdd6f4"))
            painter.drawText(pix.rect(), Qt.AlignCenter, name[0].upper())
            painter.end()
            self._icon_lbl.setPixmap(pix)

    def set_icon_path(self, path: str) -> None:
        self._entry["icon_path"] = path
        self._refresh_icon()

    # ── Sélection ────────────────────────────────────────────────────────────

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self._apply_style(active)

    def _apply_style(self, active: bool) -> None:
        custom = self._custom_color
        if active:
            border, bg = "#89b4fa", "#1e1e2e"
        elif custom:
            border, bg = custom, "#181825"
        else:
            border, bg = "#313244", "#181825"
        hover_border = "#89b4fa" if not active and not custom else border
        self.setStyleSheet(
            f"QFrame#projectCard {{"
            f" background:{bg}; border:2px solid {border}; border-radius:9px;"
            f"}}"
            f"QFrame#projectCard:hover {{"
            f" background:#1e1e2e; border-color:{hover_border};"
            f"}}"
        )

    # ── Interaction ───────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._path, self._kind)
        super().mousePressEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
# ProjectGridView — grille scrollable, colonnes dynamiques
# ─────────────────────────────────────────────────────────────────────────────

class ProjectGridView(QScrollArea):
    """Vue grille : colonnes dynamiques (2–7), tri, ping global."""

    project_selected = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._grid      = QGridLayout(self._container)
        self._grid.setSpacing(_CARD_GAP)
        self._grid.setContentsMargins(12, 12, 12, 12)
        self._grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setWidget(self._container)

        self._cards:           list[ProjectCard]        = []
        self._active:          ProjectCard | None       = None
        self._all_entries:     list[tuple[dict, str]]   = []
        self._current_entries: list[tuple[dict, str]]   = []
        self._cols:            int                      = 3
        self._sort_key:        str                      = "name_asc"

    # ── Colonnes dynamiques ───────────────────────────────────────────────────

    def _calc_cols(self) -> int:
        vw = self.viewport().width() if self.viewport() else self.width()
        cols = max(_COLS_MIN, min(_COLS_MAX,
            (vw - _CARD_GAP) // (_CARD_W + _CARD_GAP)
        ))
        return cols

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        new_cols = self._calc_cols()
        if new_cols != self._cols and self._current_entries:
            self._cols = new_cols
            self._render(self._current_entries)

    # ── Données ───────────────────────────────────────────────────────────────

    def populate(self, instances: list[dict], intents: list[dict]) -> None:
        self._all_entries = (
            [(e, "instance") for e in instances] +
            [(e, "intent")   for e in intents]
        )
        self._apply_and_render(self._all_entries)

    def set_sort(self, sort_key: str) -> None:
        self._sort_key = sort_key
        self._apply_and_render(self._all_entries)

    def filter(self, text: str) -> None:
        t = text.strip().lower()
        if not t:
            filtered = self._all_entries
        else:
            filtered = [
                (e, k) for e, k in self._all_entries
                if t in (e.get("name", "") + e.get("path", "")).lower()
            ]
        self._apply_and_render(filtered)

    def _apply_and_render(self, entries: list[tuple[dict, str]]) -> None:
        sorted_entries = _apply_sort(entries, self._sort_key)
        self._current_entries = sorted_entries
        self._cols = self._calc_cols()
        self._render(sorted_entries)

    def _render(self, entries: list[tuple[dict, str]]) -> None:
        for card in self._cards:
            self._grid.removeWidget(card)
            card.deleteLater()
        self._cards  = []
        self._active = None

        cols = self._cols
        for i, (entry, kind) in enumerate(entries):
            card = ProjectCard(entry, kind)
            card.clicked.connect(self._on_card_click)
            self._grid.addWidget(card, i // cols, i % cols)
            self._cards.append(card)

    # ── Ping global ───────────────────────────────────────────────────────────

    def ping_all(self) -> None:
        for card in self._cards:
            card.ping()

    # ── Sélection ────────────────────────────────────────────────────────────

    def _on_card_click(self, path: str, kind: str) -> None:
        if self._active:
            self._active.set_active(False)
        for card in self._cards:
            if card._path == path:
                card.set_active(True)
                self._active = card
                break
        self.project_selected.emit(path, kind)

    def select(self, path: str) -> None:
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
# ProjectListView — liste classique avec drag-and-drop
# ─────────────────────────────────────────────────────────────────────────────

class ProjectListView(QWidget):
    """
    Vue liste : deux QListWidgets (instances / intents).
    Drag-and-drop interne pour réordonner — persisté via core.reorder_entries().
    """

    project_selected = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Rechercher…")
        self._search.setObjectName("searchBox")
        self._search.textChanged.connect(self._filter)
        v.addWidget(self._search)

        lbl_i = QLabel("INSTANCES")
        lbl_i.setObjectName("sectionLbl")
        v.addWidget(lbl_i)

        self._inst_list = self._make_list("instance")
        v.addWidget(self._inst_list)

        lbl_n = QLabel("INTENTS")
        lbl_n.setObjectName("sectionLbl")
        v.addWidget(lbl_n)

        self._int_list = self._make_list("intent")
        v.addWidget(self._int_list)

        self._all_instances: list[dict] = []
        self._all_intents:   list[dict] = []
        self._sort_key = "name_asc"
        self._reorder_pending_inst = False
        self._reorder_pending_int  = False

    # ── Construction QListWidget avec drag ────────────────────────────────────

    def _make_list(self, kind: str) -> QListWidget:
        lst = QListWidget()
        lst.setDragDropMode(QAbstractItemView.InternalMove)
        lst.setDefaultDropAction(Qt.MoveAction)
        lst.setSelectionMode(QAbstractItemView.SingleSelection)
        lst.currentItemChanged.connect(
            lambda cur, _: self._on_sel(cur, kind)
        )
        # Persistance de l'ordre après drag
        lst.model().rowsMoved.connect(
            lambda *_: self._schedule_reorder(kind)
        )
        return lst

    def _schedule_reorder(self, kind: str) -> None:
        """Déclenche la persistance de l'ordre après un court délai."""
        if kind == "instance":
            self._reorder_pending_inst = True
            QTimer.singleShot(150, lambda: self._persist_reorder("instance"))
        else:
            self._reorder_pending_int = True
            QTimer.singleShot(150, lambda: self._persist_reorder("intent"))

    def _persist_reorder(self, kind: str) -> None:
        lst = self._inst_list if kind == "instance" else self._int_list
        paths = [lst.item(i).data(Qt.UserRole) for i in range(lst.count())]
        try:
            core.reorder_entries(kind, paths)
        except Exception:
            pass

    # ── Données ───────────────────────────────────────────────────────────────

    def populate(self, instances: list[dict], intents: list[dict]) -> None:
        self._all_instances = instances
        self._all_intents   = intents
        self._render(instances, intents)

    def set_sort(self, sort_key: str) -> None:
        self._sort_key = sort_key
        self._filter(self._search.text())

    def _sort_list(self, entries: list[dict], kind: str) -> list[dict]:
        pairs = [(e, kind) for e in entries]
        sorted_pairs = _apply_sort(pairs, self._sort_key)
        return [e for e, _ in sorted_pairs]

    def _render(self, instances: list[dict], intents: list[dict]) -> None:
        # Trier
        inst_sorted = self._sort_list(instances, "instance")
        int_sorted  = self._sort_list(intents, "intent")

        self._inst_list.blockSignals(True)
        self._inst_list.clear()
        for e in inst_sorted:
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
        self._inst_list.blockSignals(False)

        self._int_list.blockSignals(True)
        self._int_list.clear()
        for e in int_sorted:
            txt  = e.get("name", Path(e["path"]).name)
            em   = e.get("emoji", "")
            disp = f"{em} {txt}" if em else txt
            item = QListWidgetItem(disp)
            item.setData(Qt.UserRole, e["path"])
            if e.get("color"):
                item.setForeground(QColor(e["color"]))
            self._int_list.addItem(item)
        self._int_list.blockSignals(False)

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
        other = self._int_list if kind == "instance" else self._inst_list
        other.blockSignals(True)
        other.clearSelection()
        other.setCurrentItem(None)
        other.blockSignals(False)
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

    # ── Ping global ───────────────────────────────────────────────────────────

    def ping_all(self) -> None:
        """Vérifie l'accessibilité de tous les projets (colore les entrées)."""
        def _check_and_color(lst: QListWidget, kind: str):
            for i in range(lst.count()):
                item = lst.item(i)
                path = Path(item.data(Qt.UserRole))
                if not path.exists():
                    item.setForeground(QColor("#f38ba8"))
                    item.setToolTip("❌ Dossier introuvable")
                elif (path / ".git").exists():
                    item.setForeground(QColor("#a6e3a1"))
                    item.setToolTip("✅ Dossier OK — Git présent")
                else:
                    item.setForeground(QColor("#f9e2af"))
                    item.setToolTip("⚠️ Dossier OK — pas de Git")

        def _run():
            _check_and_color(self._inst_list, "instance")
            _check_and_color(self._int_list,  "intent")

        threading.Thread(target=_run, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# ProjectBrowser — conteneur switchable + barre de contrôle
# ─────────────────────────────────────────────────────────────────────────────

class ProjectBrowser(QWidget):
    """
    Panneau latéral complet :
      • Switch liste ↔ grille
      • Tri multi-critères
      • Bouton Ping global
      • Boutons créer Instance / Intent
    """

    project_selected = Signal(str, str)
    create_requested = Signal(str)   # "instance" | "intent"

    _MODE_LIST = "list"
    _MODE_GRID = "grid"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode      = self._MODE_LIST
        self._sort      = "name_asc"
        self._instances: list[dict] = []
        self._intents:   list[dict] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        # ── Barre switch + titre ──────────────────────────────────────────────
        bar = QHBoxLayout()
        bar.setSpacing(4)

        lbl = QLabel("Projets")
        lbl.setObjectName("sectionLbl")
        bar.addWidget(lbl)
        bar.addStretch()

        self._btn_list = QToolButton()
        self._btn_list.setText("☰")
        self._btn_list.setToolTip("Vue liste  (glisser pour réordonner)")
        self._btn_list.setCheckable(True)
        self._btn_list.setChecked(True)
        self._btn_list.setFixedSize(26, 26)
        self._btn_list.clicked.connect(lambda: self._switch(self._MODE_LIST))

        self._btn_grid = QToolButton()
        self._btn_grid.setText("⊞")
        self._btn_grid.setToolTip("Vue grille  (colonnes dynamiques)")
        self._btn_grid.setCheckable(True)
        self._btn_grid.setFixedSize(26, 26)
        self._btn_grid.clicked.connect(lambda: self._switch(self._MODE_GRID))

        grp = QButtonGroup(self)
        grp.addButton(self._btn_list)
        grp.addButton(self._btn_grid)
        grp.setExclusive(True)
        bar.addWidget(self._btn_list)
        bar.addWidget(self._btn_grid)
        v.addLayout(bar)

        # ── Barre tri + ping ──────────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(4)

        self._sort_combo = QComboBox()
        self._sort_combo.setToolTip("Trier les projets")
        self._sort_combo.setFixedHeight(24)
        for key, label in _SORT_OPTIONS:
            self._sort_combo.addItem(label, key)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_change)
        ctrl.addWidget(self._sort_combo, stretch=1)

        self._btn_ping = QToolButton()
        self._btn_ping.setText("⬤")
        self._btn_ping.setToolTip("Ping — vérifier l'accessibilité de tous les projets")
        self._btn_ping.setFixedSize(26, 24)
        self._btn_ping.setStyleSheet("color:#45475a;")
        self._btn_ping.clicked.connect(self._ping_all)
        ctrl.addWidget(self._btn_ping)

        v.addLayout(ctrl)

        # ── Vues ──────────────────────────────────────────────────────────────
        self._list_view = ProjectListView()
        self._list_view.project_selected.connect(self.project_selected)

        self._grid_view = ProjectGridView()
        self._grid_view.project_selected.connect(self.project_selected)

        v.addWidget(self._list_view)
        v.addWidget(self._grid_view)
        self._grid_view.setVisible(False)

        # ── Séparateur + boutons créer ────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #313244;")
        v.addWidget(sep)

        row = QHBoxLayout()
        btn_inst = QPushButton("+ Instance")
        btn_inst.setObjectName("primary")
        btn_inst.clicked.connect(lambda: self.create_requested.emit("instance"))
        btn_int = QPushButton("+ Intent")
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

    # ── Tri ───────────────────────────────────────────────────────────────────

    def _on_sort_change(self, _idx: int) -> None:
        self._sort = self._sort_combo.currentData() or "name_asc"
        self._list_view.set_sort(self._sort)
        self._grid_view.set_sort(self._sort)

    # ── Ping ──────────────────────────────────────────────────────────────────

    def _ping_all(self) -> None:
        self._btn_ping.setStyleSheet("color:#89b4fa;")
        self._list_view.ping_all()
        self._grid_view.ping_all()
        QTimer.singleShot(3000, lambda: self._btn_ping.setStyleSheet("color:#45475a;"))

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
