"""Fenêtre des snapshots : liste versionnée, détails, restauration sur place, comparaison avec diff."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import snapshots as sn  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from ui_dialogs import snapshot_dialog as sd  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def project(tmp_path, isolated_data_dir):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.txt").write_text("one\n")
    (root / "b.txt").write_text("two\n")
    return root


def _sync_run(dialog):
    """Exécute les tâches tout de suite (sans fenêtre modale) en gardant le même contrat."""
    from ui_main import task_dialog as td

    def run(title, job):
        ctx = SimpleNamespace(progress=lambda *a, **k: None, is_cancelled=lambda: False, log=lambda *_: None)
        try:
            return SimpleNamespace(outcome=td.OUTCOME_OK, result=job(ctx), error=""), td
        except Exception as exc:          # noqa: BLE001
            return SimpleNamespace(outcome=td.OUTCOME_ERROR, result=None, error=str(exc)), td
    dialog._run = run


def test_list_shows_versions_and_details(project):
    sn.create(project, "premier", note="note A")
    sn.create(project, "second")
    dlg = sd.SnapshotDialog(project)
    assert dlg._tree.topLevelItemCount() == 2
    assert dlg._tree.topLevelItem(0).text(0).startswith("v2")
    dlg._tree.setCurrentItem(dlg._tree.topLevelItem(1))
    assert "note A" in dlg._details.toPlainText()
    assert dlg._btn_restore.menu() is not None and dlg._btn_compare.menu() is not None


def test_create_through_dialog_with_options(project, monkeypatch):
    dlg = sd.SnapshotDialog(project)
    _sync_run(dlg)

    class Fake(sd.SnapshotCreateDialog):
        def exec(self):
            self.label.setText("depuis l'UI")
            self.note.setPlainText("n")
            return sd.QDialog.Accepted
    monkeypatch.setattr(sd, "SnapshotCreateDialog", Fake)
    dlg._create()
    assert dlg._tree.topLevelItemCount() == 1 and "depuis l'UI" in dlg._tree.topLevelItem(0).text(0)


def test_restore_in_place_from_dialog(project, monkeypatch):
    sn.create(project, "bon")
    (project / "a.txt").write_text("CASSÉ")
    dlg = sd.SnapshotDialog(project)
    _sync_run(dlg)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg._tree.setCurrentItem(dlg._tree.topLevelItem(0))
    dlg._restore_in_place()
    assert (project / "a.txt").read_text() == "one\n"
    assert dlg._tree.topLevelItemCount() == 2                       # + snapshot « Avant restauration »


def test_comparison_dialog_filters_and_shows_diff(project):
    snap = sn.create(project)
    (project / "a.txt").write_text("one\nchanged\n")
    os.rename(project / "b.txt", project / "c.txt")
    cmp = sn.compare(snap, None, project)
    dlg = sd.ComparisonDialog(cmp, "t", snap, None, project)
    assert dlg._tree.topLevelItemCount() == 2
    labels = {dlg._tree.topLevelItem(i).text(1) for i in range(2)}
    assert labels == {"Modifié", "Renommé"}
    dlg._filter.setText("renomm")
    assert dlg._tree.topLevelItemCount() == 1
    dlg._filter.setText("")
    for i in range(dlg._tree.topLevelItemCount()):
        if dlg._tree.topLevelItem(i).text(1) == "Modifié":
            dlg._tree.setCurrentItem(dlg._tree.topLevelItem(i))
    assert "+changed" in dlg._diff.toPlainText()


def test_verify_reports_tampering(project, tmp_path, monkeypatch):
    snap = sn.create(project)
    dlg = sd.SnapshotDialog(project)
    _sync_run(dlg)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append("ok"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append("bad"))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append("error"))
    dlg._tree.setCurrentItem(dlg._tree.topLevelItem(0))
    dlg._verify()
    assert shown == ["ok"]
    import zipfile
    tampered = snap.with_suffix(".tmp")
    with zipfile.ZipFile(snap) as src, zipfile.ZipFile(tampered, "w") as dst:
        for item in src.infolist():
            dst.writestr(item.filename, b"TAMPERED" if item.filename == "files/a.txt" else src.read(item))
    tampered.replace(snap)
    dlg._verify()
    assert shown[-1] in ("bad", "error") and len(shown) == 2
