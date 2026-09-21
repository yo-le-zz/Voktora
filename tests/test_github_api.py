"""Tests de core.github_api (réseau simulé)."""

import io
import json
import urllib.error

import core
import pytest
from core import github_api


class _Resp:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _repo(owner, name, otype="User", private=False):
    return {"full_name": f"{owner}/{name}", "name": name, "private": private,
            "clone_url": f"https://github.com/{owner}/{name}.git", "default_branch": "main",
            "owner": {"login": owner, "type": otype}, "description": None, "pushed_at": "2026-01-01T00:00:00Z"}


class TestListRepos:
    def test_paginates_until_short_page_and_sends_bearer(self, monkeypatch):
        pages = [[_repo("me", f"r{i}") for i in range(100)], [_repo("acme", "x", "Organization")]]
        seen = []

        def fake_urlopen(req, timeout):
            seen.append(req)
            return _Resp(pages[len(seen) - 1])

        monkeypatch.setattr(github_api.urllib.request, "urlopen", fake_urlopen)
        repos = github_api.list_user_repos("tok")
        assert len(repos) == 101 and len(seen) == 2
        assert seen[0].get_header("Authorization") == "Bearer tok"
        assert "affiliation=owner,collaborator,organization_member" in seen[0].full_url
        assert "page=2" in seen[1].full_url

    def test_installation_uses_installation_endpoint(self, monkeypatch):
        urls = []
        monkeypatch.setattr(github_api.urllib.request, "urlopen",
                            lambda req, timeout: (urls.append(req.full_url), _Resp({"repositories": [_repo("o", "r")]}))[1])
        repos = github_api.list_user_repos("tok", installation=True)
        assert [r.full_name for r in repos] == ["o/r"]
        assert "/installation/repositories" in urls[0]

    def test_requires_token(self):
        with pytest.raises(core.GitHubAPIError):
            github_api.list_user_repos("")

    def test_malformed_items_are_skipped(self, monkeypatch):
        monkeypatch.setattr(github_api.urllib.request, "urlopen",
                            lambda req, timeout: _Resp([{"nonsense": 1}, _repo("o", "ok")]))
        assert [r.name for r in github_api.list_user_repos("tok")] == ["ok"]

    def test_cancel(self, monkeypatch):
        with pytest.raises(core.OperationCancelled):
            github_api.list_user_repos("tok", cancel=lambda: True)

    @pytest.mark.parametrize("code,fragment", [(401, "invalide"), (404, "introuvable"), (500, "HTTP 500")])
    def test_http_errors_have_readable_messages(self, monkeypatch, code, fragment):
        def boom(req, timeout):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO())

        monkeypatch.setattr(github_api.urllib.request, "urlopen", boom)
        with pytest.raises(core.GitHubAPIError, match=fragment):
            github_api.list_user_repos("tok")

    def test_rate_limit_message(self, monkeypatch):
        def boom(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 403, "x", {"X-RateLimit-Remaining": "0"}, io.BytesIO())

        monkeypatch.setattr(github_api.urllib.request, "urlopen", boom)
        with pytest.raises(core.GitHubAPIError, match="Limite"):
            github_api.list_user_repos("tok")

    def test_token_never_appears_in_error(self, monkeypatch):
        def boom(req, timeout):
            raise urllib.error.URLError("dns")

        monkeypatch.setattr(github_api.urllib.request, "urlopen", boom)
        with pytest.raises(core.GitHubAPIError) as info:
            github_api.list_user_repos("ghp_SECRET")
        assert "ghp_SECRET" not in str(info.value)


class TestOwners:
    def test_orgs_failure_is_not_fatal(self, monkeypatch):
        def boom(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 403, "x", {}, io.BytesIO())

        monkeypatch.setattr(github_api.urllib.request, "urlopen", boom)
        assert github_api.list_user_orgs("tok") == []

    def test_owners_from_repos_counts_and_merges_extra_orgs(self):
        repos = [github_api._parse_repo(_repo("Acme", "a", "Organization")),
                 github_api._parse_repo(_repo("acme", "b", "Organization")),
                 github_api._parse_repo(_repo("me", "c"))]
        owners = github_api.owners_from_repos(repos, extra_orgs=["silent-org"])
        assert [(o.login, o.repo_count) for o in owners] == [("Acme", 2), ("me", 1), ("silent-org", 0)]
