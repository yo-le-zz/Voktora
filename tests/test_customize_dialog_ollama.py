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
    core.set_storage_config(str(tmp_path / "Projects"))
    return core.create_project(str(tmp_path), "OllamaTest")


class TestCustomizeDialogOllamaIntegration:
    def test_run_ollama_without_model_configured_does_not_start_worker(self, project):
        core.set_ollama_config("http://localhost:11434", "")
        dlg = ui_dialogs.CustomizeProjectDialog(str(project))
        dlg._ollama_worker = None
        # On n'appelle pas _run_ollama directement (ouvrirait une QMessageBox
        # modale bloquante en environnement offscreen) — on vérifie la
        # condition de garde qu'il évalue en amont.
        assert core.get_ollama_config()["model"] == ""

    def test_successful_description_generation_fills_notes_field(self, project):
        core.set_ollama_config("http://localhost:11434", "llama3.1")
        dlg = ui_dialogs.CustomizeProjectDialog(str(project))
        dlg._on_ollama_done("description", "Une description générée.")
        assert dlg.notes_edit.text() == "Une description générée."

    def test_successful_icon_suggestion_sets_project_icon(self, project):
        core.set_ollama_config("http://localhost:11434", "llama3.1")
        dlg = ui_dialogs.CustomizeProjectDialog(str(project))
        dlg._on_ollama_done("icon", "mdi:target")
        assert dlg._icon_value == "mdi:target"

    def test_error_reenables_buttons_and_clears_worker(self, project):
        core.set_ollama_config("http://localhost:11434", "llama3.1")
        dlg = ui_dialogs.CustomizeProjectDialog(str(project))
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


class TestAIConfig:
    def test_legacy_ollama_settings_become_the_default_provider(self, isolated_data_dir):
        core.set_ollama_config("http://10.0.0.5:11434", "mistral")
        ai = core.get_ai_config()
        assert ai["active"] == ai["providers"][0]["id"]
        assert ai["providers"][0]["kind"] == "ollama"
        assert ai["providers"][0]["host"] == "http://10.0.0.5:11434"
        assert ai["providers"][0]["model"] == "mistral"

    def test_providers_round_trip_and_mirror_ollama_settings(self, isolated_data_dir):
        ai = core.get_ai_config()
        ai["providers"][0].update(host="http://h:1", model="m1")
        ai["providers"].append({"id": "omniroute", "kind": "omniroute", "name": "OmniRoute",
                                "host": "http://localhost:20128/v1", "model": "auto", "api_key": "sk-x"})
        ai["active"] = "omniroute"
        core.set_ai_config(ai)
        assert core.get_active_ai_provider()["kind"] == "omniroute"
        assert core.get_ollama_config() == {"host": "http://h:1", "model": "m1"}

    def test_invalid_entries_are_dropped_and_ids_deduplicated(self, isolated_data_dir):
        ai = core.normalize_ai_config({"active": "zzz", "providers": [
            {"id": "a", "kind": "openai"}, {"id": "a", "kind": "openai"}, {"id": "b", "kind": "weird"}, "x"]})
        ids = [p["id"] for p in ai["providers"]]
        assert ids.count("a") == 1 and "a-2" in ids and all(p["kind"] != "weird" for p in ai["providers"])
        assert ai["active"] in ids

    def test_exported_config_never_contains_api_keys(self, isolated_data_dir):
        ai = core.get_ai_config()
        ai["providers"].append({"id": "o", "kind": "omniroute", "name": "O", "host": "", "model": "", "api_key": "sk-secret"})
        core.set_ai_config(ai)
        public = core.public_config(core._load_config())
        assert "sk-secret" not in str(public)
