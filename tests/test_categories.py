"""Tests de core.categories : catégories gérées par l'utilisateur."""

import core
import pytest


def _project(tmp_path, name, **fields):
    p = tmp_path / name
    p.mkdir()
    core.register_project(p, str(tmp_path), name=name, **fields)
    return p


class TestCrud:
    def test_add_and_list_in_order(self, isolated_data_dir):
        core.add_category("Web", "🌐", "#89b4fa")
        core.add_category("API")
        assert [c["name"] for c in core.list_categories()] == ["Web", "API"]
        assert core.list_categories()[0]["color"] == "#89b4fa"

    def test_duplicate_is_case_insensitive(self, isolated_data_dir):
        core.add_category("Web")
        with pytest.raises(ValueError, match="existe déjà"):
            core.add_category("web")

    @pytest.mark.parametrize("bad", ["", "   ", "x" * 200, "a\nb"])
    def test_invalid_names(self, isolated_data_dir, bad):
        with pytest.raises(ValueError):
            core.add_category(bad)

    def test_invalid_color(self, isolated_data_dir):
        with pytest.raises(ValueError, match="Couleur"):
            core.add_category("X", color="rouge")

    def test_list_returns_copy(self, isolated_data_dir):
        core.add_category("Web")
        core.list_categories()[0]["name"] = "Hack"
        assert core.list_categories()[0]["name"] == "Web"

    def test_ensure_is_idempotent(self, isolated_data_dir):
        first = core.ensure_category("Outils")
        second = core.ensure_category("outils")
        assert first["name"] == second["name"] == "Outils"
        assert len(core.list_categories()) == 1

    def test_move_category(self, isolated_data_dir):
        for n in ("A", "B", "C"):
            core.add_category(n)
        core.move_category("C", -2)
        assert [c["name"] for c in core.list_categories()] == ["C", "A", "B"]
        core.move_category("C", 99)
        assert [c["name"] for c in core.list_categories()] == ["A", "B", "C"]


class TestProjectsLink:
    def test_rename_cascades_to_projects(self, isolated_data_dir, tmp_path):
        core.add_category("Web")
        p = _project(tmp_path, "site", category="Web")
        core.update_category("Web", new_name="Frontend")
        assert core.get_project(p)["category"] == "Frontend"

    def test_rename_to_existing_is_refused(self, isolated_data_dir):
        core.add_category("A")
        core.add_category("B")
        with pytest.raises(ValueError):
            core.update_category("A", new_name="b")

    def test_delete_clears_projects_and_reports_count(self, isolated_data_dir, tmp_path):
        core.add_category("Old")
        p1 = _project(tmp_path, "p1", category="Old")
        _project(tmp_path, "p2", category="Old")
        assert core.delete_category("Old") == 2
        assert core.get_project(p1)["category"] is None
        assert core.list_categories() == []

    def test_assign_creates_missing_category(self, isolated_data_dir, tmp_path):
        p = _project(tmp_path, "p")
        assert core.assign_category([p], "Nouvelle") == 1
        assert core.get_project(p)["category"] == "Nouvelle"
        assert [c["name"] for c in core.list_categories()] == ["Nouvelle"]

    def test_assign_none_removes(self, isolated_data_dir, tmp_path):
        p = _project(tmp_path, "p", category="X")
        core.assign_category([str(p)], None)
        assert core.get_project(p)["category"] is None

    def test_counts(self, isolated_data_dir, tmp_path):
        _project(tmp_path, "a", category="X")
        _project(tmp_path, "b", category="X")
        _project(tmp_path, "c")
        assert core.category_counts() == {"X": 2, None: 1}


class TestAutoByOwner:
    def test_creates_categories_from_owners(self, isolated_data_dir, tmp_path):
        a = _project(tmp_path, "a", github_repo="https://github.com/acme/a")
        b = _project(tmp_path, "b", github_repo="git@github.com:me/b.git")
        c = _project(tmp_path, "c")
        result = core.categorize_by_github_owner()
        assert result == {"acme": 1, "me": 1}
        assert core.get_project(a)["category"] == "acme"
        assert core.get_project(b)["category"] == "me"
        assert core.get_project(c)["category"] is None
        assert {x["name"] for x in core.list_categories()} == {"acme", "me"}

    def test_existing_category_is_kept_by_default(self, isolated_data_dir, tmp_path):
        a = _project(tmp_path, "a", category="Perso", github_repo="https://github.com/acme/a")
        assert core.categorize_by_github_owner() == {}
        assert core.get_project(a)["category"] == "Perso"
        assert core.categorize_by_github_owner(only_uncategorized=False) == {"acme": 1}

    def test_reuses_existing_category_case_insensitively(self, isolated_data_dir, tmp_path):
        core.add_category("Acme")
        a = _project(tmp_path, "a", github_repo="https://github.com/acme/a")
        core.categorize_by_github_owner()
        assert core.get_project(a)["category"] == "Acme"
        assert len(core.list_categories()) == 1
