"""Fenêtre de synchronisation : construction et rafraîchissement sans erreur."""

import pytest
from sync import appio
from sync.appio import AppConfigIO


@pytest.fixture(autouse=True)
def _reset(isolated_data_dir):
    appio.reset_service_for_tests()
    yield
    appio.reset_service_for_tests()


def test_dialog_builds(qtbot_free=None):
    from PySide6.QtWidgets import QApplication
    from ui_dialogs import SyncDialog
    QApplication.instance() or QApplication([])
    dlg = SyncDialog()
    dlg._refresh(dlg.svc.snapshot())
    assert dlg.primary.count() >= 1
    dlg._timer.stop()


def test_appio_keeps_local_settings():
    io = AppConfigIO()
    cfg = io.load()
    cfg["app_config"]["theme"] = "nord"
    io.save({"app_config": {"theme": "nord"}})
    after = io.load()
    assert after["app_config"]["theme"] == "nord"
    assert "vault" in after and "github_account" in after
