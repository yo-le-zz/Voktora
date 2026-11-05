"""
Voktora — icons.py
Vraies icônes (police Material Design Icons embarquée) à la place des emojis.

Pourquoi : un emoji dépend d'une police système (Noto Color Emoji…) absente de nombreuses
installations Linux — l'interface affiche alors des carrés « tofu ». Les icônes ci-dessous sont
dessinées avec une police fournie avec Voktora (assets/icons), donc identiques partout, nettes à
toute taille et teintées par le thème.

API :
    icons.icon("mdi:rocket-launch")          -> QIcon
    icons.icon("🚀")                          -> QIcon (emoji enregistré avant la 1.0.5, converti)
    icons.icon("mdi:circle", color="#f38ba8") -> QIcon teinté
    icons.install(app)                        -> nettoie automatiquement les emojis restants

`install` ne touche pas aux données : il remplace, à l'affichage, l'emoji placé en tête d'un
bouton / d'une action / d'un onglet / d'un élément de liste par l'icône équivalente, et retire les
emojis des libellés (QLabel, titres de fenêtre…), sans changer le code qui les a écrits.
"""

from __future__ import annotations

import json
from pathlib import Path

import icon_catalog as catalog
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QIconEngine, QPainter, QPixmap

_FONT_FILE = "materialdesignicons-webfont.ttf"
_CHARMAP_FILE = "materialdesignicons-charmap.json"
_DEFAULT_COLOR = "#cdd6f4"
_FALLBACK_FAMILY = "Material Design Icons"

_family: str | None = None
_charmap: dict[str, str] = {}
_loaded = False
_cache: dict[tuple[str, str], QIcon] = {}


def _icon_dirs() -> list[Path]:
    import core
    app_dir = core.get_app_dir()
    return [app_dir / "assets" / "icons", app_dir.parent / "assets" / "icons",
            Path(__file__).resolve().parent / "assets" / "icons"]


def load() -> bool:
    """Charge la police et la table des glyphes (une seule fois). Retourne False si indisponible."""
    global _family, _charmap, _loaded
    if _loaded:
        return _family is not None
    _loaded = True
    for directory in _icon_dirs():
        font_path, map_path = directory / _FONT_FILE, directory / _CHARMAP_FILE
        if not (font_path.is_file() and map_path.is_file()):
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        if not families:
            continue
        try:
            raw = json.loads(map_path.read_text(encoding="utf-8"))
            _charmap = {name: chr(int(code, 16)) for name, code in raw.items()}
        except (OSError, ValueError):
            continue
        _family = families[0] or _FALLBACK_FAMILY
        return True
    return False


def is_available() -> bool:
    return load()


def set_default_color(color: str) -> None:
    """Couleur des icônes sans teinte explicite (le texte du thème) ; appelée par theme_manager."""
    global _DEFAULT_COLOR
    if color and color != _DEFAULT_COLOR:
        _DEFAULT_COLOR = color


def all_glyph_names() -> list[str]:
    load()
    return sorted(_charmap)


def has_glyph(name: str) -> bool:
    load()
    return name in _charmap


class _GlyphEngine(QIconEngine):
    """Dessine un glyphe de la police d'icônes à la taille et dans l'état demandés."""

    def __init__(self, char: str, color: str | None):
        super().__init__()
        self._char = char
        self._color = color

    def clone(self) -> QIconEngine:
        return _GlyphEngine(self._char, self._color)

    def _pen_color(self, mode: QIcon.Mode) -> QColor:
        color = QColor(self._color or _DEFAULT_COLOR)
        if mode == QIcon.Mode.Disabled:
            color.setAlphaF(0.35)
        return color

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        font = QFont(_family or _FALLBACK_FAMILY)
        font.setPixelSize(max(8, int(min(rect.width(), rect.height()) * 0.92)))
        painter.setFont(font)
        painter.setPen(self._pen_color(mode))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), self._char)
        painter.restore()

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(QPoint(0, 0), size), mode, state)
        painter.end()
        return pixmap


def resolve_id(value: str | None) -> str | None:
    """Identifiant « mdi:… » pour un identifiant d'icône ou un emoji ; None si rien d'affichable."""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if catalog.is_icon_id(value):
        return value
    if catalog.contains_emoji(value):
        return catalog.emoji_to_icon_id(catalog.split_leading_emoji(value)[0] or value[:1]) \
            or catalog.FALLBACK_ICON
    return None


def icon(value: str | None, color: str | None = None) -> QIcon:
    """QIcon pour un identifiant d'icône ou un emoji hérité ; QIcon() vide si l'icône est inconnue."""
    icon_id = resolve_id(value)
    if icon_id is None or not load():
        return QIcon()
    char = _charmap.get(icon_id[len(catalog.PREFIX):]) or _charmap.get(catalog.FALLBACK_ICON[len(catalog.PREFIX):])
    if not char:
        return QIcon()
    key = (icon_id, color or "")
    cached = _cache.get(key)
    if cached is None:
        cached = _cache[key] = QIcon(_GlyphEngine(char, color))
    return cached


def pixmap(value: str | None, size: int = 16, color: str | None = None) -> QPixmap:
    return icon(value, color).pixmap(size, size)


def display_name(value: str | None) -> str:
    """Nom lisible d'une icône (pour les info-bulles), vide si inconnue."""
    icon_id = resolve_id(value)
    if not icon_id:
        return ""
    entry = catalog.entry_for(icon_id)
    return entry.label if entry else icon_id[len(catalog.PREFIX):].replace("-", " ")


# ──────────────────────────────────────────────
# NETTOYAGE AUTOMATIQUE DES EMOJIS RESTANTS
# ──────────────────────────────────────────────

_ICON_PROP = "_vk_iconified"


def _convert(text: str) -> tuple[QIcon | None, str]:
    """(icône, texte sans emoji). Icône None si le texte n'avait pas d'emoji en tête reconnu."""
    if not catalog.contains_emoji(text):
        return None, text
    lead, rest = catalog.split_leading_emoji(text)
    qicon = None
    if lead:
        icon_id = catalog.emoji_to_icon_id(lead)
        if icon_id:
            candidate = icon(icon_id)
            qicon = candidate if not candidate.isNull() else None
    return qicon, catalog.strip_emoji(rest if lead else text)


def _fix_button(button) -> None:
    text = button.text()
    qicon, clean = _convert(text)
    if clean != text:
        button.setText(clean)
        if qicon is not None and button.icon().isNull():
            button.setIcon(qicon)
            button.setProperty(_ICON_PROP, True)


def _fix_action(action) -> None:
    text = action.text()
    qicon, clean = _convert(text)
    if clean != text:
        action.setText(clean)
        if qicon is not None and action.icon().isNull():
            action.setIcon(qicon)


def _fix_menu_actions(widget, depth: int = 0) -> None:
    for action in widget.actions():
        _fix_action(action)
        sub = action.menu()
        if sub is not None and depth < 4:
            _fix_menu_actions(sub, depth + 1)


def _fix_items_text(count: int, get_text, set_item) -> None:
    for index in range(min(count, 400)):
        text = get_text(index)
        if text and catalog.contains_emoji(text):
            qicon, clean = _convert(text)
            set_item(index, clean, qicon)


def fix_widget(widget) -> None:
    """Remplace/retire les emojis dans le texte propre d'un widget (appelé à l'affichage)."""
    from PySide6.QtWidgets import (
        QAbstractButton,
        QComboBox,
        QGroupBox,
        QLabel,
        QListWidget,
        QMenu,
        QMenuBar,
        QTabWidget,
        QToolBar,
        QTreeWidget,
    )
    if widget.isWindow():
        title = widget.windowTitle()
        if catalog.contains_emoji(title):
            widget.setWindowTitle(catalog.strip_emoji(title))
    if isinstance(widget, QAbstractButton):
        _fix_button(widget)
    elif isinstance(widget, QLabel):
        text = widget.text()
        if catalog.contains_emoji(text):
            widget.setText(catalog.strip_emoji(text))
    elif isinstance(widget, QGroupBox):
        title = widget.title()
        if catalog.contains_emoji(title):
            widget.setTitle(catalog.strip_emoji(title))
    elif isinstance(widget, QTabWidget):
        for index in range(widget.count()):
            text = widget.tabText(index)
            if catalog.contains_emoji(text):
                qicon, clean = _convert(text)
                widget.setTabText(index, clean)
                if qicon is not None:
                    widget.setTabIcon(index, qicon)
    elif isinstance(widget, QComboBox):
        def _set_combo(i, clean, qicon):
            widget.setItemText(i, clean)
            if qicon is not None:
                widget.setItemIcon(i, qicon)
        _fix_items_text(widget.count(), widget.itemText, _set_combo)
    elif isinstance(widget, QListWidget):
        def _set_list(i, clean, qicon):
            item = widget.item(i)
            item.setText(clean)
            if qicon is not None and item.icon().isNull():
                item.setIcon(qicon)
        _fix_items_text(widget.count(), lambda i: widget.item(i).text(), _set_list)
    elif isinstance(widget, QTreeWidget):
        _fix_tree(widget)
    elif isinstance(widget, QMenu | QMenuBar | QToolBar):
        _fix_menu_actions(widget)


def _fix_tree(tree) -> None:
    budget = [400]

    def walk(item) -> None:
        if budget[0] <= 0:
            return
        budget[0] -= 1
        for column in range(item.columnCount()):
            text = item.text(column)
            if text and catalog.contains_emoji(text):
                qicon, clean = _convert(text)
                item.setText(column, clean)
                if qicon is not None and item.icon(column).isNull():
                    item.setIcon(column, qicon)
        for child_index in range(item.childCount()):
            walk(item.child(child_index))

    for top in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(top))


class _EmojiFilter(QObject):
    """Filtre global : à chaque affichage d'un widget, remplace les emojis de son texte."""

    def eventFilter(self, watched, event) -> bool:        # noqa: N802 - nom imposé par Qt
        if event.type() == QEvent.Type.Show:
            try:
                from PySide6.QtWidgets import QWidget
                if isinstance(watched, QWidget):
                    fix_widget(watched)
            except Exception:
                pass         # un nettoyage cosmétique ne doit jamais faire échouer l'affichage
        return False


_filter: _EmojiFilter | None = None
_patched = False


def _patch_setters() -> None:
    """Fait passer par le nettoyage les textes posés APRÈS l'affichage (setText, setTitle…)."""
    global _patched
    if _patched:
        return
    _patched = True
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QAbstractButton, QGroupBox, QLabel, QWidget

    orig_button = QAbstractButton.setText
    orig_label = QLabel.setText
    orig_group = QGroupBox.setTitle
    orig_action = QAction.setText
    orig_title = QWidget.setWindowTitle

    def button_set_text(self, text):
        qicon, clean = _convert(text) if isinstance(text, str) else (None, text)
        orig_button(self, clean)
        if qicon is not None:
            self.setIcon(qicon)
            self.setProperty(_ICON_PROP, True)
        elif self.property(_ICON_PROP) and clean == text:
            self.setIcon(QIcon())
            self.setProperty(_ICON_PROP, False)

    def label_set_text(self, text):
        orig_label(self, catalog.strip_emoji(text) if isinstance(text, str) else text)

    def group_set_title(self, title):
        orig_group(self, catalog.strip_emoji(title) if isinstance(title, str) else title)

    def action_set_text(self, text):
        qicon, clean = _convert(text) if isinstance(text, str) else (None, text)
        orig_action(self, clean)
        if qicon is not None and self.icon().isNull():
            self.setIcon(qicon)

    def window_set_title(self, title):
        orig_title(self, catalog.strip_emoji(title) if isinstance(title, str) else title)

    QAbstractButton.setText = button_set_text
    QLabel.setText = label_set_text
    QGroupBox.setTitle = group_set_title
    QAction.setText = action_set_text
    QWidget.setWindowTitle = window_set_title


def install(app) -> None:
    """Active le remplacement automatique des emojis sur toute l'application."""
    global _filter
    load()
    if _filter is None:
        _filter = _EmojiFilter(app)
        app.installEventFilter(_filter)
    try:
        _patch_setters()
    except Exception:                # pragma: no cover - monkeypatch impossible : le filtre reste actif
        pass
