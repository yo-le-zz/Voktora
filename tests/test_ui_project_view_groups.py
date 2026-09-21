"""Vues projets : regroupement, classement par glisser-déposer / menu, mémorisation de l'état."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core  # noqa: E402
import ui_project_view as upv  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _mk(tmp_path, name, **fields):
    p = tmp_path / name
    p.mkdir()
    core.register_project(p, str(tmp_path), name=name, **fields)
    return str(p)


@pytest.fixture
def world(isolated_data_dir, tmp_path):
    core.add_category("Web", "🌐")
    core.add_category("Outils")
    paths = {
        "site": _mk(tmp_path, "site", category="Web", github_repo="https://github.com/acme/site"),
        "api": _mk(tmp_path, "api", category="Web", github_repo="https://github.com/me/api"),
        "cli": _mk(tmp_path, "cli", github_repo="https://github.com/acme/cli"),
        "note": _mk(tmp_path, "note"),
    }
    browser = upv.ProjectBrowser()
    browser.populate(core.list_projects())
    return browser, paths


def _headers(browser):
    tree = browser.get_list_view()._tree
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


class TestGroupedList:
    def test_default_groups_by_category_with_user_order_and_empty_category(self, world):
        browser, _ = world
        headers = _headers(browser)
        assert headers[0].startswith("🌐 Web") and "(2)" in headers[0]
        assert headers[1].startswith("Outils") and "(0)" in headers[1]      # cible de dépôt vide
        assert headers[-1].startswith("Sans catégorie") and "(2)" in headers[-1]

    def test_group_by_github_owner(self, world):
        browser, _ = world
        browser.set_view_state("list", "github_owner", "name_asc")
        headers = _headers(browser)
        assert [h.split("  ")[0] for h in headers] == ["acme", "me", "Sans dépôt GitHub"]

    def test_no_grouping_is_flat(self, world):
        browser, paths = world
        browser.set_view_state("list", "none", "name_asc")
        tree = browser.get_list_view()._tree
        assert tree.topLevelItemCount() == 4
        assert browser.get_list_view().visible_paths() == sorted(paths.values(), key=lambda p: Path(p).name)

    def test_all_uncategorized_is_shown_flat_without_useless_header(self, isolated_data_dir, tmp_path):
        _mk(tmp_path, "a")
        _mk(tmp_path, "b")
        browser = upv.ProjectBrowser()
        browser.populate(core.list_projects())
        tree = browser.get_list_view()._tree
        assert tree.topLevelItemCount() == 2 and tree.topLevelItem(0).childCount() == 0

    def test_filtering_hides_empty_groups(self, world):
        browser, _ = world
        browser.get_search_widget().setText("cli")
        assert not any(h.startswith("Outils") for h in _headers(browser))

    def test_search_matches_github_owner(self, world):
        browser, paths = world
        browser.get_search_widget().setText("acme")
        assert set(browser.get_list_view().visible_paths()) == {paths["site"], paths["cli"]}

    def test_grid_has_one_section_per_group_and_cards(self, world):
        browser, _ = world
        browser._switch(browser._MODE_GRID)
        assert len(browser._grid_view._cards) == 4

    def test_selection_is_kept_after_rerender(self, world):
        browser, paths = world
        browser.select(paths["api"])
        browser.set_view_state("list", "github_owner", "name_asc")
        assert browser.get_list_view()._tree.currentItem().data(0, upv._ROLE_PATH) == paths["api"]


class TestViewState:
    def test_state_signal_is_emitted_on_user_change(self, world):
        browser, _ = world
        seen = []
        browser.view_state_changed.connect(lambda *a: seen.append(a))
        browser._group_combo.setCurrentIndex(browser._group_combo.findData("language"))
        assert seen[-1] == ("list", "language", "name_asc")

    def test_set_view_state_does_not_emit_and_rejects_bad_values(self, world):
        browser, _ = world
        seen = []
        browser.view_state_changed.connect(lambda *a: seen.append(a))
        browser.set_view_state("grid", "nonsense", "whatever")
        assert seen == []
        assert browser._group_by == core.DEFAULT_GROUP and browser._sort == core.DEFAULT_SORT


class TestClassify:
    def test_drop_on_category_assigns_it(self, world):
        browser, paths = world
        modified = []
        browser.projects_modified.connect(lambda: modified.append(1))
        browser._on_projects_dropped([paths["note"], paths["cli"]], "Outils", None)
        assert core.get_project(paths["note"])["category"] == "Outils"
        assert core.get_project(paths["cli"])["category"] == "Outils"
        assert modified

    def test_drop_on_uncategorized_clears_category(self, world):
        browser, paths = world
        browser._on_projects_dropped([paths["site"]], upv._NO_GROUP, None)
        assert core.get_project(paths["site"])["category"] is None

    def test_drop_within_same_group_reorders_and_switches_to_manual_sort(self, world):
        browser, paths = world
        # « api » et « site » sont dans « Web » ; on met « site » avant « api ».
        browser._on_projects_dropped([paths["site"]], "Web", paths["api"])
        order = [e["path"] for e in core.list_projects()]
        assert order.index(paths["site"]) < order.index(paths["api"])
        assert browser._sort == "manual"

    def test_drop_on_github_owner_group_is_ignored(self, world):
        browser, paths = world
        browser.set_view_state("list", "github_owner", "name_asc")
        before = core.get_project(paths["note"]).copy()
        browser._on_projects_dropped([paths["note"]], "acme", None)
        assert core.get_project(paths["note"]) == before

    def test_drop_on_status_group_changes_status(self, world):
        browser, paths = world
        browser.set_view_state("list", "status", "name_asc")
        browser._on_projects_dropped([paths["note"]], "finished", None)
        assert core.get_project(paths["note"])["status"] == "finished"

    def test_context_menu_assign_new_category_path(self, world):
        browser, paths = world
        browser.assign_category([paths["note"]], "Nouvelle")
        assert core.get_project(paths["note"])["category"] == "Nouvelle"
        assert "Nouvelle" in [c["name"] for c in core.list_categories()]
