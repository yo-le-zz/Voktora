"""Git Insights 1.1 : parseurs, collecte sur un vrai dépôt, activité, Markdown, interface."""

import subprocess
from datetime import date
from pathlib import Path

import pytest
from plugin_stub import StubApi, load_plugin, submodule

GIT = ["git", "-c", "user.name=Ana", "-c", "user.email=ana@example.org", "-c", "commit.gpgsign=false"]


def git(cwd, *args):
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603


@pytest.fixture(scope="module")
def plg():
    return load_plugin("git-insights"), submodule("git-insights", "insights")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    for i in range(3):
        (r / "a.txt").write_text(str(i))
        (r / f"f{i}.txt").write_text("x")
        git(r, "add", "-A")
        git(r, "commit", "-q", "-m", f"commit {i}")
    git(r, "tag", "v1.0")
    (r / "a.txt").write_text("modifié")
    (r / "new.txt").write_text("n")
    return r


def runner(path):
    def run(args):
        p = subprocess.run(args, cwd=path, capture_output=True, text=True, check=False)  # noqa: S603
        return p.returncode, p.stdout + p.stderr
    return run


def test_parsers(plg):
    _m, ins = plg
    assert ins.parse_porcelain("?? n\n M a\nA  b\nMM c\n") == {"staged": 2, "modified": 2, "untracked": 1}
    assert ins.parse_shortlog("    5\tAna <a@x>\n    2\tBob <b@x>\n") == [("Ana", 5), ("Bob", 2)]
    assert ins.parse_log("abc\x1fAna\x1f2026-01-02\x1fMessage\nbad") == [{"hash": "abc", "author": "Ana", "date": "2026-01-02", "subject": "Message"}]
    assert ins.hot_files("a\nb\na\n\n") == [("a", 2), ("b", 1)]
    assert ins.bar(5, 10, 20) == "█" * 10 and ins.bar(0, 10) == "" and ins.bar(1, 1000) == "█"


def test_weekly_activity_buckets(plg):
    _m, ins = plg
    today = date(2026, 11, 13)                              # vendredi
    rows = ins.weekly_activity(["2026-11-13", "2026-11-09", "2026-11-02", "garbage", "2020-01-01"], weeks=3, today=today)
    assert rows == [("26/10", 0), ("02/11", 1), ("09/11", 2)]


def test_collect_real_repo(plg, repo):
    _m, ins = plg
    d = ins.collect(runner(repo))
    assert d["repo"] and d["branch"] == "main" and d["commits"] == 3 and d["tag"] == "v1.0"
    assert d["status"] == {"staged": 0, "modified": 1, "untracked": 1}
    assert d["authors"] == [("Ana", 3)] and len(d["recent"]) == 3 and d["recent"][0]["subject"] == "commit 2"
    assert d["ahead"] is None and ("a.txt", 3) in d["hot"]
    assert sum(c for _w, c in d["activity"]) == 3
    md = ins.to_markdown(d, "repo")
    assert "# Git — repo" in md and "**main**" in md and "`a.txt` — 3" in md


def test_collect_outside_repo_and_empty_repo(plg, tmp_path):
    _m, ins = plg
    assert ins.collect(runner(tmp_path)) == {"repo": False} and "pas un dépôt" in ins.to_markdown({"repo": False})
    empty = tmp_path / "e"
    empty.mkdir()
    git(empty, "init", "-q")
    assert ins.collect(runner(empty))["commits"] == 0


def test_tab(plg, repo, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    mod, _ins = plg
    api = StubApi(tmp_path / "d")
    mod.on_load(api)
    tab = api.tabs[0][1](None)
    tab.set_project(Path(repo))
    assert tab._cards["branch"].value.text().startswith("main") and tab._cards["commits"].value.text() == "3"
    assert "1 modifié(s)" in tab._cards["state"].value.text() and tab._recent.rowCount() == 3
    tab._copy()
    assert "Git — repo" in api.clipboard
    tab.set_project(Path(tmp_path))
    assert "pas un dépôt" in tab._message.text() and tab._recent.rowCount() == 0
