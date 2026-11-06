"""Icônes à la place des emojis : catalogue, rendu, nettoyage automatique de l'interface."""

from __future__ import annotations

import os
import sys

import icon_catalog as catalog
import icons
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QAction, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QPushButton, QTabWidget  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def test_font_loads_and_every_catalog_icon_exists():
    assert icons.is_available()
    missing = [e.id for e in catalog.all_entries() if not icons.has_glyph(e.id[len(catalog.PREFIX):])]
    assert not missing


def test_every_emoji_mapping_points_to_a_real_glyph():
    icons.load()
    missing = sorted({n for n in catalog.EMOJI_TO_ICON.values() if not icons.has_glyph(n)})
    assert not missing


def test_icon_renders_visible_pixels_and_follows_color():
    pixmap = icons.icon("mdi:rocket-launch", color="#ff0000").pixmap(32, 32)
    image = pixmap.toImage()
    opaque = [(x, y) for x in range(32) for y in range(32) if image.pixelColor(x, y).alpha() > 128]
    assert len(opaque) > 40
    x, y = opaque[0]
    assert image.pixelColor(x, y).red() > 200 and image.pixelColor(x, y).green() < 60


def test_legacy_emoji_resolves_to_icon_and_unknown_emoji_to_fallback():
    assert icons.resolve_id("🚀") == "mdi:rocket-launch"
    assert icons.resolve_id("🛠️") == "mdi:tools"
    assert icons.resolve_id("🦄") == catalog.FALLBACK_ICON
    assert icons.resolve_id("") is None and icons.resolve_id("texte") is None
    assert not icons.icon("🦄").isNull()


def test_strip_and_split_emoji():
    assert catalog.split_leading_emoji("📥  Cloner") == ("📥", "Cloner")
    assert catalog.strip_emoji("✅ Terminé → OK ■") == "Terminé → OK ■"
    assert catalog.strip_emoji("Rien") == "Rien"


@pytest.fixture(scope="module", autouse=True)
def _install():
    icons.install(_app)


def test_button_text_with_emoji_becomes_icon_and_clean_text():
    button = QPushButton("🚀  Lancer")     # le constructeur n'appelle pas setText : le filtre d'affichage agit
    button.show()
    assert button.text() == "Lancer"
    assert not button.icon().isNull()
    button.setText("Arrêter")
    assert button.icon().isNull()


def test_label_action_and_window_title_lose_their_emoji():
    label = QLabel("⚠  Attention")
    label.show()
    assert label.text() == "Attention"
    action = QAction("🔍  Chercher")
    action.setText("🔍  Chercher")
    assert action.text() == "Chercher" and not action.icon().isNull()
    label.setWindowTitle("🎨 Thème")
    assert label.windowTitle() == "Thème"


def test_show_filter_fixes_tabs_and_menus_created_without_setters():
    tabs = QTabWidget()
    tabs.addTab(QLabel("x"), "🐙  Mes dépôts")
    menu = QMenu()
    menu.addAction("🗑️  Supprimer")
    tabs.show()
    menu.show()
    assert tabs.tabText(0) == "Mes dépôts" and not tabs.tabIcon(0).isNull()
    assert menu.actions()[0].text() == "Supprimer"
    assert isinstance(menu.actions()[0].icon(), QIcon)
