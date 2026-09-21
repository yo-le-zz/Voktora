"""
Tests de la recherche partagée (nom, chemin, tags) dans ui_project_view.py,
et de la correction du bug "recherche invisible en mode grille/bloc".
Nécessite PySide6 — utilise QT_QPA_PLATFORM=offscreen (voir conftest.py).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))

pytest.importorskip("PySide6")

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ui_project_view as upv  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def browser():
    b = upv.ProjectBrowser()
    b.populate(
        instances=[
            {"name": "AlphaProject", "path": "/tmp/alpha", "tags": ["web", "urgent"]},
            {"name": "BetaProject", "path": "/tmp/beta", "tags": ["cli"]},
        ],
        intents=[
            {"name": "GammaIdea", "path": "/tmp/gamma", "tags": ["urgent"]},
        ],
    )
    return b


class TestEntryMatches:
    def test_matches_by_name(self):
        assert upv._entry_matches({"name": "Foo", "path": "/x"}, "foo")

    def test_matches_by_path(self):
        assert upv._entry_matches({"name": "Foo", "path": "/special-dir"}, "special")

    def test_matches_by_tag(self):
        assert upv._entry_matches({"name": "Foo", "path": "/x", "tags": ["urgent"]}, "urgent")

    def test_no_match(self):
        assert not upv._entry_matches({"name": "Foo", "path": "/x", "tags": ["cli"]}, "urgent")

    def test_entry_without_tags_key(self):
        assert not upv._entry_matches({"name": "Foo", "path": "/x"}, "urgent")


class TestSharedSearchAcrossModes:
    def test_search_by_tag_filters_grid_view(self, browser):
        browser._switch(browser._MODE_GRID)
        browser.get_search_widget().setText("urgent")
        paths = [c._path for c in browser._grid_view._cards]
        assert paths == ["/tmp/alpha", "/tmp/gamma"]

    def test_search_by_tag_filters_list_view(self, browser):
        browser.get_search_widget().setText("cli")
        assert browser._list_view._inst_list.count() == 1
        assert browser._list_view._int_list.count() == 0

    def test_clearing_search_restores_all_entries(self, browser):
        browser.get_search_widget().setText("urgent")
        browser.get_search_widget().setText("")
        assert len(browser._grid_view._cards) == 3

    def test_sort_change_preserves_active_grid_filter(self, browser):
        # Régression : changer le tri en mode grille pendant une recherche
        # active réinitialisait le filtre avant ce correctif.
        browser.get_search_widget().setText("urgent")
        browser._sort_combo.setCurrentIndex(1)
        paths = [c._path for c in browser._grid_view._cards]
        assert set(paths) == {"/tmp/alpha", "/tmp/gamma"}
