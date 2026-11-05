import os
import sys

import core
import pytest
from core.github_api import RepoInfo

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
from ui_main import account_sync_dialog  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _repo(owner, name, **kw):
    return RepoInfo(full_name=f"{owner}/{name}", name=name, owner=owner, owner_type="User", private=False,
                    description="", clone_url=f"https://github.com/{owner}/{name}.git",
                    default_branch="main", pushed_at="", **kw)


@pytest.fixture
def dialog(isolated_data_dir, tmp_path):
    core.set_storage_config(str(tmp_path / "P"))
    dlg = account_sync_dialog.AccountSyncDialog(str(tmp_path))
    repos = [_repo("me", "a"), _repo("me", "forked", fork=True), _repo("me", "old", archived=True), _repo("o", "b")]
    dlg._on_loaded((repos, core.owners_from_repos(repos)))
    return dlg


def test_forks_and_archived_hidden_by_default_and_all_checked(dialog):
    assert [dialog.list.item(i).text().split()[0] for i in range(dialog.list.count())] == ["me/a", "o/b"]
    assert len(dialog._checked()) == 2 and dialog.btn_start.isEnabled()
    dialog.chk_forks.setChecked(True)
    assert dialog.list.count() == 3


def test_owner_filter_and_uncheck_all(dialog):
    dialog.owner_combo.setCurrentIndex(dialog.owner_combo.findData("o"))
    assert dialog.list.count() == 1
    dialog._set_all(account_sync_dialog.Qt.Unchecked)
    assert not dialog.btn_start.isEnabled()


def test_already_present_repos_are_hidden_then_shown_disabled(dialog, tmp_path):
    dialog._present = {"me/a"}
    dialog._render()
    assert dialog.list.count() == 1
    dialog.chk_hide_present.setChecked(False)
    assert dialog.list.count() == 2 and len(dialog._checked()) == 1


def test_summary_text():
    outcomes = [core.CloneOutcome("a/b", "cloned"), core.CloneOutcome("a/c", "skipped", message="déjà dans Voktora"),
                core.CloneOutcome("a/d", "failed", message="x\nboom")]
    text = account_sync_dialog.summarize(outcomes)
    assert "1 dépôt(s) cloné(s)" in text and "a/c" in text and "a/d — boom" in text
