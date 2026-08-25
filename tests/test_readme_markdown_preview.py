import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core  # noqa: E402
import ui_project_panel  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def project_with_readme(isolated_data_dir, tmp_path):
    core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))
    path = core.create_instance(str(tmp_path), "ReadmeProject")
    (path / "README.md").write_text("# Titre\n\nUn **texte** en *markdown*.")
    return path


class TestReadmeFallbackAndMarkdownPreview:
    def test_empty_note_falls_back_to_readme(self, project_with_readme):
        panel = ui_project_panel.ProjectPanel()
        panel.show()
        panel.show_project(str(project_with_readme), "instance")

        assert panel._note_is_readme_fallback is True
        assert "Titre" in panel._note_edit.toPlainText()
        assert not panel._note_source_lbl.isHidden()

    def test_existing_note_takes_priority_over_readme(self, project_with_readme):
        core.set_instance_note(project_with_readme, "Ma note")
        panel = ui_project_panel.ProjectPanel()
        panel.show()
        panel.show_project(str(project_with_readme), "instance")

        assert panel._note_is_readme_fallback is False
        assert panel._note_edit.toPlainText() == "Ma note"
        assert panel._note_source_lbl.isHidden()

    def test_no_readme_and_no_note_shows_empty(self, isolated_data_dir, tmp_path):
        core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))
        path = core.create_instance(str(tmp_path), "NoReadme")
        panel = ui_project_panel.ProjectPanel()
        panel.show()
        panel.show_project(str(path), "instance")

        assert panel._note_is_readme_fallback is False
        assert panel._note_edit.toPlainText() == ""

    def test_toggle_preview_renders_markdown_and_locks_editing(self, project_with_readme):
        panel = ui_project_panel.ProjectPanel()
        panel.show()
        panel.show_project(str(project_with_readme), "instance")

        panel._toggle_note_preview()
        assert panel._note_preview_active is True
        assert panel._note_edit.isReadOnly() is True
        assert not panel._btn_save_note.isEnabled()
        assert "<h1" in panel._note_edit.toHtml().lower()

    def test_toggle_preview_twice_returns_to_original_editable_text(self, project_with_readme):
        panel = ui_project_panel.ProjectPanel()
        panel.show()
        panel.show_project(str(project_with_readme), "instance")
        original = panel._note_edit.toPlainText()

        panel._toggle_note_preview()
        panel._toggle_note_preview()

        assert panel._note_preview_active is False
        assert panel._note_edit.isReadOnly() is False
        assert panel._btn_save_note.isEnabled()
        assert panel._note_edit.toPlainText() == original

    def test_save_while_in_preview_switches_back_and_saves_raw_text(self, project_with_readme):
        panel = ui_project_panel.ProjectPanel()
        panel.show()
        panel.show_project(str(project_with_readme), "instance")

        panel._toggle_note_preview()
        panel._save_note()

        assert panel._note_preview_active is False
        saved = core.get_instance_note(project_with_readme)
        assert "Titre" in saved
        assert "<h1" not in saved.lower()  # texte source, pas le HTML rendu
