"""Fenêtre « Espace disque » : analyse, nettoyage, double confirmation au-delà du seuil."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core  # noqa: E402
import diskusage as du  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox  # noqa: E402
from ui_dialogs import disk_dialog as dd  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def projects(tmp_path, isolated_data_dir):
    out = []
    for name in ("alpha", "beta"):
        root = tmp_path / name
        (root / "src").mkdir(parents=True)
        (root / "src" / "main.py").write_text("x")
        (root / "package.json").write_text("{}")
        (root / "node_modules" / "m").mkdir(parents=True)
        (root / "node_modules" / "m" / "i.js").write_bytes(b"x" * 20_000)
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "a.pyc").write_bytes(b"x" * 8_000)
        out.append(root)
    return out


def _sync(dialog):
    from ui_main import task_dialog as td

    def run(title, job):
        ctx = SimpleNamespace(progress=lambda *a, **k: None, is_cancelled=lambda: False, log=lambda *_: None)
        return SimpleNamespace(outcome=td.OUTCOME_OK, result=job(ctx), error=""), td
    dialog._run = run


def test_scan_fills_table_and_summary(projects):
    dlg = dd.DiskUsageDialog(paths=projects)
    _sync(dlg)
    dlg.scan()
    assert dlg._tree.topLevelItemCount() == 2
    assert "régénérables" in dlg._summary.text()
    dlg._tree.setCurrentItem(dlg._tree.topLevelItem(0))
    kinds = {dlg._items.topLevelItem(i).text(0) for i in range(dlg._items.topLevelItemCount())}
    assert {"node_modules", "__pycache__"} <= kinds
    assert dlg._btn_reset.isEnabled() and dlg._btn_clean.isEnabled()


def test_clean_selected_project(projects, monkeypatch):
    dlg = dd.DiskUsageDialog(paths=projects)
    _sync(dlg)
    dlg.scan()
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(dd.CategoryChoiceDialog, "exec", lambda self: QDialog.Accepted)
    first = dlg._selected_usage().path
    dlg._clean_selected()
    assert not (first / "__pycache__").exists() and (first / "node_modules").exists()    # deps : opt-in


def test_single_confirmation_below_threshold(projects, monkeypatch):
    dlg = dd.DiskUsageDialog(paths=projects)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(1) or QMessageBox.Yes)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: pytest.fail("seconde confirmation inattendue"))
    assert dlg.confirm_reset(10 * 1024 * 1024, 2) is True and len(asked) == 1


def test_double_confirmation_above_threshold(projects, monkeypatch):
    cfg = core.get_app_config()
    cfg["disk_reset_confirm_mb"] = 1
    core.set_app_config(cfg)
    dlg = dd.DiskUsageDialog(paths=projects)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("oups", True))
    assert dlg.confirm_reset(50 * 1024 * 1024, 2) is False                 # mauvais mot
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("réinitialiser", True))
    assert dlg.confirm_reset(50 * 1024 * 1024, 2) is True
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    assert dlg.confirm_reset(50 * 1024 * 1024, 2) is False                 # annulé
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    assert dlg.confirm_reset(50 * 1024 * 1024, 2) is False                 # refus dès la première


def test_reset_all_cancelled_by_user_deletes_nothing(projects, monkeypatch):
    dlg = dd.DiskUsageDialog(paths=projects)
    _sync(dlg)
    dlg.scan()
    monkeypatch.setattr(dd.CategoryChoiceDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    dlg._reset_all()
    assert all((p / "__pycache__").exists() for p in projects)


def test_reset_all_deletes_after_confirmation(projects, monkeypatch):
    dlg = dd.DiskUsageDialog(paths=projects)
    _sync(dlg)
    dlg.scan()
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(dd.CategoryChoiceDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg._reset_all()
    assert not any((p / "__pycache__").exists() for p in projects)
    assert all((p / "src" / "main.py").exists() for p in projects)


def test_category_dialog_totals(projects):
    usages = du.scan_many(projects)
    dlg = dd.CategoryChoiceDialog(None, "t", "i", usages)
    assert dlg.categories() == [du.CACHE]                  # rien à compiler ici ; dépendances : opt-in
    assert dlg.total_bytes() == sum(u.reclaimable_for(dlg.categories()) for u in usages)
    dlg._boxes[du.DEPS].setChecked(True)
    assert du.DEPS in dlg.categories() and dlg.total_bytes() > 40_000


def test_settings_have_threshold_and_keep(isolated_data_dir):
    from ui_dialogs.config_dialog import ConfigDialog
    dlg = ConfigDialog()
    dlg.disk_threshold_spin.setValue(123)
    dlg.snapshot_keep_spin.setValue(7)
    import ui_dialogs.config_dialog as cd
    cd.QMessageBox.information = staticmethod(lambda *a, **k: None)
    dlg._save()
    cfg = core.get_app_config()
    assert cfg["disk_reset_confirm_mb"] == 123 and cfg["snapshot_keep"] == 7
