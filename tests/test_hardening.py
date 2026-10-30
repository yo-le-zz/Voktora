"""Durcissements 1.0.4 : désinstallation, permissions, URL, chiffrement de projet, workflow CI."""

import os
import re
import stat
import subprocess
from pathlib import Path

import core
import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestUninstallScript:
    def test_dev_checkout_never_deletes_the_sources(self, isolated_data_dir):
        targets = core.diagnostics._removal_targets()
        assert core.get_app_dir().resolve() not in targets

    def test_script_is_private_with_random_name(self, isolated_data_dir):
        path = core.create_uninstall_script()
        try:
            assert path.parent == Path(os.environ.get("TMPDIR", "/tmp")) or path.exists()
            if os.name == "posix":
                assert stat.S_IMODE(path.stat().st_mode) == 0o700
            assert path.name != "voktora_uninstall.sh"
        finally:
            path.unlink(missing_ok=True)

    def test_paths_are_shell_quoted(self, isolated_data_dir, monkeypatch, tmp_path):
        evil = tmp_path / 'a"; touch PWNED; "b'
        monkeypatch.setattr(core.diagnostics, "_removal_targets", lambda: [evil])
        monkeypatch.setattr(core.constants, "IS_WINDOWS", False)
        path = core.create_uninstall_script()
        try:
            text = path.read_text()
            assert "rm -rf -- '" in text
            assert subprocess.run(["bash", "-n", str(path)], check=False).returncode == 0
        finally:
            path.unlink(missing_ok=True)

    @pytest.mark.parametrize("bad", ["/", str(Path.home())])
    def test_dangerous_targets_are_refused(self, monkeypatch, bad):
        monkeypatch.setattr(core.paths, "get_app_dir", lambda: Path(bad))
        monkeypatch.setattr(core.paths, "is_frozen", lambda: True)
        with pytest.raises(RuntimeError):
            core.diagnostics._removal_targets()


@pytest.mark.skipif(os.name != "posix", reason="permissions POSIX")
def test_config_is_never_world_readable(isolated_data_dir):
    core.config_store._save_config(core.config_store._load_config())
    assert stat.S_IMODE(core.get_config_path().stat().st_mode) == 0o600


class TestOpenUrl:
    @pytest.mark.parametrize("url", ["file:///etc/passwd", "ms-msdt:/id", "javascript:alert(1)", ""])
    def test_non_http_schemes_are_refused(self, url):
        with pytest.raises(ValueError):
            core.open_url_in_browser(url)

    def test_https_is_opened(self, monkeypatch):
        import webbrowser
        opened = []
        monkeypatch.setattr(webbrowser, "open", opened.append)
        core.open_url_in_browser("https://github.com/yo-le-zz")
        assert opened == ["https://github.com/yo-le-zz"]


class TestProjectEncryptionWorker:
    @pytest.fixture
    def worker_cls(self):
        from ui_dialogs.encrypt_dialog import EncryptWorker
        return EncryptWorker

    def _project(self, tmp_path):
        root = tmp_path / "p"
        (root / "sub").mkdir(parents=True)
        (root / "a.txt").write_text("alpha")
        (root / "sub" / "b.bin").write_bytes(os.urandom(3000))
        return root

    def _run(self, worker):
        results = []
        worker.finished.connect(lambda ok, msg: results.append((ok, msg)))
        worker.run()
        return results[0]

    def test_encrypt_then_decrypt_round_trip(self, tmp_path, worker_cls):
        root = self._project(tmp_path)
        original = (root / "sub" / "b.bin").read_bytes()
        ok, _ = self._run(worker_cls(root, "mot-de-passe-solide", "encrypt"))
        assert ok and not (root / "a.txt").exists() and (root / "a.txt.vkenc").exists()
        assert b"alpha" not in (root / "a.txt.vkenc").read_bytes()
        ok, _ = self._run(worker_cls(root, "mot-de-passe-solide", "decrypt"))
        assert ok and (root / "a.txt").read_text() == "alpha" and (root / "sub" / "b.bin").read_bytes() == original
        assert not (root / ".voktora_encrypted").exists()

    def test_wrong_password_destroys_nothing(self, tmp_path, worker_cls):
        root = self._project(tmp_path)
        self._run(worker_cls(root, "mot-de-passe-solide", "encrypt"))
        ok, msg = self._run(worker_cls(root, "mauvais-mot-de-passe", "decrypt"))
        assert not ok and "incorrect" in msg
        assert (root / "a.txt.vkenc").exists() and not (root / "a.txt").exists()
        assert (root / ".voktora_encrypted").exists()
        ok, _ = self._run(worker_cls(root, "mot-de-passe-solide", "decrypt"))
        assert ok and (root / "a.txt").read_text() == "alpha"

    def test_cancel_keeps_originals(self, tmp_path, worker_cls):
        root = self._project(tmp_path)
        worker = worker_cls(root, "mot-de-passe-solide", "encrypt")
        worker.isInterruptionRequested = lambda: True
        ok, msg = self._run(worker)
        assert not ok and "annulée" in msg and (root / "a.txt").exists()

    def test_legacy_menc_projects_can_still_be_decrypted(self, tmp_path, worker_cls):
        import hashlib
        root = tmp_path / "old"
        root.mkdir()
        key = hashlib.sha512(b"ancien-mdp").digest()
        (root / "n.txt.menc").write_bytes(bytes(b ^ key[i % 64] for i, b in enumerate(b"vieux contenu")))
        (root / ".voktora_encrypted").write_text("x")
        ok, msg = self._run(worker_cls(root, "ancien-mdp", "decrypt"))
        assert ok and (root / "n.txt").read_text() == "vieux contenu" and "ancien format" in msg


class TestWorkflow:
    wf = (ROOT / ".github" / "workflows" / "build-release.yml").read_text(encoding="utf-8")

    def test_untrusted_context_is_never_interpolated_in_a_script(self):
        """Aucun bloc `run:` ne doit contenir d'expression `${{ github.event.* }}` (injection de commande)."""
        lines, in_run, run_indent = self.wf.splitlines(), False, 0
        offenders = []
        for line in lines:
            indent = len(line) - len(line.lstrip())
            if in_run and line.strip() and indent <= run_indent:
                in_run = False
            if line.strip().startswith("run:"):
                in_run, run_indent = True, indent
                body = line.split("run:", 1)[1]
                if "github.event" in body:
                    offenders.append(line)
                continue
            if in_run and "github.event" in line:
                offenders.append(line)
        assert offenders == []

    def test_version_job_validates_title_with_a_strict_regex(self):
        assert "PR_TITLE: ${{ github.event.pull_request.title }}" in self.wf
        assert "[0-9]+\\.[0-9]+\\.[0-9]+" in self.wf

    def test_rpm_is_built_and_released(self):
        assert "build_rpm.sh" in self.wf and "name: linux-rpm" in self.wf and "linux-rpm/voktora-*.rpm" in self.wf
        assert self.wf.index("build_deb.sh") < self.wf.index("build_rpm.sh")   # compilation partagée

    def test_default_permissions_are_read_only(self):
        assert re.search(r"^permissions:\n  contents: read", self.wf, re.MULTILINE)


class TestPackagingScripts:
    @pytest.mark.parametrize("script", ["Installers/linux_common.sh", "Installers/DEB installer/build_deb.sh",
                                        "Installers/RPM installer/build_rpm.sh"])
    def test_shell_syntax(self, script):
        assert subprocess.run(["bash", "-n", str(ROOT / script)], check=False).returncode == 0

    def test_spec_is_consistent_with_staged_tree(self):
        spec = (ROOT / "Installers" / "RPM installer" / "voktora.spec").read_text(encoding="utf-8")
        common = (ROOT / "Installers" / "linux_common.sh").read_text(encoding="utf-8")
        for installed in ("/usr/share/applications/voktora.desktop", "/usr/bin/voktora",
                          "/usr/share/metainfo/io.github.yo_le_zz.Voktora.metainfo.xml",
                          "/usr/share/icons/hicolor/256x256/apps/voktora.png"):
            assert installed in spec
            assert installed.split("/usr/")[-1].split("/")[-1] in common
        assert "<n>" not in common and "<name>Voktora</name>" in common
