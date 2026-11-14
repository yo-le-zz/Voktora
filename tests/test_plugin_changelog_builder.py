"""Changelog Builder : analyse des Conventional Commits, rendu, SemVer, insertion, dialogue sur un vrai dépôt."""

import subprocess
from datetime import date

import pytest
from plugin_stub import StubApi, load_plugin, submodule

GIT = ["git", "-c", "user.name=Ana", "-c", "user.email=a@x.org", "-c", "commit.gpgsign=false"]


@pytest.fixture(scope="module")
def plg():
    return load_plugin("changelog-builder"), submodule("changelog-builder", "core")


def commit(core, subject, body=""):
    return core.Commit("abc1234", subject, body, "Ana")


def test_classification(plg):
    _m, core = plg
    assert core.classify(commit(core, "feat(ui): bouton")) == ("feat", "ui", "bouton")
    assert core.classify(commit(core, "fix: crash")) == ("fix", "", "crash")
    assert core.classify(commit(core, "feat!: nouvelle API"))[0] == "breaking"
    assert core.classify(commit(core, "refactor: x", "BREAKING CHANGE: format"))[0] == "breaking"
    assert core.classify(commit(core, "Fusion de trucs"))[0] == "other" and core.classify(commit(core, "wip: x"))[0] == "other"
    assert core.classify(commit(core, "Feature: alias"))[0] == "feat"


def test_render_order_skip_and_empty(plg):
    _m, core = plg
    cs = [commit(core, "chore: deps"), commit(core, "fix(core): bug"), commit(core, "feat: truc"), commit(core, "feat!: casse")]
    md = core.render(cs, "2.0.0", date(2026, 11, 14), skip=("chore",))
    assert md.startswith("## [2.0.0] — 2026-11-14")
    assert md.index("Changements incompatibles") < md.index("Nouveautés") < md.index("Corrections") and "deps" not in md
    assert "- **core** : bug (`abc1234`)" in md
    assert "_Aucun changement._" in core.render([], "1.0.0", date(2026, 1, 1))


def test_next_version(plg):
    _m, core = plg
    fixes, feat, brk = [commit(core, "fix: a")], [commit(core, "feat: a")], [commit(core, "feat!: a")]
    assert core.next_version("v1.4.2", fixes) == "1.4.3" and core.next_version("1.4.2", feat) == "1.5.0"
    assert core.next_version("1.4.2", brk) == "2.0.0" and core.next_version("0.3.1", brk) == "0.4.0"
    assert core.next_version("", fixes) == "0.0.1"


def test_insert_keeps_history(plg):
    _m, core = plg
    old = "# Changelog\n\nIntro.\n\n## [1.0.0] — 2026-01-01\n\n- ancien\n"
    out = core.insert(old, "## [1.1.0] — 2026-02-02\n\n- nouveau\n")
    assert out.index("Intro.") < out.index("1.1.0") < out.index("1.0.0") and "- ancien" in out
    assert core.insert("", "## [1.0.0]\n").startswith("# Changelog\n\n## [1.0.0]")
    assert core.insert("# Notes\ntexte\n", "## [1.0.0]\n").endswith("## [1.0.0]\n\n")


def test_parse_log_roundtrip(plg):
    _m, core = plg
    text = "a1\x1ffeat: x\x1fAna\x1fcorps\x1e\nb2\x1ffix: y\x1fBob\x1f\x1e\n"
    assert [(c.hash, c.subject, c.body, c.author) for c in core.parse_log(text)] == [("a1", "feat: x", "corps", "Ana"), ("b2", "fix: y", "", "Bob")]


def test_dialog_on_real_repo(plg, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    mod, _core = plg
    r = tmp_path / "r"
    r.mkdir()
    run = lambda *a: subprocess.run([*GIT, *a], cwd=r, check=True, capture_output=True)  # noqa: E731, S603
    run("init", "-q", "-b", "main")
    for i, msg in enumerate(["chore: init", "feat: base"]):
        (r / f"f{i}").write_text("x")
        run("add", "-A")
        run("commit", "-q", "-m", msg)
    run("tag", "v1.0.0")
    for i, msg in enumerate(["fix(api): erreur 500", "feat: export", "chore: nettoyage"], start=2):
        (r / f"f{i}").write_text("x")
        run("add", "-A")
        run("commit", "-q", "-m", msg)
    api = StubApi(tmp_path / "d", r)
    mod.on_load(api)
    dlg = mod.ChangelogDialog(api, r, True)
    assert dlg.since.currentText() == "v1.0.0" and "3 commit(s)" in dlg.info.text() and dlg.version.text() == "1.1.0"
    text = dlg.preview.toPlainText()
    assert "**api** : erreur 500" in text and "export" in text and "nettoyage" not in text
    dlg.chore.setChecked(False)
    dlg.render()
    assert "nettoyage" in dlg.preview.toPlainText()
    (r / "CHANGELOG.md").write_text("# Changelog\n\n## [1.0.0] — 2026-01-01\n\n- ancien\n")
    dlg.write()
    out = (r / "CHANGELOG.md").read_text()
    assert out.index("[1.1.0]") < out.index("[1.0.0]") and "- ancien" in out
    dlg.since.setCurrentText("tag-inexistant")
    dlg.generate()
    assert "refusé" in dlg.info.text() and dlg.commits == []
    dlg.copy()
    assert api.notices
