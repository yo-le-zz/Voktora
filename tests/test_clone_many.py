"""Clonage en lot des dépôts d'un compte."""

from __future__ import annotations

import threading
from pathlib import Path

import core
import pytest
from core.github_api import RepoInfo


def _repo(owner, name, **kw):
    return RepoInfo(full_name=f"{owner}/{name}", name=name, owner=owner, owner_type="User", private=False,
                    description="", clone_url=f"https://github.com/{owner}/{name}.git",
                    default_branch="main", pushed_at="", **kw)


@pytest.fixture
def env(isolated_data_dir, tmp_path, monkeypatch):
    core.set_storage_config(str(tmp_path / "Projects"))
    calls, lock = [], threading.Lock()

    def fake_clone(url, target, token="", branch="", on_output=None, cancel=None):
        if "boom" in url:
            raise RuntimeError("git clone a échoué : dépôt introuvable")
        target.mkdir(parents=True)
        (target / ".git").mkdir()
        (target / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {url}\n')
        (target / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        with lock:
            calls.append(url)
        if on_output:
            on_output("Receiving objects: 100%")
        return ""

    monkeypatch.setattr(core.git_ops, "git_clone", fake_clone)
    return tmp_path / "Projects", calls


def test_clones_registers_and_groups_by_owner(env):
    root, calls = env
    progress = []
    outcomes = core.clone_many([_repo("me", "a"), _repo("orgx", "b"), _repo("me", "c")],
                               on_progress=lambda d, t, n: progress.append((d, t)))
    assert sorted(o.status for o in outcomes) == ["cloned"] * 3
    assert len(calls) == 3 and progress[-1] == (3, 3)
    projects = {e["name"]: e for e in core.list_projects()}
    assert set(projects) == {"a", "b", "c"}
    assert projects["b"]["category"] == "orgx" and projects["a"]["github_repo"].endswith("me/a.git")
    assert (root / "a" / ".git").is_dir()


def test_already_registered_and_existing_folders_are_skipped(env):
    root, calls = env
    core.clone_many([_repo("me", "a")])
    (root / "taken").mkdir()
    outcomes = core.clone_many([_repo("me", "a"), _repo("me", "taken")])
    by = {o.repo: o for o in outcomes}
    assert by["me/a"].status == "skipped" and "déjà" in by["me/a"].message
    assert by["me/taken"].status == "cloned" and by["me/taken"].path.name == "me-taken"
    assert len(calls) == 2


def test_same_name_from_two_owners_gets_prefixed(env):
    outcomes = core.clone_many([_repo("x", "tool"), _repo("y", "tool")])
    assert sorted(o.path.name for o in outcomes) == ["tool", "y-tool"]


def test_one_failure_does_not_stop_the_others(env):
    outcomes = core.clone_many([_repo("me", "ok"), _repo("me", "boom"), _repo("me", "ok2")])
    by = {o.repo: o for o in outcomes}
    assert by["me/boom"].status == "failed" and "introuvable" in by["me/boom"].message
    assert by["me/ok"].status == by["me/ok2"].status == "cloned"
    assert {e["name"] for e in core.list_projects()} == {"ok", "ok2"}


def test_category_override_and_none(env):
    core.clone_many([_repo("me", "a")], category="Perso")
    core.clone_many([_repo("me", "b")], category=None)
    cats = {e["name"]: e["category"] for e in core.list_projects()}
    assert cats == {"a": "Perso", "b": None}


def test_cancellation_raises_but_keeps_finished_projects(env):
    state = {"n": 0}

    def cancel():
        state["n"] += 1
        return state["n"] > 3

    with pytest.raises(core.OperationCancelled):
        core.clone_many([_repo("me", f"r{i}") for i in range(8)], workers=1, cancel=cancel)
    for entry in core.list_projects():
        assert Path(entry["path"]).is_dir()


def test_git_progress_lines_are_parsed():
    assert core.parse_git_progress("Receiving objects:  45% (450/1000), 1.2 MiB | 2 MiB/s") == ("Réception", 45)
    assert core.parse_git_progress("remote: Compressing objects: 100% (12/12), done.") == ("Compression", 100)
    assert core.parse_git_progress("Cloning into 'x'...") is None
