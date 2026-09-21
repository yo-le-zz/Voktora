"""Tests de core.organize : URL GitHub, recherche, tri, regroupement."""

from typing import ClassVar

import core
import pytest
from core import organize


class TestGithubUrl:
    @pytest.mark.parametrize("url,owner,repo", [
        ("https://github.com/yo-le-zz/Voktora", "yo-le-zz", "Voktora"),
        ("https://github.com/yo-le-zz/Voktora.git", "yo-le-zz", "Voktora"),
        ("https://github.com/org/repo/", "org", "repo"),
        ("https://ghp_abc@github.com/org/repo.git", "org", "repo"),
        ("https://user:tok@github.com/org/repo.git", "org", "repo"),
        ("git@github.com:org/repo.git", "org", "repo"),
        ("ssh://git@github.com/org/repo.git", "org", "repo"),
        ("HTTPS://GitHub.com/Org/Repo", "Org", "Repo"),
    ])
    def test_parse(self, url, owner, repo):
        assert organize.parse_github_url(url) == (owner, repo)

    @pytest.mark.parametrize("url", ["", None, "https://gitlab.com/a/b", "https://github.com/onlyowner", "not a url"])
    def test_not_github(self, url):
        assert organize.github_owner(url) is None

    def test_strip_credentials(self):
        assert organize.strip_url_credentials("https://u:tok@github.com/a/b.git") == "https://github.com/a/b.git"
        assert organize.strip_url_credentials("https://github.com/a/b.git") == "https://github.com/a/b.git"

    def test_repo_name(self):
        assert organize.repo_name_from_url("https://github.com/a/my-repo.git") == "my-repo"
        assert organize.repo_name_from_url("git@github.com:a/b.git") == "b"


class TestReadGitOrigin:
    def test_reads_url_and_branch_and_strips_credentials(self, tmp_path):
        git = tmp_path / ".git"
        git.mkdir()
        (git / "config").write_text(
            '[core]\n\tbare = false\n[remote "origin"]\n\turl = https://me:tok@github.com/o/r.git\n'
            '\tfetch = +refs/heads/*:refs/remotes/origin/*\n')
        (git / "HEAD").write_text("ref: refs/heads/develop\n")
        assert organize.read_git_origin(tmp_path) == ("https://github.com/o/r.git", "develop")

    def test_no_git_folder(self, tmp_path):
        assert organize.read_git_origin(tmp_path) == (None, None)

    def test_other_remote_is_ignored(self, tmp_path):
        git = tmp_path / ".git"
        git.mkdir()
        (git / "config").write_text('[remote "upstream"]\n\turl = https://github.com/x/y.git\n')
        assert organize.read_git_origin(tmp_path)[0] is None


ENTRIES = [
    {"name": "Bravo", "path": "/p/b", "category": "Web", "github_repo": "https://github.com/acme/bravo", "language": "Python", "created": "2026-02-01", "tags": ["urgent"]},
    {"name": "alpha", "path": "/p/a", "category": "Web", "github_repo": "https://github.com/me/alpha", "language": "Rust", "created": "2026-03-01"},
    {"name": "Charlie", "path": "/p/c", "category": None, "github_repo": None, "language": None, "created": "2026-01-01"},
]


class TestSearch:
    def test_by_name_path_category_owner_tag(self):
        e = ENTRIES[0]
        for needle in ("bravo", "/p/b", "web", "acme", "urgent"):
            assert organize.entry_matches(e, needle)
        assert not organize.entry_matches(e, "zzz")


class TestSort:
    def test_name_asc_is_case_insensitive(self):
        assert [e["name"] for e in organize.sort_entries(ENTRIES, "name_asc")] == ["alpha", "Bravo", "Charlie"]

    def test_date_desc(self):
        assert [e["name"] for e in organize.sort_entries(ENTRIES, "date_desc")] == ["alpha", "Bravo", "Charlie"]

    def test_manual_keeps_stored_order(self):
        assert organize.sort_entries(ENTRIES, "manual") == ENTRIES

    def test_category_puts_uncategorized_last(self):
        assert organize.sort_entries(ENTRIES, "category")[-1]["name"] == "Charlie"


class TestGroup:
    CATS: ClassVar[list[dict]] = [{"name": "Web", "emoji": "🌐", "color": ""},
                                  {"name": "Vide", "emoji": "", "color": ""}]

    def test_group_by_category_follows_user_order_and_puts_none_last(self):
        groups = organize.group_entries(ENTRIES, "category", categories=self.CATS)
        assert [g.key for g in groups] == ["Web", None]
        assert groups[0].emoji == "🌐"
        assert groups[-1].label == "Sans catégorie"

    def test_empty_categories_only_when_requested(self):
        groups = organize.group_entries(ENTRIES, "category", categories=self.CATS, include_empty_categories=True)
        assert [g.key for g in groups] == ["Web", "Vide", None]
        assert groups[1].entries == []

    def test_group_by_github_owner_alphabetical(self):
        groups = organize.group_entries(ENTRIES, "github_owner")
        assert [g.key for g in groups] == ["acme", "me", None]
        assert groups[-1].label == "Sans dépôt GitHub"

    def test_group_by_language(self):
        assert [g.key for g in organize.group_entries(ENTRIES, "language")] == ["Python", "Rust", None]

    def test_none_gives_single_group(self):
        groups = organize.group_entries(ENTRIES, "none")
        assert len(groups) == 1 and len(groups[0].entries) == 3

    def test_category_matching_ignores_case(self):
        entries = [{"name": "x", "path": "/x", "category": "web"}]
        groups = organize.group_entries(entries, "category", categories=self.CATS)
        assert [g.key for g in groups] == ["Web"]

    def test_core_facade_exposes_helpers(self):
        assert core.github_owner("https://github.com/a/b") == "a"
