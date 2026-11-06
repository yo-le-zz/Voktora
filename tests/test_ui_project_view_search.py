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

import core  # noqa: E402
import ui_project_view as upv  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


ENTRIES = [
    {"name": "AlphaProject", "path": "/tmp/alpha", "tags": ["web", "urgent"]},
    {"name": "BetaProject", "path": "/tmp/beta", "tags": ["cli"]},
    {"name": "GammaIdea", "path": "/tmp/gamma", "tags": ["urgent"]},
]


@pytest.fixture
def browser(isolated_data_dir):
    b = upv.ProjectBrowser()
    b.set_view_state("list", "none", "name_asc")   # à plat : on teste la recherche seule
    b.populate(ENTRIES)
    return b


class TestEntryMatches:
    def test_matches_by_name(self):
        assert core.entry_matches({"name": "Foo", "path": "/x"}, "foo")

    def test_matches_by_path(self):
        assert core.entry_matches({"name": "Foo", "path": "/special-dir"}, "special")

    def test_matches_by_tag(self):
        assert core.entry_matches({"name": "Foo", "path": "/x", "tags": ["urgent"]}, "urgent")

    def test_no_match(self):
        assert not core.entry_matches({"name": "Foo", "path": "/x", "tags": ["cli"]}, "urgent")

    def test_entry_without_tags_key(self):
        assert not core.entry_matches({"name": "Foo", "path": "/x"}, "urgent")


class TestSharedSearchAcrossModes:
    def test_search_by_tag_filters_grid_view(self, browser):
        browser._switch(browser._MODE_GRID)
        browser.get_search_widget().setText("urgent")
        paths = [c._path for c in browser._grid_view._cards]
        assert paths == ["/tmp/alpha", "/tmp/gamma"]

    def test_search_by_tag_filters_list_view(self, browser):
        browser.get_search_widget().setText("cli")
        assert browser._list_view.visible_paths() == ["/tmp/beta"]

    def test_clearing_search_restores_all_entries(self, browser):
        browser._switch(browser._MODE_GRID)
        browser.get_search_widget().setText("urgent")
        browser.get_search_widget().setText("")
        assert len(browser._grid_view._cards) == 3

    def test_sort_change_preserves_active_grid_filter(self, browser):
        # Régression : changer le tri en mode grille pendant une recherche
        # active réinitialisait le filtre avant ce correctif.
        browser._switch(browser._MODE_GRID)
        browser.get_search_widget().setText("urgent")
        browser._sort_combo.setCurrentIndex(1)
        paths = [c._path for c in browser._grid_view._cards]
        assert set(paths) == {"/tmp/alpha", "/tmp/gamma"}


class TestLazyAndChunkedGrid:
    """1.0.6 : la grille masquée ne construit rien ; une grande grille est construite par tranches."""

    def test_hidden_grid_builds_nothing_until_shown(self, browser):
        assert browser._grid_view._cards == []
        browser._switch(browser._MODE_GRID)
        assert len(browser._grid_view._cards) == 3

    def test_large_grid_is_built_in_chunks(self, isolated_data_dir):
        import ui_project_view as view
        grid = view.ProjectGridView()
        entries = [{"name": f"p{i}", "path": f"/tmp/p{i}"} for i in range(view._CHUNK_MIN + 100)]
        grid.populate(entries)
        assert grid.pending_cards() > 0                    # tout n'est pas construit d'un coup
        assert len(grid._cards) < len(entries)
        grid.flush()
        assert len(grid._cards) == len(entries)
        assert grid.pending_cards() == 0

    def test_new_render_cancels_pending_chunks(self, isolated_data_dir):
        import ui_project_view as view
        grid = view.ProjectGridView()
        grid.populate([{"name": f"p{i}", "path": f"/tmp/p{i}"} for i in range(view._CHUNK_MIN + 100)])
        grid.populate([{"name": "solo", "path": "/tmp/solo"}])
        grid.flush()
        assert [c._path for c in grid._cards] == ["/tmp/solo"]
