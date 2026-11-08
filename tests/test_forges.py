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
