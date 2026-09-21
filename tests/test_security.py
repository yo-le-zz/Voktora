"""Régressions de sécurité : injection via un nom de projet, permissions de config, secrets d'export."""

import os
import stat
import subprocess
import zipfile
from pathlib import Path

import core
import pytest
from core import system

EVIL_NAMES = ["a'; touch pwned; '", "$(touch pwned)", "`touch pwned`", "x & calc", "x && rm -rf ~", 'x"; echo hi; "']


class TestNoShellInterpolation:
    @pytest.fixture(autouse=True)
    def _posix(self, monkeypatch):
        monkeypatch.setattr(core.constants, "IS_WINDOWS", False)
        monkeypatch.setattr(core.constants, "IS_LINUX", True)

    @pytest.mark.parametrize("name", EVIL_NAMES)
    def test_app_command_keeps_path_as_a_single_argument(self, name):
        path = Path("/projects") / name
        argv = system.build_app_command("code --reuse-window {path}", path)
        assert argv == ["code", "--reuse-window", str(path)]

    def test_app_command_without_placeholder_appends_path(self):
        assert system.build_app_command("code", Path("/p/x y")) == ["code", "/p/x y"]

    def test_quoted_template_is_respected(self):
        assert system.build_app_command('"/opt/My App/run" {path}', Path("/p")) == ["/opt/My App/run", "/p"]

    @pytest.mark.parametrize("name", EVIL_NAMES)
    def test_terminal_never_puts_the_path_in_a_shell_string(self, name, monkeypatch):
        calls = []
        monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: calls.append((cmd, kw)))
        path = Path("/projects") / name
        system.open_terminal(path)
        cmd, kw = calls[0]
        assert isinstance(cmd, list)                      # jamais une chaîne interprétée par un shell
        assert not kw.get("shell")
        assert "-c" not in cmd and "-e" not in cmd          # pas de commande shell « cd … && … »
        assert not any(arg.startswith("cd ") for arg in cmd)

    def test_terminal_falls_back_to_next_emulator_with_cwd(self, monkeypatch):
        calls = []

        def popen(cmd, cwd=None, **kw):
            calls.append((cmd, cwd))
            if cmd[0] in ("gnome-terminal", "konsole"):
                raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(subprocess, "Popen", popen)
        system.open_terminal(Path("/p/it's"))
        assert calls[-1] == (["xterm"], "/p/it's")


@pytest.mark.skipif(os.name != "posix", reason="permissions POSIX")
def test_config_file_is_private(isolated_data_dir):
    core._save_config(core._load_config())
    mode = stat.S_IMODE(core.get_config_path().stat().st_mode)
    assert mode == 0o600


class TestSecretsNeverLeaveTheMachine:
    def test_bundle_has_no_project_tokens(self, isolated_data_dir, tmp_path):
        import mc
        p = tmp_path / "p"
        p.mkdir()
        core.register_project(p, str(tmp_path), name="p", github_token="ghp_PROJECT", github_token_protected=False)
        core.save_github_account(token="ghp_ACCOUNT", user_info={"login": "octocat"})
        dest = tmp_path / "out.mpack"
        assert mc.export_bundle(dest).success
        with zipfile.ZipFile(dest) as zf:
            blob = b"".join(zf.read(n) for n in zf.namelist())
        assert b"ghp_PROJECT" not in blob and b"ghp_ACCOUNT" not in blob

    def test_snapshot_strips_git_credentials(self, isolated_data_dir, tmp_path):
        import snapshots
        proj = tmp_path / "proj"
        (proj / ".git").mkdir(parents=True)
        (proj / ".git" / "config").write_text('[remote "origin"]\n\turl = https://u:ghp_LEAK@github.com/o/r.git\n')
        (proj / "a.txt").write_text("x")
        snap = snapshots.create(proj, "test")
        with zipfile.ZipFile(snap) as zf:
            data = b"".join(zf.read(n) for n in zf.namelist() if n.endswith(".git/config"))
        assert data and b"ghp_LEAK" not in data
