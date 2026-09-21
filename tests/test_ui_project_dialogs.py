"""Dialogues d'import, de progression, de catégories, de création et de clone (Qt hors écran)."""

import os
import sys
import time
import zipfile
from pathlib import Path
from typing import ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402
from ui_dialogs import CategoriesDialog  # noqa: E402
from ui_dialogs.categories_dialog import CategoryEditor  # noqa: E402
from ui_main import (  # noqa: E402
    clone_dialog,
    create_dialog,
    github_dialog,
    import_dialog,
    repo_picker,
    task_dialog,
)

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def root(isolated_data_dir, tmp_path):
    core.set_storage_config(str(tmp_path / "Projects"))
    return tmp_path / "Projects"


@pytest.fixture
def messages(monkeypatch):
    """Capture les boîtes de message au lieu de bloquer sur exec()."""
    seen = {"warning": [], "critical": [], "information": []}
    for kind in seen:
        monkeypatch.setattr(QMessageBox, kind,
                            staticmethod(lambda *a, _k=kind, **k: seen[_k].append(a[2] if len(a) > 2 else "")))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    return seen


class TestTaskDialog:
    def test_success_returns_result(self):
        done = task_dialog.run_task(None, "t", lambda ctx: 42)
        assert done.outcome == task_dialog.OUTCOME_OK and done.result == 42

    def test_error_message_is_kept(self):
        def boom(ctx):
            raise ValueError("boom")

        done = task_dialog.run_task(None, "t", boom)
        assert done.outcome == task_dialog.OUTCOME_ERROR and done.error == "boom"

    def test_operation_cancelled_is_reported_as_cancelled(self):
        def cancelled(ctx):
            raise core.OperationCancelled()

        assert task_dialog.run_task(None, "t", cancelled).outcome == task_dialog.OUTCOME_CANCELLED

    def test_user_cancel_stops_the_job(self):
        def job(ctx):
            while not ctx.is_cancelled():
                time.sleep(0.01)
            raise core.OperationCancelled()

        dlg = task_dialog.TaskDialog("t", job)
        QTimer.singleShot(80, dlg.reject)
        dlg.exec()
        assert dlg.outcome == task_dialog.OUTCOME_CANCELLED

    def test_progress_updates_bar_and_label(self):
        seen = {}

        def job(ctx):
            ctx.progress(50, 100, "fichier.txt")
            ctx.progress(100, 100, "fichier.txt")   # le dernier appel est toujours transmis
            return "ok"

        dlg = task_dialog.TaskDialog("t", job)
        dlg._worker.progress.connect(lambda d, t, c: seen.update(done=d, total=t, cur=c))
        dlg.exec()
        assert seen["total"] == 100 and seen["done"] == 100 and dlg._bar.value() == 1000

    def test_ui_thread_is_not_blocked_during_job(self):
        """Régression du freeze : la boucle d'événements continue de tourner pendant la tâche."""
        ticks = []

        def job(ctx):
            time.sleep(0.3)
            return None

        dlg = task_dialog.TaskDialog("t", job)
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(20)
        dlg.exec()
        timer.stop()
        assert len(ticks) >= 5

    @pytest.mark.parametrize("n,expected", [(10, "10 o"), (2048, "2.0 Ko"), (5 * 1024**2, "5.0 Mo")])
    def test_format_bytes(self, n, expected):
        assert task_dialog.format_bytes(n) == expected


class TestImportDialog:
    def _folder(self, tmp_path, name="ext"):
        src = tmp_path / "elsewhere" / name
        src.mkdir(parents=True)
        (src / "main.py").write_text("x")
        return src

    def test_move_folder_import(self, root, tmp_path, messages):
        src = self._folder(tmp_path)
        dlg = import_dialog.ImportDialog(str(tmp_path), None, str(src), import_dialog.SOURCE_FOLDER)
        assert dlg.mode() == core.IMPORT_MOVE and dlg.name_edit.text() == "ext"
        dlg.category_combo.setCurrentText("Import")
        dlg._start_import()
        assert dlg.imported_path == root / "ext" and not src.exists()
        assert core.get_project(root / "ext")["category"] == "Import"

    def test_zip_import_suggests_name_and_describes_archive(self, root, tmp_path, messages):
        z = tmp_path / "a.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("monproj/main.py", "print(1)")
        dlg = import_dialog.ImportDialog(str(tmp_path), None, str(z), import_dialog.SOURCE_ZIP)
        assert dlg.kind() == import_dialog.SOURCE_ZIP and dlg.name_edit.text() == "monproj"
        assert "1 fichier" in dlg._source_info.text()
        dlg._start_import()
        assert (root / "monproj" / "main.py").exists()

    def test_path_kind_is_autodetected(self, root, tmp_path):
        src = self._folder(tmp_path)
        dlg = import_dialog.ImportDialog(str(tmp_path), None, str(src), import_dialog.SOURCE_ZIP)
        assert dlg.kind() == import_dialog.SOURCE_FOLDER   # le chemin réel prime sur la valeur initiale

    def test_link_mode_keeps_folder_in_place(self, root, tmp_path, messages):
        src = self._folder(tmp_path)
        dlg = import_dialog.ImportDialog(str(tmp_path), None, str(src))
        dlg._mode_buttons[core.IMPORT_LINK].setChecked(True)
        dlg._start_import()
        assert dlg.imported_path == src and (src / "main.py").exists()

    def test_name_conflict_is_flagged_and_reported_without_touching_source(self, root, tmp_path, messages):
        (root / "ext").mkdir(parents=True)
        src = self._folder(tmp_path)
        dlg = import_dialog.ImportDialog(str(tmp_path), None, str(src))
        assert "déjà utilisé" in dlg._preview.text()
        dlg._start_import()
        assert messages["critical"] and dlg.imported_path is None and (src / "main.py").exists()

    def test_invalid_source_is_refused(self, root, tmp_path, messages):
        dlg = import_dialog.ImportDialog(str(tmp_path), None, str(tmp_path / "nope"))
        dlg.name_edit.setText("x")
        dlg._start_import()
        assert messages["warning"] and dlg.imported_path is None

    def test_invalid_name_is_refused(self, root, tmp_path, messages):
        src = self._folder(tmp_path)
        dlg = import_dialog.ImportDialog(str(tmp_path), None, str(src))
        dlg.name_edit.setText("a/b")
        dlg._start_import()
        assert messages["warning"] and src.exists()

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_empty_path_is_not_a_source(self, raw):
        # Régression : Path("") vaut « . », un champ vide passait pour un dossier valide.
        assert import_dialog.classify_path(raw) is None

    def test_regular_file_is_not_a_source(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("x")
        assert import_dialog.classify_path(str(f)) is None


class TestCategoriesDialog:
    def test_lists_categories_with_counts(self, isolated_data_dir, tmp_path):
        core.add_category("Web", "🌐", "#89b4fa")
        p = tmp_path / "p"
        p.mkdir()
        core.register_project(p, str(tmp_path), name="p", category="Web")
        dlg = CategoriesDialog()
        item = dlg.categories_list.item(0)
        assert "Web" in item.text() and "1 projet" in item.text()

    def test_editor_values_and_color_clear(self, isolated_data_dir):
        editor = CategoryEditor(None, "A", "📁", "#112233")
        assert editor.values() == ("A", "📁", "#112233")
        editor._clear_color()
        assert editor.values()[2] == ""

    def test_delete_moves_projects_to_uncategorized(self, isolated_data_dir, tmp_path, messages):
        core.add_category("Old")
        p = tmp_path / "p"
        p.mkdir()
        core.register_project(p, str(tmp_path), name="p", category="Old")
        dlg = CategoriesDialog()
        dlg.categories_list.setCurrentRow(0)
        dlg._delete()
        assert core.list_categories() == [] and core.get_project(p)["category"] is None
        assert dlg.has_changes()

    def test_move_up_down(self, isolated_data_dir):
        core.add_category("A")
        core.add_category("B")
        dlg = CategoriesDialog()
        dlg.categories_list.setCurrentRow(1)
        dlg._move(-1)
        assert [c["name"] for c in core.list_categories()] == ["B", "A"]

    def test_from_github_owner_button(self, isolated_data_dir, tmp_path, messages):
        p = tmp_path / "p"
        p.mkdir()
        core.register_project(p, str(tmp_path), name="p", github_repo="https://github.com/acme/p")
        dlg = CategoriesDialog()
        dlg._from_github()
        assert core.get_project(p)["category"] == "acme"
        assert messages["information"]


class TestCreateDialog:
    def test_get_data_feeds_create_project(self, root, tmp_path):
        dlg = create_dialog.CreateDialog()
        dlg.name_edit.setText("Nouveau")
        dlg.category_combo.setCurrentText("Clients")
        dlg.repo_edit.setText("https://github.com/acme/nouveau")
        dlg.git_init_check.setChecked(False)
        data = dlg.get_data()
        assert data["name"] == "Nouveau" and data["category"] == "Clients"
        path = core.create_project(**{**data, "drive": str(tmp_path)})
        assert core.get_project(path)["github_repo"] == "https://github.com/acme/nouveau"

    def test_invalid_repo_url_is_rejected(self, root, messages):
        dlg = create_dialog.CreateDialog()
        dlg.name_edit.setText("X")
        dlg.repo_edit.setText("ext::sh -c evil")
        dlg._validate()
        assert messages["warning"] and dlg.result() != QDialog.Accepted

    def test_default_category_is_preselected(self, root):
        core.add_category("Web")
        assert create_dialog.CreateDialog(default_category="Web").get_data()["category"] == "Web"


class TestCloneDialog:
    def test_url_tab_clone_calls_core_with_clean_arguments(self, root, tmp_path, messages, monkeypatch):
        calls = {}

        def fake_clone(url, drive, name=None, branch="", token="", category=None, on_output=None, cancel=None):
            calls.update(url=url, name=name, branch=branch, category=category)
            on_output("Cloning into 'depot'...")
            return root / name

        monkeypatch.setattr(core.projects, "clone_project", fake_clone)
        dlg = clone_dialog.CloneDialog(str(tmp_path))
        dlg.tabs.setCurrentIndex(1)
        dlg.url_edit.setText("https://github.com/acme/depot.git")
        assert dlg.name_edit.text() == "depot"
        dlg.branch_edit.setText("dev")
        dlg.category_combo.setCurrentIndex(dlg.category_combo.findData("__owner__"))
        dlg._start_clone()
        assert calls == {"url": "https://github.com/acme/depot.git", "name": "depot",
                         "branch": "dev", "category": "acme"}
        assert dlg.cloned_path == root / "depot"

    def test_invalid_url_is_refused_before_cloning(self, root, tmp_path, messages, monkeypatch):
        monkeypatch.setattr(core.projects, "clone_project", lambda *a, **k: pytest.fail("ne doit pas cloner"))
        dlg = clone_dialog.CloneDialog(str(tmp_path))
        dlg.tabs.setCurrentIndex(1)
        dlg.url_edit.setText("--upload-pack=evil")
        dlg.name_edit.setText("x")
        dlg._start_clone()
        assert messages["warning"]

    def test_clone_error_is_reported(self, root, tmp_path, messages, monkeypatch):
        def failing(*a, **k):
            raise RuntimeError("git clone a échoué")

        monkeypatch.setattr(core.projects, "clone_project", failing)
        dlg = clone_dialog.CloneDialog(str(tmp_path))
        dlg.tabs.setCurrentIndex(1)
        dlg.url_edit.setText("https://github.com/a/b.git")
        dlg._start_clone()
        assert messages["critical"] and dlg.cloned_path is None


class TestRepoPickerAndGithubDialog:
    REPOS: ClassVar[list] = [
        core.github_api.RepoInfo("acme/site", "site", "acme", "Organization", True, "Le site web",
                                 "https://github.com/acme/site.git", "main", ""),
        core.github_api.RepoInfo("me/tool", "tool", "me", "User", False, "",
                                 "https://github.com/me/tool.git", "master", ""),
    ]

    def test_filter_by_owner_and_text(self):
        f = repo_picker.filter_repos
        assert [r.name for r in f(self.REPOS, repo_picker.ALL_OWNERS, "")] == ["site", "tool"]
        assert [r.name for r in f(self.REPOS, "ACME", "")] == ["site"]
        assert [r.name for r in f(self.REPOS, repo_picker.ALL_OWNERS, "web")] == ["site"]   # description
        assert f(self.REPOS, "me", "site") == []

    def test_picker_renders_and_selects(self, isolated_data_dir):
        picker = repo_picker.RepoPicker()
        picker._on_loaded((self.REPOS, core.owners_from_repos(self.REPOS, ["silent"])))
        assert picker.list.count() == 2
        picker.list.setCurrentRow(0)
        assert picker.selected_repo().full_name == "acme/site"
        picker.owner_combo.setCurrentIndex(picker.owner_combo.findData("me"))
        assert picker.list.count() == 1
        assert picker.owner_combo.findData("silent") >= 0   # organisation sans dépôt visible

    def test_picker_shows_error_message(self, isolated_data_dir):
        picker = repo_picker.RepoPicker()
        picker._on_failed("Token GitHub invalide")
        assert "invalide" in picker.status.text() and picker.btn_refresh.isEnabled()

    def test_github_dialog_merges_local_and_remote_owners(self, isolated_data_dir, tmp_path):
        p = tmp_path / "p"
        p.mkdir()
        core.register_project(p, str(tmp_path), name="p", github_repo="https://github.com/acme/p")
        dlg = github_dialog.GitHubDialog()
        assert dlg.table.rowCount() == 1 and dlg.table.item(0, 3).text() == "1"
        dlg._on_loaded((self.REPOS, core.owners_from_repos(self.REPOS)))
        logins = [dlg.table.item(i, 0).text() for i in range(dlg.table.rowCount())]
        assert logins == ["acme", "me"]
        assert dlg.table.item(0, 2).text() == "1"   # dépôts GitHub chez acme

    def test_github_dialog_classify_emits_signal(self, isolated_data_dir, tmp_path, messages):
        p = tmp_path / "p"
        p.mkdir()
        core.register_project(p, str(tmp_path), name="p", github_repo="https://github.com/acme/p")
        dlg = github_dialog.GitHubDialog()
        fired = []
        dlg.projects_changed.connect(lambda: fired.append(1))
        dlg._classify()
        assert fired and core.get_project(p)["category"] == "acme"


class TestGitDialogAsync:
    def _dialog(self):
        from ui_main import git_dialog
        return git_dialog.GitDialog("https://github.com/acme/api.git", "main")

    def _wait(self, dlg):
        dlg._worker.wait(5000)
        QApplication.processEvents()

    def test_resolve_token_prefers_typed_valid_token(self, monkeypatch):
        from ui_main import git_dialog
        monkeypatch.setattr(core.github_auth, "verify_github_token", lambda t: (t == "good", "refusé"))
        assert git_dialog.GitDialog._resolve_token("good", "", False) == ("good", "")
        assert git_dialog.GitDialog._resolve_token("bad", "clear", False) == ("", "❌ refusé")
        assert git_dialog.GitDialog._resolve_token("", "clear", False) == ("clear", "")
        assert git_dialog.GitDialog._resolve_token("", "", False) == ("", "")

    def test_verify_runs_in_background_and_updates_label(self, isolated_data_dir, monkeypatch):
        monkeypatch.setattr(core.git_ops, "verify_github_repo", lambda url, token="": (True, "✅ Repo accessible"))
        dlg = self._dialog()
        dlg.chk_private.setChecked(False)
        dlg._verify_repo()
        assert not dlg.btn_verify.isEnabled()          # pendant la vérification
        self._wait(dlg)
        assert dlg._repo_verified and "accessible" in dlg.lbl_verify_result.text()
        assert dlg.btn_verify.isEnabled()

    def test_validate_verifies_then_accepts_by_itself(self, isolated_data_dir, monkeypatch):
        monkeypatch.setattr(core.git_ops, "verify_github_repo", lambda url, token="": (True, "ok"))
        dlg = self._dialog()
        dlg.chk_private.setChecked(False)
        dlg._validate()
        self._wait(dlg)
        assert dlg.result() == QDialog.Accepted

    def test_validate_refuses_unreachable_repo(self, isolated_data_dir, monkeypatch, messages):
        monkeypatch.setattr(core.git_ops, "verify_github_repo", lambda url, token="": (False, "introuvable"))
        dlg = self._dialog()
        dlg.chk_private.setChecked(False)
        dlg._validate()
        self._wait(dlg)
        assert dlg.result() != QDialog.Accepted and messages["warning"]

    def test_branches_loaded_in_background(self, isolated_data_dir, monkeypatch):
        monkeypatch.setattr(core.git_ops, "list_github_branches", lambda url, token="": ["main", "dev"])
        dlg = self._dialog()
        dlg.chk_private.setChecked(False)
        dlg._load_remote_branches()
        self._wait(dlg)
        assert [dlg.branch_combo.itemText(i) for i in range(dlg.branch_combo.count())] == ["main", "dev"]

    def test_pick_repo_fills_url_and_branch(self, isolated_data_dir, monkeypatch):
        repo = TestRepoPickerAndGithubDialog.REPOS[0]

        class FakeChooser:
            def __init__(self, parent=None):
                pass

            def exec(self):
                return QDialog.Accepted

            def selected_repo(self):
                return repo

        from ui_main import git_dialog
        monkeypatch.setattr(git_dialog, "RepoChooserDialog", FakeChooser)
        dlg = self._dialog()
        dlg._pick_repo()
        assert dlg.url_edit.text() == "https://github.com/acme/site.git"
        assert dlg.chk_private.isChecked() and dlg.branch_combo.currentText() == "main"
