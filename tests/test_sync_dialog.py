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


def test_log_controls_and_incremental_view():
    from PySide6.QtWidgets import QApplication
    from ui_dialogs import SyncDialog
    QApplication.instance() or QApplication([])
    dlg = SyncDialog()
    dlg._timer.stop()
    svc = dlg.svc
    for i in range(5):
        svc.log(f"ligne {i}", important=True)
    dlg._refresh(svc.snapshot())
    assert "ligne 4" in dlg.log_view.toPlainText()
    svc.log("ligne 5", important=True)
    dlg._refresh(svc.snapshot())
    assert dlg.log_view.toPlainText().count("ligne 5") == 1 and dlg.log_view.blockCount() >= 6
    dlg._clear_log()
    assert dlg.log_view.toPlainText() == "" and not svc.logs
    dlg.log_enabled.setChecked(False)
    dlg.log_level.setCurrentIndex(dlg.log_level.findData("detailed"))
    assert svc.settings["log_enabled"] is False and svc.settings["log_level"] == "detailed"
    dlg.perf.setCurrentIndex(dlg.perf.findData("eco"))
    dlg._apply()
    assert svc.settings["performance"] == "eco"


def test_peer_rows_updated_in_place():
    from PySide6.QtWidgets import QApplication
    from ui_dialogs import SyncDialog
    QApplication.instance() or QApplication([])
    dlg = SyncDialog()
    dlg._timer.stop()
    dlg.s["peers"].append({"id": "p1", "name": "Portable", "host": "100.1.1.1", "port": 47821, "secret": "x"})
    dlg._refresh(dlg.svc.snapshot())
    row = dlg._rows["p1"]
    dlg._refresh({**dlg.svc.snapshot(), "peers": {"p1": {"state": "syncing", "percent": 42, "detail": "Envoi"}}})
    assert dlg._rows["p1"] is row and row["bar"].value() == 42           # même widget, pas de reconstruction
    dlg.s["peers"].clear()
    dlg._refresh(dlg.svc.snapshot())
    assert "p1" not in dlg._rows
