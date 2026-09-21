"""Fenêtre principale : câblage des nouvelles fonctions (import, glisser-déposer, suppression, état)."""

import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core  # noqa: E402
from PySide6.QtCore import QMimeData, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from ui_main import MainWindow, import_dialog  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(isolated_data_dir, tmp_path, monkeypatch):
    # Les contrôles de démarrage ouvrent des dialogues modaux : hors sujet ici.
    monkeypatch.setattr(MainWindow, "_run_startup_health_check", lambda self: None)
    monkeypatch.setattr(MainWindow, "_show_migration_summary", lambda self: None)
    monkeypatch.setattr(MainWindow, "_run_update_check", lambda self: None)
    core.set_storage_config(str(tmp_path / "Projects"))
    w = MainWindow()
    yield w
    w.close()


def _mime(*paths) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


class TestWindow:
    def test_builds_and_lists_projects_grouped_by_category(self, window, tmp_path):
        core.create_project(str(tmp_path), "Alpha", category="Web")
        core.create_project(str(tmp_path), "Beta")
        window._invalidate_cache()
        window._refresh_all()
        tree = window._browser.get_list_view()._tree
        assert tree.topLevelItemCount() >= 2
        assert window._stat_projects.text() == "2" and window._stat_categories.text() == "1"

    def test_selecting_a_project_opens_the_panel(self, window, tmp_path):
        p = core.create_project(str(tmp_path), "Alpha")
        window._on_project_selected(str(p))
        assert window._right_stack.currentIndex() == 1 and window._sel_path == p

    def test_view_state_is_persisted_and_restored(self, window):
        window._browser._group_combo.setCurrentIndex(window._browser._group_combo.findData("github_owner"))
        assert core.get_app_config()["browser_group_by"] == "github_owner"
        fresh_state = core.get_app_config()
        assert fresh_state["browser_sort"] == core.DEFAULT_SORT

    def test_no_intent_or_instance_wording_left_in_menus(self, window):
        titles = " ".join(
            sub.text().lower()
            for top in window.menuBar().actions() if top.menu()
            for sub in top.menu().actions()
        )
        assert "intent" not in titles and "instance" not in titles


class TestDragAndDrop:
    def test_dropped_folder_and_zip_are_recognised_others_ignored(self, window, tmp_path):
        folder = tmp_path / "proj"
        folder.mkdir()
        z = tmp_path / "a.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("x/y.txt", "1")
        note = tmp_path / "notes.txt"
        note.write_text("x")
        found = MainWindow._dropped_sources(_mime(folder, z, note))
        assert found == [(str(folder), import_dialog.SOURCE_FOLDER), (str(z), import_dialog.SOURCE_ZIP)]

    def test_non_file_mime_is_ignored(self):
        assert MainWindow._dropped_sources(QMimeData()) == []

    def test_import_dialog_is_opened_prefilled(self, window, tmp_path, monkeypatch):
        seen = {}

        class FakeDialog:
            imported_path = None

            def __init__(self, drive, parent, source_path, source_kind):
                seen.update(path=source_path, kind=source_kind)

            def exec(self):
                return 0

        monkeypatch.setattr(import_dialog, "ImportDialog", FakeDialog)
        window._open_import_dialog("/some/folder", import_dialog.SOURCE_FOLDER)
        assert seen == {"path": "/some/folder", "kind": import_dialog.SOURCE_FOLDER}


class TestDelete:
    def _choose(self, monkeypatch, label_part):
        monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
        monkeypatch.setattr(QMessageBox, "clickedButton",
                            lambda self: next(b for b in self.buttons() if label_part in b.text()))
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))

    def test_forget_keeps_the_folder(self, window, tmp_path, monkeypatch):
        p = core.create_project(str(tmp_path), "Keep")
        (p / "f.txt").write_text("data")
        window._sel_path = p
        self._choose(monkeypatch, "Retirer")
        window.act_delete()
        assert p.exists() and core.get_project(p) is None

    def test_delete_removes_folder_and_entry(self, window, tmp_path, monkeypatch):
        p = core.create_project(str(tmp_path), "Gone")
        (p / "sub").mkdir()
        (p / "sub" / "f.txt").write_text("data")
        window._sel_path = p
        self._choose(monkeypatch, "Supprimer")
        window.act_delete()
        assert not p.exists() and core.get_project(p) is None

    def test_cancel_changes_nothing(self, window, tmp_path, monkeypatch):
        p = core.create_project(str(tmp_path), "Stay")
        window._sel_path = p
        self._choose(monkeypatch, "Annuler")
        window.act_delete()
        assert p.exists() and core.get_project(p) is not None


class TestExportAndNotes:
    def test_export_runs_with_progress_dialog(self, window, tmp_path, monkeypatch):
        p = core.create_project(str(tmp_path), "Exp")
        (p / "f.txt").write_text("data")
        window._sel_path = p
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
        window.act_export()
        backups = list(core.get_backups_dir().glob("Exp_*.zip"))
        assert len(backups) == 1
        with zipfile.ZipFile(backups[0]) as zf:
            assert "Exp/f.txt" in zf.namelist()

    def test_autosave_writes_only_changed_notes(self, window, tmp_path):
        p = core.create_project(str(tmp_path), "Notes")
        window._on_project_selected(str(p))
        panel = window._project_panel
        panel._note_edit.setPlainText("ma note")
        window._auto_save_note()
        assert core.get_project_note(p) == "ma note"
        core.set_project_note(p, "changée ailleurs")
        window._auto_save_note()       # texte inchangé depuis la dernière sauvegarde : rien à écrire
        assert core.get_project_note(p) == "changée ailleurs"


class TestMeridianMerge:
    def test_merge_external_config_accepts_legacy_and_new_formats(self, isolated_data_dir):
        data = {
            "instances": [{"name": "a", "path": "/x/a", "category": "Web"}],
            "intents": [{"name": "b", "path": "/x/b"}],
            "projects": [{"name": "c", "path": "/x/c"}],
            "categories": ["Web", "Perso"],
            "custom_statuses": {"wip": {"name": "WIP", "color": "#fff", "emoji": "🚧"}},
            "storage": {"instances_root": "/data/inst"},
        }
        added = core.merge_external_config(data)
        assert added == {"projects": 3, "categories": 2, "statuses": 1}
        assert core.merge_external_config(data) == {"projects": 0, "categories": 0, "statuses": 0}
        assert core.get_storage_config()["projects_root"] == "/data/inst"
        assert {c["name"] for c in core.list_categories()} == {"Web", "Perso"}

    def test_existing_data_is_never_overwritten(self, isolated_data_dir):
        core._load_config()["projects"].append(
            {"name": "mine", "path": "/x/a", "note": "à moi", "category": None})
        core.merge_external_config({"projects": [{"name": "theirs", "path": "/x/a", "note": "eux"}]})
        assert core.get_project("/x/a")["note"] == "à moi"
