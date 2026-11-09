"""Forges : analyse des remotes, distinction des forks, clients (réponses simulées), comptes."""

import pytest
from forges import accounts, base, hub
from forges.base import ForgeError, parse_remote
from forges.clients import ForgejoClient, GitHubClient, GitLabClient


@pytest.mark.parametrize("url,host,full", [
    ("https://github.com/yo-le-zz/Voktora.git", "github.com", "yo-le-zz/Voktora"),
    ("git@github.com:yo-le-zz/Voktora.git", "github.com", "yo-le-zz/Voktora"),
    ("ssh://git@forge.fedoraproject.org:22/fedora/pkg.git", "forge.fedoraproject.org", "fedora/pkg"),
    ("https://gitlab.com/groupe/sous/projet", "gitlab.com", "groupe/sous/projet"),
    ("https://user:tok@codeberg.org/a/b.git", "codeberg.org", "a/b"),
])
def test_parse_remote(url, host, full):
    r = parse_remote(url)
    assert r and r.host == host and r.full_name == full


@pytest.mark.parametrize("bad", ["", "nonsense", "https://github.com/seul", "/chemin/local"])
def test_parse_remote_rejects(bad):
    assert parse_remote(bad) is None


def test_guess_kind():
    assert base.guess_kind("github.com") == "github"
    assert base.guess_kind("gitlab.com") == "gitlab"
    assert base.guess_kind("gitlab.example.org") == "gitlab"
    assert base.guess_kind("forge.fedoraproject.org") == "forgejo"
    assert base.guess_kind("codeberg.org") == "forgejo"
    assert base.guess_kind("example.com") == ""


def test_fork_detected_from_upstream_remote():
    info = hub.project_info("x", [("origin", "git@github.com:moi/Voktora.git"),
                                  ("upstream", "https://github.com/yo-le-zz/Voktora.git")])
    assert info.is_fork and info.parent == "yo-le-zz/Voktora" and info.source == "upstream"
    assert "fork de yo-le-zz/Voktora" in info.badge() and info.forge_label == "GitHub"


def test_not_a_fork_when_upstream_is_same_repo():
    info = hub.project_info("x", [("origin", "https://github.com/a/b.git"), ("upstream", "git@github.com:a/b.git")])
    assert not info.is_fork


def test_tokens_scrubbed_in_remote_listing():
    info = hub.project_info("x", [("origin", "https://user:SECRET@gitlab.com/a/b.git")])
    assert "SECRET" not in str(info.remotes)


def test_clients_normalise_fork_info(monkeypatch):
    gh = GitHubClient("github.com", "t")
    monkeypatch.setattr(gh, "_get", lambda p: {"full_name": "moi/x", "fork": True, "html_url": "u", "clone_url": "c",
                                               "parent": {"full_name": "orig/x", "html_url": "pu"}})
    r = gh.repo("moi", "x")
    assert r.fork and r.parent == "orig/x" and r.parent_url == "pu"
    gl = GitLabClient("gitlab.com", "t")
    monkeypatch.setattr(gl, "_get", lambda p: {"path_with_namespace": "moi/x", "web_url": "w", "visibility": "private",
                                               "forked_from_project": {"path_with_namespace": "orig/x",
                                                                       "web_url": "pw"}})
    r = gl.repo("moi", "x")
    assert r.fork and r.parent == "orig/x" and r.private
    fj = ForgejoClient("forge.fedoraproject.org", "t")
    monkeypatch.setattr(fj, "_get", lambda p: {"full_name": "moi/x", "fork": False, "private": False})
    assert not fj.repo("moi", "x").fork


def test_pagination(monkeypatch):
    gh = GitHubClient("github.com", "t")
    pages = {1: [{"full_name": f"a/{i}"} for i in range(100)], 2: [{"full_name": "a/last"}]}
    monkeypatch.setattr(gh, "_get", lambda p: pages[int(p.rsplit("page=", 1)[1])])
    assert len(gh.list_repos()) == 101


def test_auth_headers():
    assert "PRIVATE-TOKEN" in GitLabClient("gitlab.com", "x")._headers()
    assert ForgejoClient("h.org", "x")._headers()["Authorization"] == "token x"
    assert GitHubClient("github.com", "x")._headers()["Authorization"] == "Bearer x"
    assert GitHubClient("github.com", "")._headers() == {}


def test_https_only():
    with pytest.raises(ForgeError):
        base.http_json("http://example.com/api", {})


def test_clean_host():
    assert accounts.clean_host("https://Forge.Fedoraproject.org/") == "forge.fedoraproject.org"
    for bad in ("", "a b", "../x", "nodot"):
        with pytest.raises(ForgeError):
            accounts.clean_host(bad)


def test_account_roundtrip_without_leaking_token(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(GitLabClient, "user", lambda self: {"login": "moi", "name": "Moi", "avatar_url": ""})
    acc = accounts.add_account("gitlab", "gitlab.com", "glpat-SECRET")
    listed = accounts.list_accounts()
    assert listed and "token" not in listed[0] and "SECRET" not in str(listed)
    assert accounts.get_token(acc["id"]) == "glpat-SECRET"
    accounts.remove_account(acc["id"])
    assert accounts.list_accounts() == []
    with pytest.raises(ForgeError):
        accounts.add_account("gitlab", "gitlab.com", "  ")


def test_confirm_with_api_unsets_false_fork(monkeypatch):
    hub._cache.clear()
    info = hub.project_info("x", [("origin", "https://github.com/moi/x.git"), ("upstream", "https://github.com/o/x.git")])
    monkeypatch.setattr(GitHubClient, "repo", lambda self, o, n: base.Repo("github", "github.com", "moi/x", fork=False))
    hub.confirm_with_api(info)
    assert info.is_fork            # l'upstream explicite reste un signe de fork même si l'API ne le confirme pas
    monkeypatch.setattr(GitHubClient, "repo", lambda self, o, n: base.Repo(
        "github", "github.com", "moi/x", fork=True, parent="vrai/parent", parent_url="pu"))
    hub._cache.clear()
    hub.confirm_with_api(info)
    assert info.parent == "vrai/parent" and info.source == "api"


def test_forges_dialog_builds(isolated_data_dir):
    from PySide6.QtWidgets import QApplication
    from ui_dialogs import ForgesDialog
    QApplication.instance() or QApplication([])
    dlg = ForgesDialog(None, {})
    dlg._fill_repos([("GitHub (@moi)", base.Repo("github", "github.com", "moi/x", fork=True, parent="o/x"))])
    assert dlg.repos.count() == 1 and "fork de o/x" in dlg.repos.item(0).text()
    dlg.only_forks.setChecked(True)
    assert dlg.repos.count() == 1


# ── 1.1.0 : tickets / demandes de fusion / CI en lecture seule ────────────────────────────

def _client(cls, routes, host="h"):
    client = cls(host, "tok")
    client._get = lambda path: next(v for k, v in routes.items() if path.startswith(k))
    return client


def test_github_issues_pulls_ci():
    c = _client(GitHubClient, {
        "/repos/o/r/issues": [{"number": 1, "title": "bug", "user": {"login": "a"}, "html_url": "u1", "updated_at": "2026-11-01T10"},
                              {"number": 2, "title": "une PR", "pull_request": {}, "user": {"login": "b"}}],
        "/repos/o/r/pulls": [{"number": 2, "title": "une PR", "user": {"login": "b"}, "html_url": "u2", "draft": True}],
        "/repos/o/r/actions/runs": {"workflow_runs": [{"status": "completed", "conclusion": "failure", "name": "CI", "html_url": "w"}]},
    })
    assert [i["number"] for i in c.issues("o", "r")] == [1]              # les PR ne sont pas des tickets
    assert c.pulls("o", "r")[0]["draft"] is True
    assert c.ci("o", "r") == {"state": "failure", "name": "CI", "url": "w"}


def test_gitlab_and_forgejo_activity():
    g = _client(GitLabClient, {
        "/projects/o%2Fr/issues": [{"iid": 3, "title": "t", "author": {"username": "u"}, "web_url": "w"}],
        "/projects/o%2Fr/merge_requests": [{"iid": 4, "title": "mr", "author": {"username": "u"}, "web_url": "m"}],
        "/projects/o%2Fr/pipelines": [{"id": 9, "status": "success", "web_url": "p"}]})
    assert g.issues("o", "r")[0]["number"] == 3 and g.pulls("o", "r")[0]["number"] == 4
    assert g.ci("o", "r")["state"] == "success"
    f = _client(ForgejoClient, {
        "/repos/o/r/issues": [{"number": 5, "title": "t", "user": {"login": "x"}, "html_url": "w"}],
        "/repos/o/r/pulls": [],
        "/repos/o/r/commits/main/status": {"state": "pending"},
        "/repos/o/r": {"full_name": "o/r", "default_branch": "main"}}, "forge.fedoraproject.org")
    assert f.issues("o", "r")[0]["number"] == 5 and f.pulls("o", "r") == []
    assert f.ci("o", "r")["state"] == "pending"


def test_project_activity_collects_errors_without_failing(monkeypatch):
    class Boom(GitHubClient):
        def issues(self, *a, **k):
            return [{"number": 1}]

        def pulls(self, *a, **k):
            raise ForgeError("403")

        def ci(self, *a, **k):
            return {"state": "success"}

    monkeypatch.setattr(hub, "project_info", lambda p: hub.ProjectForgeInfo(origin=parse_remote("https://github.com/o/r")))
    monkeypatch.setattr(hub, "_client_for_origin", lambda origin: Boom("github.com", ""))
    out = hub.project_activity("x")
    assert out["issues"] == [{"number": 1}] and out["ci"]["state"] == "success" and "pulls : 403" in out["errors"][0]
