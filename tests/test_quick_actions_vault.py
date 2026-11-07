"""Actions rapides (affichage, édition, icônes, lancement) et déverrouillage du vault dans l'interface."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core  # noqa: E402
import quick_actions as qa  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QPushButton  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


class TestLogic:
    def test_legacy_entries_are_loaded_and_dedup(self, isolated_data_dir):
        core.set_quick_apps([{"name": "VS Code", "cmd": "code {path}", "icon": "💙"},
                             {"name": "vs code", "cmd": "x"}, {"name": "", "cmd": "y"}, "junk"])
        actions = qa.load()
        assert [a.name for a in actions] == ["VS Code"] and actions[0].icon == "💙"

    def test_save_roundtrip(self, isolated_data_dir):
        qa.save([qa.QuickAction("Zed", "zed {path}", "mdi:flash", terminal=True)])
        assert qa.load()[0].terminal is True

    def test_validate(self):
        assert qa.validate(qa.QuickAction("", "x"))
        assert qa.validate(qa.QuickAction("a", ""))
        assert qa.validate(qa.QuickAction("a", "echo 'unterminated"))
        assert qa.validate(qa.QuickAction("A", "x"), [qa.QuickAction("a", "y")])
        assert qa.validate(qa.QuickAction("a", "code {path}")) == ""

    def test_path_with_spaces_stays_one_argument_and_no_shell(self, tmp_path):
        project = tmp_path / "my project; rm -rf ~"
        argv = qa.build_argv(qa.QuickAction("x", "code {path} --flag {name}"), project)
        assert argv == ["code", str(project), "--flag", project.name]

    def test_launch_runs_in_project_dir(self, tmp_path):
        out = tmp_path / "out.txt"
        action = qa.QuickAction("pwd", f"{sys.executable} -c \"import os;open(r'{out}','w').write(os.getcwd())\"")
        assert qa.launch(action, tmp_path) == ""
        import time
        for _ in range(50):
            if out.exists() and out.read_text():
                break
            time.sleep(0.1)
        assert Path(out.read_text()).resolve() == tmp_path.resolve()

    def test_launch_unknown_program_reports_error(self, tmp_path):
        assert "introuvable" in qa.launch(qa.QuickAction("x", "definitely-not-a-program-xyz"), tmp_path)


class TestUi:
    def test_edit_dialog_and_list(self, isolated_data_dir, monkeypatch):
        from ui_dialogs.quick_actions_dialog import QuickActionEditDialog, QuickActionsDialog
        qa.save([qa.QuickAction("A", "a {path}", "mdi:flash"), qa.QuickAction("B", "b", "mdi:flash")])
        dlg = QuickActionsDialog()
        assert dlg._list.count() == 2 and dlg.btn_edit.isEnabled() is False or dlg._list.currentRow() == 0
        # réordonner
        dlg._list.setCurrentRow(0)
        dlg._move(1)
        assert [a.name for a in qa.load()] == ["B", "A"]
        # modifier : l'éditeur est pré-rempli et le résultat enregistré
        edit = QuickActionEditDialog(None, qa.load()[0])
        assert edit.name.text() == "B"
        edit.name.setText("B2")
        edit.cmd.setText("b2 {path}")
        monkeypatch.setattr(QuickActionEditDialog, "exec", lambda self: (self._accept(), QDialog.Accepted)[1])
        dlg._list.setCurrentRow(0)
        dlg._edit()
        assert dlg._list.count() == 2
        # supprimer
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        dlg._list.setCurrentRow(0)
        dlg._remove()
        assert len(qa.load()) == 1

    def test_icon_button_exists_in_editor(self, isolated_data_dir):
        from ui_dialogs.quick_actions_dialog import QuickActionEditDialog
        dlg = QuickActionEditDialog()
        assert "icône" in dlg.btn_icon.text().lower() and dlg._icon == qa.DEFAULT_ICON

    def test_project_panel_shows_user_actions(self, isolated_data_dir, tmp_path):
        from ui_project_panel import ProjectPanel
        qa.save([qa.QuickAction("Mon outil", "echo {path}", "mdi:flash")])
        project = tmp_path / "p"
        project.mkdir()
        panel = ProjectPanel()
        panel.show_project(str(project))
        names = [panel._quick_layout.itemAt(i).widget().text().strip()
                 for i in range(panel._quick_layout.count()) if panel._quick_layout.itemAt(i).widget()]
        assert "Mon outil" in names and "Modifier" in names
        buttons = panel._quick_box.findChildren(QPushButton)
        assert len(buttons) == 2


class TestVaultUnlock:
    def test_dialog_unlocks_with_right_password(self, isolated_data_dir):
        from ui_dialogs.vault_unlock_dialog import VaultUnlockDialog
        core.vault_lock()
        core.vault_init("correct horse")
        core.vault_lock()
        dlg = VaultUnlockDialog()
        dlg.password.setText("wrong")
        dlg._try()
        assert not core.vault_is_unlocked() and dlg.error.text()
        dlg.password.setText("correct horse")
        dlg._try()
        assert core.vault_is_unlocked()
        core.vault_lock()

    def test_vault_dialog_has_unlock_button_and_toggles(self, isolated_data_dir, monkeypatch):
        from ui_dialogs import vault_unlock_dialog
        from ui_dialogs.vault_dialog import VaultDialog
        core.vault_init("pw-123456")
        core.vault_lock()
        dlg = VaultDialog()
        assert "Déverrouiller" in dlg._btn_lock.text() and dlg._status_lbl.text() == "Verrouillé"
        monkeypatch.setattr(vault_unlock_dialog, "ensure_unlocked", lambda *a, **k: core.vault_unlock("pw-123456"))
        dlg._toggle_lock()
        assert core.vault_is_unlocked() and dlg._btn_lock.text() == "Verrouiller"
        dlg._toggle_lock()
        assert not core.vault_is_unlocked()

    def test_adding_secret_prompts_unlock(self, isolated_data_dir, monkeypatch):
        from ui_dialogs import vault_dialog
        core.vault_init("pw-123456")
        core.vault_lock()
        called = []
        monkeypatch.setattr("ui_dialogs.vault_unlock_dialog.ensure_unlocked",
                            lambda *a, **k: called.append(1) or False)
        dlg = vault_dialog.VaultDialog()
        dlg._add_secret()
        assert called

    def test_startup_prompt_only_when_secrets(self, isolated_data_dir, monkeypatch):
        from ui_dialogs import vault_unlock_dialog as vu
        shown = []
        monkeypatch.setattr(vu.VaultUnlockDialog, "exec", lambda self: shown.append(1) or 0)
        core.vault_init("pw-123456")
        core.vault_lock()
        vu.prompt_at_startup()
        assert not shown                       # coffre vide : pas de fenêtre au démarrage
        core.vault_unlock("pw-123456")
        core.vault_store("K", "v")
        core.vault_lock()
        vu.prompt_at_startup()
        assert shown
