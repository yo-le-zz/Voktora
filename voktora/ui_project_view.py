"""
ui_project_view.py — Vues projets Voktora
Trois éléments :
  • ProjectListView : arbre regroupable (catégorie, organisation GitHub,
    langage, statut) avec glisser-déposer : sur un groupe pour classer les
    projets, entre deux projets pour les réordonner ;
  • ProjectGridView : cartes ProjectCard rangées par sections, colonnes dynamiques ;
  • ProjectBrowser  : conteneur — recherche partagée, regroupement, tri, ping,
    menu contextuel « Catégorie », boutons créer / importer / cloner.

Toute la logique de tri/regroupement/recherche vit dans core.organize (pure et
testée) ; ce module ne fait que l'afficher.
"""

from __future__ import annotations

import threading
from pathlib import Path

import core
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

_CARD_W   = 170
_CARD_H   = 165
_CARD_GAP = 12
_COLS_MIN = 2
_COLS_MAX = 9

_ROLE_PATH  = Qt.UserRole          # chemin d'un projet
_ROLE_GROUP = Qt.UserRole + 1      # (clé de groupe,) pour un en-tête de groupe
_NO_GROUP   = "\x00none"           # marqueur : « groupe sans valeur »

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


def _status_labels() -> dict[str, str]:
    """Identifiant de statut → « emoji nom » (statuts intégrés + personnalisés)."""
    return {s.id: f"{s.emoji} {s.name}" for s in core.get_all_project_statuses().values()}


def _group_title(group, count: int | None = None) -> str:
    icon = f"{group.emoji} " if group.emoji else ""
    n = len(group.entries) if count is None else count
    return f"{icon}{group.label}  ({n})"


def _visible_groups(entries: list[dict], group_by: str, sort: str, filtering: bool):
    """Groupes à afficher, ou None pour un affichage à plat (un seul groupe sans intérêt)."""
    ordered = core.sort_entries(entries, sort)
    groups = core.group_entries(
        ordered, group_by,
        categories=core.list_categories(),
        status_labels=_status_labels(),
        include_empty_categories=not filtering,
    )
    only_empty_group = len(groups) == 1 and groups[0].key is None
    if group_by == "none" or only_empty_group:
        return None, ordered
    return groups, ordered


def _compute_ping(path: str) -> tuple[str, str]:
    p = Path(path)
    if not p.exists():
        return "red", "❌ Dossier introuvable"
    if (p / ".git").exists():
        return "green", "✅ Dossier OK — dépôt Git présent"
    return "yellow", "⚠️ Dossier OK — pas de dépôt Git"


_PING_COLORS = {"green": "#a6e3a1", "yellow": "#f9e2af", "red": "#f38ba8"}


# ─────────────────────────────────────────────────────────────────────────────
# ProjectCard — carte individuelle mode grille
# ─────────────────────────────────────────────────────────────────────────────

class ProjectCard(QFrame):
    """
    Carte cliquable représentant un projet.
    Signal clicked(path) ; context_requested(path, position globale).
    Point de ping en coin supérieur droit :
      ● gris   = non pingé
      ● vert   = dossier OK + Git
      ● jaune  = dossier OK, pas de Git
      ● rouge  = dossier introuvable
    """

    clicked = Signal(str)
    context_requested = Signal(str, QPoint)
    _ping_finished = Signal(str, str)   # émis depuis un thread → traité dans le thread GUI

    def __init__(self, entry: dict, category_color: str = "", parent=None):
        super().__init__(parent)
        self._entry        = entry
        self._path         = entry.get("path", "")
        self._active       = False
        self._custom_color = entry.get("color", "") or ""

        self.setFixedSize(_CARD_W, _CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("projectCard")
        self._apply_style(active=False)
        self._ping_finished.connect(self._apply_ping)

        tags = entry.get("tags") or []
        tip = []
        if tags:
            tip.append("Tags : " + ", ".join(tags))
        owner = core.github_owner(entry.get("github_repo"))
        if owner:
            tip.append(f"GitHub : {owner}")
        if tip:
            self.setToolTip("\n".join(tip))

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 6)
        v.setSpacing(3)
        v.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        self._icon_lbl = QLabel()
        self._icon_lbl.setAlignment(Qt.AlignCenter)
        self._icon_lbl.setFixedSize(44, 44)
        self._refresh_icon()
        v.addWidget(self._icon_lbl, alignment=Qt.AlignHCenter)

        name = entry.get("name", Path(self._path).name)
        self._name_lbl = QLabel(name)
        self._name_lbl.setAlignment(Qt.AlignCenter)
        self._name_lbl.setWordWrap(True)
        self._name_lbl.setStyleSheet(
            "color:#cdd6f4; font-size:11px; font-weight:600; background:transparent;"
        )
        self._name_lbl.setMaximumWidth(_CARD_W - 16)
        v.addWidget(self._name_lbl)

        # ── Badges : catégorie + langage ──
        row1 = QHBoxLayout()
        row1.setSpacing(3)
        row1.setAlignment(Qt.AlignHCenter)

        category = entry.get("category") or ""
        if category:
            lbl_cat = QLabel(category)
            lbl_cat.setStyleSheet(
                f"background:{category_color or '#74c7ec'}; color:#1e1e2e;"
                " border-radius:3px; font-size:8px; padding:1px 4px; font-weight:600;"
            )
            row1.addWidget(lbl_cat)

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
        status_id = entry.get("status", "")
        if status_id:
            status = core.get_project_status_by_id(status_id)
            text = f"{status.emoji} {status.name}" if status else status_id
            row2 = QHBoxLayout()
            row2.setAlignment(Qt.AlignHCenter)
            lbl_s = QLabel(text)
            sl = text.lower()
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

        self._ping_dot = QLabel("●", self)
        self._ping_dot.setFixedSize(14, 14)
        self._ping_dot.setAlignment(Qt.AlignCenter)
        self._ping_dot.setStyleSheet("color:#45475a; font-size:10px; background:transparent;")
        self._ping_dot.setToolTip("Cliquer pour vérifier l'accessibilité")
        self._ping_dot.setCursor(Qt.PointingHandCursor)
        self._ping_dot.move(_CARD_W - 16, 4)
        self._ping_dot.mousePressEvent = lambda _: self.ping()

    # ── Ping (calcul en thread, affichage dans le thread GUI) ─────────────────

    def ping(self) -> None:
        self._ping_dot.setStyleSheet("color:#89b4fa; font-size:10px; background:transparent;")
        self._ping_dot.setToolTip("Vérification…")

        def _work() -> None:
            color_key, tip = _compute_ping(self._path)
            try:
                self._ping_finished.emit(color_key, tip)
            except RuntimeError:
                pass  # carte détruite entre-temps (re-rendu de la grille)

        threading.Thread(target=_work, daemon=True).start()

    def _apply_ping(self, color_key: str, tip: str) -> None:
        self._ping_dot.setStyleSheet(
            f"color:{_PING_COLORS[color_key]}; font-size:10px; background:transparent;")
        self._ping_dot.setToolTip(tip)

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
            self.clicked.emit(self._path)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.context_requested.emit(self._path, event.globalPos())


# ─────────────────────────────────────────────────────────────────────────────
# ProjectGridView — grille scrollable par sections, colonnes dynamiques
# ─────────────────────────────────────────────────────────────────────────────

class ProjectGridView(QScrollArea):
    """Vue grille : sections repliables, colonnes dynamiques (2–9), ping global."""

    project_selected  = Signal(str)
    context_requested = Signal(str, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._layout    = QVBoxLayout(self._container)
        self._layout.setSpacing(6)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setAlignment(Qt.AlignTop)
        self.setWidget(self._container)

        self._cards:        list[ProjectCard] = []
        self._active_path:  str               = ""
        self._all_entries:  list[dict]        = []
        self._cols:         int               = 3
        self._sort_key:     str               = core.DEFAULT_SORT
        self._group_by:     str               = core.DEFAULT_GROUP
        self._filter_text:  str               = ""
        self._collapsed:    set[str]          = set()

    # ── Colonnes dynamiques ───────────────────────────────────────────────────

    def _calc_cols(self) -> int:
        vw = self.viewport().width() if self.viewport() else self.width()
        return max(_COLS_MIN, min(_COLS_MAX, (vw - _CARD_GAP) // (_CARD_W + _CARD_GAP)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        new_cols = self._calc_cols()
        if new_cols != self._cols and self._all_entries:
            self._cols = new_cols
            self._render()

    # ── Données ───────────────────────────────────────────────────────────────

    def populate(self, entries: list[dict]) -> None:
        self._all_entries = list(entries)
        self._render()

    def set_sort(self, sort_key: str) -> None:
        self._sort_key = sort_key
        self._render()

    def set_group_by(self, group_by: str) -> None:
        self._group_by = group_by
        self._render()

    def filter(self, text: str) -> None:
        self._filter_text = text
        self._render()

    def _filtered(self) -> list[dict]:
        needle = self._filter_text.strip().lower()
        if not needle:
            return self._all_entries
        return [e for e in self._all_entries if core.entry_matches(e, needle)]

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # setParent(None) : le widget disparaît tout de suite, sans attendre le
                # deleteLater (sinon d'anciennes cartes restent visibles sous les nouvelles).
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._cards = []

    def _render(self) -> None:
        self._clear()
        self._cols = self._calc_cols()
        filtering = bool(self._filter_text.strip())
        groups, ordered = _visible_groups(self._filtered(), self._group_by, self._sort_key, filtering)
        colors = {c["name"].lower(): c["color"] for c in core.list_categories()}

        if groups is None:
            self._layout.addWidget(self._make_grid(ordered, colors))
            return
        for group in groups:
            gkey = f"{self._group_by}:{group.key}"
            header = QPushButton(self._header_text(group, gkey))
            header.setObjectName("sectionLbl")
            header.setFlat(True)
            header.setCursor(Qt.PointingHandCursor)
            header.setStyleSheet("text-align:left; font-weight:600; padding:4px 2px;"
                                 + (f"color:{group.color};" if group.color else ""))
            body = self._make_grid(group.entries, colors)
            body.setVisible(gkey not in self._collapsed)
            header.clicked.connect(lambda _=False, b=body, h=header, g=group, k=gkey: self._toggle(b, h, g, k))
            self._layout.addWidget(header)
            self._layout.addWidget(body)

    def _header_text(self, group, gkey: str) -> str:
        arrow = "▸" if gkey in self._collapsed else "▾"
        return f"{arrow}  {_group_title(group)}"

    def _toggle(self, body: QWidget, header: QPushButton, group, gkey: str) -> None:
        if gkey in self._collapsed:
            self._collapsed.discard(gkey)
        else:
            self._collapsed.add(gkey)
        body.setVisible(gkey not in self._collapsed)
        header.setText(self._header_text(group, gkey))

    def _make_grid(self, entries: list[dict], colors: dict[str, str]) -> QWidget:
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setSpacing(_CARD_GAP)
        grid.setContentsMargins(0, 0, 0, 6)
        grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        for i, entry in enumerate(entries):
            card = ProjectCard(entry, colors.get((entry.get("category") or "").lower(), ""))
            card.clicked.connect(self._on_card_click)
            card.context_requested.connect(self.context_requested)
            card.set_active(entry.get("path") == self._active_path)
            grid.addWidget(card, i // self._cols, i % self._cols)
            self._cards.append(card)
        return holder

    # ── Ping global ───────────────────────────────────────────────────────────

    def ping_all(self) -> None:
        for card in self._cards:
            card.ping()

    # ── Sélection ────────────────────────────────────────────────────────────

    def _on_card_click(self, path: str) -> None:
        self.select(path)
        self.project_selected.emit(path)

    def select(self, path: str) -> None:
        self._active_path = path
        for card in self._cards:
            card.set_active(card._path == path)

    def update_card_icon(self, path: str, icon_path: str) -> None:
        for card in self._cards:
            if card._path == path:
                card.set_icon_path(icon_path)
                break


# ─────────────────────────────────────────────────────────────────────────────
# ProjectListView — arbre groupé avec glisser-déposer
# ─────────────────────────────────────────────────────────────────────────────

class _ProjectTree(QTreeWidget):
    """QTreeWidget qui ne déplace jamais rien lui-même : un dépôt est
    traduit en signal, l'appelant met à jour les données puis re-rend l'arbre."""

    projects_dropped = Signal(list, object, object)   # chemins, clé de groupe, chemin « avant »

    def dropEvent(self, event) -> None:
        moved = [it.data(0, _ROLE_PATH) for it in self.selectedItems() if it.data(0, _ROLE_PATH)]
        target = self.itemAt(event.position().toPoint())
        event.ignore()
        if not moved or target is None:
            return

        indicator = self.dropIndicatorPosition()
        if target.data(0, _ROLE_PATH):                      # déposé sur / entre des projets
            parent = target.parent()
            group_key = parent.data(0, _ROLE_GROUP)[0] if parent is not None else _NO_GROUP
            siblings = parent if parent is not None else self.invisibleRootItem()
            index = siblings.indexOfChild(target)
            if indicator == QAbstractItemView.BelowItem:
                index += 1
            before = siblings.child(index).data(0, _ROLE_PATH) if index < siblings.childCount() else None
            self.projects_dropped.emit(moved, group_key, before)
        else:                                               # déposé sur un en-tête de groupe
            self.projects_dropped.emit(moved, target.data(0, _ROLE_GROUP)[0], None)


class ProjectListView(QWidget):
    """Vue liste : arbre regroupé. Glisser des projets sur un groupe les y classe."""

    project_selected  = Signal(str)
    context_requested = Signal(list, QPoint)
    projects_dropped  = Signal(list, object, object)
    _ping_finished    = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self._tree = _ProjectTree()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._tree.setDragEnabled(True)
        self._tree.setAcceptDrops(True)
        self._tree.setDropIndicatorShown(True)
        self._tree.setDragDropMode(QAbstractItemView.DragDrop)
        self._tree.setDefaultDropAction(Qt.MoveAction)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.currentItemChanged.connect(self._on_current_changed)
        self._tree.itemCollapsed.connect(lambda it: self._remember(it, True))
        self._tree.itemExpanded.connect(lambda it: self._remember(it, False))
        self._tree.projects_dropped.connect(self.projects_dropped)
        v.addWidget(self._tree)

        self._ping_finished.connect(self._apply_ping)
        self._all_entries: list[dict] = []
        self._sort_key    = core.DEFAULT_SORT
        self._group_by    = core.DEFAULT_GROUP
        self._search_text = ""
        self._collapsed:  set[str] = set()
        self._selected_path = ""
        self._ping_results: dict[str, tuple[str, str]] = {}

    # ── Données ───────────────────────────────────────────────────────────────

    def populate(self, entries: list[dict]) -> None:
        self._all_entries = list(entries)
        self._render()

    def set_sort(self, sort_key: str) -> None:
        self._sort_key = sort_key
        self._render()

    def set_group_by(self, group_by: str) -> None:
        self._group_by = group_by
        self._render()

    def filter(self, text: str) -> None:
        """Filtre par texte (nom, chemin, catégorie, organisation GitHub ou tags)."""
        self._search_text = text
        self._render()

    def _filtered(self) -> list[dict]:
        needle = self._search_text.strip().lower()
        if not needle:
            return self._all_entries
        return [e for e in self._all_entries if core.entry_matches(e, needle)]

    def _make_project_item(self, entry: dict) -> QTreeWidgetItem:
        name = entry.get("name", Path(entry["path"]).name)
        emoji = entry.get("emoji", "")
        text = f"{emoji} {name}" if emoji else name
        status_id = entry.get("status", "")
        if status_id and status_id != core.DEFAULT_PROJECT_STATUS:
            status = core.get_project_status_by_id(status_id)
            text += f"  [{status.name if status else status_id}]"
        item = QTreeWidgetItem([text])
        item.setData(0, _ROLE_PATH, entry["path"])
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
        if entry.get("color"):
            item.setForeground(0, QColor(entry["color"]))
        if entry["path"] in self._ping_results:
            self._paint_ping(item, *self._ping_results[entry["path"]])
        return item

    def _render(self) -> None:
        tree = self._tree
        tree.blockSignals(True)
        tree.clear()
        filtering = bool(self._search_text.strip())
        groups, ordered = _visible_groups(self._filtered(), self._group_by, self._sort_key, filtering)

        if groups is None:
            for entry in ordered:
                tree.addTopLevelItem(self._make_project_item(entry))
        else:
            for group in groups:
                header = QTreeWidgetItem([_group_title(group)])
                header.setData(0, _ROLE_GROUP, (group.key if group.key is not None else _NO_GROUP,))
                header.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled)
                font = header.font(0)
                font.setBold(True)
                header.setFont(0, font)
                if group.color:
                    header.setForeground(0, QColor(group.color))
                tree.addTopLevelItem(header)
                for entry in group.entries:
                    header.addChild(self._make_project_item(entry))
                header.setExpanded(f"{self._group_by}:{group.key}" not in self._collapsed)
        tree.blockSignals(False)
        if self._selected_path:
            self._select_item(self._selected_path)

    def _remember(self, item: QTreeWidgetItem, collapsed: bool) -> None:
        data = item.data(0, _ROLE_GROUP)
        if data is None:
            return
        key = f"{self._group_by}:{None if data[0] == _NO_GROUP else data[0]}"
        if collapsed:
            self._collapsed.add(key)
        else:
            self._collapsed.discard(key)

    # ── Sélection ────────────────────────────────────────────────────────────

    def _on_current_changed(self, current: QTreeWidgetItem | None, _prev) -> None:
        if current is None or not current.data(0, _ROLE_PATH):
            return
        self._selected_path = current.data(0, _ROLE_PATH)
        self.project_selected.emit(self._selected_path)

    def _iter_project_items(self):
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            top = root.child(i)
            if top.data(0, _ROLE_PATH):
                yield top
            for j in range(top.childCount()):
                yield top.child(j)

    def _select_item(self, path: str) -> None:
        for item in self._iter_project_items():
            if item.data(0, _ROLE_PATH) == path:
                self._tree.blockSignals(True)
                self._tree.setCurrentItem(item)
                self._tree.blockSignals(False)
                return

    def select(self, path: str) -> None:
        self._selected_path = path
        self._select_item(path)

    def visible_paths(self) -> list[str]:
        """Chemins des projets dans l'ordre d'affichage courant."""
        return [it.data(0, _ROLE_PATH) for it in self._iter_project_items()]

    def selected_paths(self) -> list[str]:
        return [it.data(0, _ROLE_PATH) for it in self._tree.selectedItems() if it.data(0, _ROLE_PATH)]

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self._tree.itemAt(pos)
        if item is None or not item.data(0, _ROLE_PATH):
            return
        if not item.isSelected():
            self._tree.clearSelection()
            item.setSelected(True)
        self.context_requested.emit(self.selected_paths(), self._tree.viewport().mapToGlobal(pos))

    # ── Ping global ───────────────────────────────────────────────────────────

    def ping_all(self) -> None:
        """Vérifie l'accessibilité de tous les projets (le calcul se fait hors du thread GUI)."""
        paths = self.visible_paths()

        def _run() -> None:
            results = {p: _compute_ping(p) for p in paths}
            try:
                self._ping_finished.emit(results)
            except RuntimeError:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def _apply_ping(self, results: dict) -> None:
        self._ping_results.update(results)
        for item in self._iter_project_items():
            res = results.get(item.data(0, _ROLE_PATH))
            if res:
                self._paint_ping(item, *res)

    @staticmethod
    def _paint_ping(item: QTreeWidgetItem, color_key: str, tip: str) -> None:
        item.setForeground(0, QColor(_PING_COLORS[color_key]))
        item.setToolTip(0, tip)


# ─────────────────────────────────────────────────────────────────────────────
# ProjectBrowser — conteneur switchable + barre de contrôle
# ─────────────────────────────────────────────────────────────────────────────

class ProjectBrowser(QWidget):
    """
    Panneau latéral complet :
      • Switch liste ↔ grille
      • Regroupement (catégorie, organisation GitHub, langage, statut) et tri
      • Bouton Ping global
      • Boutons créer / importer / cloner
    """

    project_selected          = Signal(str)
    create_requested          = Signal()
    import_requested          = Signal()
    clone_requested           = Signal()
    manage_categories_requested = Signal()
    projects_modified         = Signal()          # catégorie/ordre/statut modifiés ici
    view_state_changed        = Signal(str, str, str)   # mode, regroupement, tri

    _MODE_LIST = "list"
    _MODE_GRID = "grid"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode     = self._MODE_LIST
        self._sort     = core.DEFAULT_SORT
        self._group_by = core.DEFAULT_GROUP
        self._entries: list[dict] = []

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

        self._btn_categories = QToolButton()
        self._btn_categories.setText("📂")
        self._btn_categories.setToolTip("Gérer les catégories")
        self._btn_categories.setFixedSize(26, 26)
        self._btn_categories.clicked.connect(self.manage_categories_requested)
        bar.addWidget(self._btn_categories)

        self._btn_list = QToolButton()
        self._btn_list.setText("☰")
        self._btn_list.setToolTip("Vue liste  (glisser un projet sur un groupe pour le classer)")
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

        # ── Recherche — partagée entre les deux modes d'affichage ──────────────
        self._search = QLineEdit()
        self._search.setPlaceholderText("Rechercher (nom, catégorie, organisation, tag)…")
        self._search.setObjectName("searchBox")
        self._search.textChanged.connect(self.filter)
        v.addWidget(self._search)

        # ── Regroupement + tri + ping ─────────────────────────────────────────
        self._group_combo = QComboBox()
        self._group_combo.setToolTip("Regrouper les projets")
        self._group_combo.setFixedHeight(24)
        for key, label in core.GROUP_OPTIONS:
            self._group_combo.addItem(label, key)
        self._group_combo.currentIndexChanged.connect(self._on_group_change)
        v.addWidget(self._group_combo)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(4)
        self._sort_combo = QComboBox()
        self._sort_combo.setToolTip("Trier les projets")
        self._sort_combo.setFixedHeight(24)
        for key, label in core.SORT_OPTIONS:
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
        self._list_view.context_requested.connect(self._show_category_menu)
        self._list_view.projects_dropped.connect(self._on_projects_dropped)

        self._grid_view = ProjectGridView()
        self._grid_view.project_selected.connect(self.project_selected)
        self._grid_view.context_requested.connect(lambda path, pos: self._show_category_menu([path], pos))

        v.addWidget(self._list_view, 1)
        v.addWidget(self._grid_view, 1)
        self._grid_view.setVisible(False)

        # ── Séparateur + boutons ──────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #313244;")
        v.addWidget(sep)

        row = QHBoxLayout()
        btn_new = QPushButton("+ Nouveau")
        btn_new.setObjectName("primary")
        btn_new.clicked.connect(self.create_requested)
        btn_import = QPushButton("📥 Importer")
        btn_import.setObjectName("subtle")
        btn_import.setToolTip("Importer un dossier ou une archive ZIP")
        btn_import.clicked.connect(self.import_requested)
        btn_clone = QPushButton("🐙")
        btn_clone.setObjectName("subtle")
        btn_clone.setToolTip("Cloner un dépôt GitHub")
        btn_clone.setFixedWidth(38)
        btn_clone.clicked.connect(self.clone_requested)
        row.addWidget(btn_new, 1)
        row.addWidget(btn_import, 1)
        row.addWidget(btn_clone)
        v.addLayout(row)

    # ── Switch de mode ────────────────────────────────────────────────────────

    def _switch(self, mode: str, emit: bool = True) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._btn_list.setChecked(mode == self._MODE_LIST)
        self._btn_grid.setChecked(mode == self._MODE_GRID)
        self._list_view.setVisible(mode == self._MODE_LIST)
        self._grid_view.setVisible(mode == self._MODE_GRID)
        if emit:
            self._emit_state()

    # ── État de l'affichage (mémorisé par la fenêtre principale) ──────────────

    def set_view_state(self, mode: str, group_by: str, sort: str) -> None:
        """Restaure l'état sans émettre view_state_changed."""
        valid_groups = {k for k, _ in core.GROUP_OPTIONS}
        valid_sorts = {k for k, _ in core.SORT_OPTIONS}
        self._group_by = group_by if group_by in valid_groups else core.DEFAULT_GROUP
        self._sort = sort if sort in valid_sorts else core.DEFAULT_SORT
        for combo, value in ((self._group_combo, self._group_by), (self._sort_combo, self._sort)):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(combo.findData(value), 0))
            combo.blockSignals(False)
        self._switch(mode if mode in (self._MODE_LIST, self._MODE_GRID) else self._MODE_LIST, emit=False)
        self._apply_state()

    def _apply_state(self) -> None:
        for view in (self._list_view, self._grid_view):
            view._sort_key = self._sort
            view._group_by = self._group_by
        self._list_view._render()
        self._grid_view._render()

    def _emit_state(self) -> None:
        self.view_state_changed.emit(self._mode, self._group_by, self._sort)

    def _on_group_change(self, _idx: int) -> None:
        self._group_by = self._group_combo.currentData() or core.DEFAULT_GROUP
        self._apply_state()
        self._emit_state()

    def _on_sort_change(self, _idx: int) -> None:
        self._sort = self._sort_combo.currentData() or core.DEFAULT_SORT
        self._apply_state()
        self._emit_state()

    # ── Ping ──────────────────────────────────────────────────────────────────

    def _ping_all(self) -> None:
        self._btn_ping.setStyleSheet("color:#89b4fa;")
        self._list_view.ping_all()
        self._grid_view.ping_all()
        QTimer.singleShot(3000, lambda: self._btn_ping.setStyleSheet("color:#45475a;"))

    # ── Données ───────────────────────────────────────────────────────────────

    def populate(self, entries: list[dict]) -> None:
        self._entries = list(entries)
        self._list_view.populate(entries)
        self._grid_view.populate(entries)

    def select(self, path: str) -> None:
        self._list_view.select(path)
        self._grid_view.select(path)

    def get_list_view(self) -> ProjectListView:
        return self._list_view

    def get_grid_view(self) -> ProjectGridView:
        return self._grid_view

    def get_search_widget(self) -> QLineEdit:
        return self._search

    def filter(self, text: str) -> None:
        """Filtre les deux vues (liste ET grille) — la recherche reste active
        quel que soit le mode d'affichage courant."""
        self._list_view.filter(text)
        self._grid_view.filter(text)

    # ── Classement : menu contextuel et glisser-déposer ───────────────────────

    def _show_category_menu(self, paths: list[str], pos: QPoint) -> None:
        menu = QMenu(self)
        sub = menu.addMenu(f"📂 Catégorie ({len(paths)} projet(s))" if len(paths) > 1 else "📂 Catégorie")
        for cat in core.list_categories():
            label = f"{cat['emoji']} {cat['name']}".strip()
            sub.addAction(label, lambda n=cat["name"]: self.assign_category(paths, n))
        if sub.actions():
            sub.addSeparator()
        sub.addAction("➕ Nouvelle catégorie…", lambda: self._assign_new_category(paths))
        sub.addAction("✕ Aucune catégorie", lambda: self.assign_category(paths, None))
        menu.exec(pos)

    def _assign_new_category(self, paths: list[str]) -> None:
        name, ok = QInputDialog.getText(self, "Nouvelle catégorie", "Nom de la catégorie :")
        if ok and name.strip():
            try:
                self.assign_category(paths, name.strip())
            except ValueError as exc:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Voktora", str(exc))

    def assign_category(self, paths: list[str], category: str | None) -> None:
        core.assign_category(paths, category)
        self.projects_modified.emit()

    def _on_projects_dropped(self, moved: list[str], group_key, before) -> None:
        """Traduit un glisser-déposer : changer de groupe (classement) ou réordonner."""
        visible = self._list_view.visible_paths()
        source_group_same = self._is_same_group(moved, group_key)

        if not source_group_same:
            target = None if group_key == _NO_GROUP else group_key
            if self._group_by == "category":
                self.assign_category(moved, target)
            elif self._group_by == "status" and target:
                for path in moved:
                    core.update_project(path, status=target)
                self.projects_modified.emit()
            # Organisation GitHub et langage sont déduits des projets : pas de dépôt possible.
            return

        # Même groupe → réordonner (l'ordre affiché devient l'ordre manuel).
        rest = [p for p in visible if p not in moved]
        index = rest.index(before) if before in rest else len(rest)
        core.reorder_projects(rest[:index] + moved + rest[index:])
        if self._sort != "manual":
            self._sort_combo.setCurrentIndex(self._sort_combo.findData("manual"))   # ré-affiche + mémorise
        self.projects_modified.emit()

    def _is_same_group(self, paths: list[str], group_key) -> bool:
        """True si tous les projets déplacés appartiennent déjà au groupe cible."""
        if self._group_by == "none":
            return True
        by_path = {e["path"]: e for e in self._entries}
        for path in paths:
            entry = by_path.get(path)
            if entry is None:
                return False
            value = {
                "category": entry.get("category"),
                "github_owner": core.github_owner(entry.get("github_repo")),
                "language": entry.get("language"),
                "status": entry.get("status"),
            }.get(self._group_by)
            current = value or _NO_GROUP
            if current.lower() != str(group_key).lower():
                return False
        return True
