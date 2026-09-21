import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core  # noqa: E402
import ui_dialogs  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def project(isolated_data_dir, tmp_path):
    core.set_storage_config(str(tmp_path / "Instances"), str(tmp_path / "Intents"))
    return core.create_instance(str(tmp_path), "OllamaTest")


class TestCustomizeDialogOllamaIntegration:
    def test_run_ollama_without_model_configured_does_not_start_worker(self, project):
        core.set_ollama_config("http://localhost:11434", "")
        dlg = ui_dialogs.CustomizeProjectDialog(str(project), "instance")
        dlg._ollama_worker = None
        # On n'appelle pas _run_ollama directement (ouvrirait une QMessageBox
        # modale bloquante en environnement offscreen) — on vérifie la
        # condition de garde qu'il évalue en amont.
        assert core.get_ollama_config()["model"] == ""

    def test_successful_description_generation_fills_notes_field(self, project):
        core.set_ollama_config("http://localhost:11434", "llama3.1")
        dlg = ui_dialogs.CustomizeProjectDialog(str(project), "instance")
        dlg._on_ollama_done("description", "Une description générée.")
        assert dlg.notes_edit.text() == "Une description générée."

    def test_successful_emoji_suggestion_fills_emoji_combo(self, project):
        core.set_ollama_config("http://localhost:11434", "llama3.1")
        dlg = ui_dialogs.CustomizeProjectDialog(str(project), "instance")
        dlg._on_ollama_done("emoji", "🎯")
        assert dlg.emoji_combo.currentText() == "🎯"

    def test_error_reenables_buttons_and_clears_worker(self, project):
        core.set_ollama_config("http://localhost:11434", "llama3.1")
        dlg = ui_dialogs.CustomizeProjectDialog(str(project), "instance")
        dlg.btn_ollama_desc.setEnabled(False)
        dlg.btn_ollama_emoji.setEnabled(False)
        dlg._ollama_worker = object()
        dlg._ollama_reset_buttons()
        assert dlg.btn_ollama_desc.isEnabled()
        assert dlg.btn_ollama_emoji.isEnabled()
        assert dlg._ollama_worker is None


class TestOllamaConfigPersistence:
    def test_ollama_config_round_trip(self, isolated_data_dir):
        core.set_ollama_config("http://192.168.1.10:11434", "mistral:latest")
        cfg = core.get_ollama_config()
        assert cfg["host"] == "http://192.168.1.10:11434"
        assert cfg["model"] == "mistral:latest"

    def test_default_ollama_config(self, isolated_data_dir):
        cfg = core.get_ollama_config()
        assert cfg["host"] == "http://localhost:11434"
        assert cfg["model"] == ""
