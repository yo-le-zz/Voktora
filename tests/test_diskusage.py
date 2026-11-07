"""Espace disque : classification intelligente (marqueurs), nettoyage sûr, seuil de double confirmation."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))

import core  # noqa: E402
import diskusage as du  # noqa: E402


def _fill(path: Path, size: int = 4096, name: str = "f.bin") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_bytes(b"x" * size)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    _fill(root, 100, "main.py")
    (root / "Cargo.toml").write_text("[package]\n")
    (root / "package.json").write_text("{}")
    _fill(root / "target" / "debug", 50_000)
    _fill(root / "node_modules" / "left-pad", 30_000)
    _fill(root / "src" / "__pycache__", 2_000)
    _fill(root / ".pytest_cache", 1_000)
    _fill(root / "build", 9_000)                      # build + package.json à côté → build
    _fill(root / ".git" / "objects", 7_000)
    return root


class TestClassification:
    def test_categories(self, project):
        usage = du.scan_project(project)
        found = {i.rel: i.category for i in usage.items}
        assert found["target"] == du.BUILD and found["node_modules"] == du.DEPS
        assert found["src/__pycache__"] == du.CACHE and found[".pytest_cache"] == du.CACHE
        assert found["build"] == du.BUILD
        assert usage.by_category[du.VCS] > 0 and usage.by_category[du.SOURCE] > 0
        assert usage.reclaimable == sum(usage.by_category[c] for c in du.REGENERABLE)

    def test_markers_prevent_false_positives(self, tmp_path):
        # « target », « build », « dist », « vendor » sans fichier de projet voisin = ce sont VOS dossiers
        root = tmp_path / "p"
        for name in ("target", "build", "dist", "vendor", "out", "env", "bin"):
            _fill(root / name, 5_000)
        assert du.scan_project(root).items == []

    def test_venv_needs_pyvenv_cfg(self, tmp_path):
        root = tmp_path / "p"
        _fill(root / "env", 5000)
        _fill(root / ".venv", 5000)
        (root / ".venv" / "pyvenv.cfg").write_text("home = /usr")
        assert [i.rel for i in du.scan_project(root).items] == [".venv"]

    def test_cachedir_tag_is_recognised(self, tmp_path):
        root = tmp_path / "p"
        _fill(root / "weird-cache", 5000)
        (root / "weird-cache" / "CACHEDIR.TAG").write_bytes(du.CACHEDIR_SIGNATURE + b"\n")
        item = du.scan_project(root).items[0]
        assert item.rel == "weird-cache" and item.category == du.CACHE

    def test_nuitka_build_dirs(self, tmp_path):
        root = tmp_path / "p"
        _fill(root / "main.build", 5000, "main.c")
        _fill(root / "main.dist", 5000)
        _fill(root / "notes.build", 5000, "readme.txt")      # même suffixe, mais pas Nuitka
        assert sorted(i.rel for i in du.scan_project(root).items) == ["main.build"]

    def test_nested_matches_are_counted_once(self, project):
        _fill(project / "node_modules" / "a" / "node_modules", 10_000)
        rels = [i.rel for i in du.scan_project(project).items]
        assert "node_modules/a/node_modules" not in rels

    def test_symlinks_not_followed(self, tmp_path):
        root = tmp_path / "p"
        outside = tmp_path / "outside"
        _fill(outside, 1_000_000)
        root.mkdir()
        (root / "link").symlink_to(outside, target_is_directory=True)
        assert du.scan_project(root).total < 100_000

    def test_scan_many_and_progress(self, project, tmp_path):
        seen = []
        out = du.scan_many([project, tmp_path / "missing"], on_progress=lambda d, t, n: seen.append((d, t)))
        assert out[0].total > 0 and out[1].error and seen[-1] == (2, 2)


class TestClean:
    def test_clean_default_keeps_deps_and_sources(self, project):
        freed, notes = du.clean_project(project)
        assert freed > 50_000 and not notes
        assert not (project / "target").exists() and not (project / ".pytest_cache").exists()
        assert (project / "node_modules").exists()                  # dépendances : opt-in
        assert (project / "main.py").exists() and (project / ".git").exists()

    def test_clean_with_deps(self, project):
        du.clean_project(project, (du.CACHE, du.BUILD, du.DEPS))
        assert not (project / "node_modules").exists() and (project / "Cargo.toml").exists()

    def test_git_tracked_directory_is_protected(self, project):
        if subprocess.run(["git", "--version"], capture_output=True, check=False).returncode != 0:
            pytest.skip("git absent")
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull}
        for cmd in (["init", "-q"], ["add", "-A", "-f", "build"]):
            subprocess.run(["git", "-C", str(project), *cmd], check=True, env=env, capture_output=True)
        usage = du.scan_project(project)
        build = next(i for i in usage.items if i.rel == "build")
        assert build.protected == "suivi par git"
        freed, notes = du.clean_project(project, (du.BUILD,), usage)
        assert (project / "build").exists() and any("conservé" in n for n in notes)

    def test_refuses_dangerous_items(self, project, tmp_path):
        bad = [du.Item("../outside", du.CACHE, "", 1, 1), du.Item("", du.CACHE, "", 1, 1),
               du.Item("src", du.SOURCE, "", 1, 1), du.Item(".git/objects", du.CACHE, "", 1, 1)]
        for item in bad:
            assert du.safe_to_delete(project, item), item
        link = project / "lnk"
        link.symlink_to(tmp_path, target_is_directory=True)
        assert du.safe_to_delete(project, du.Item("lnk", du.CACHE, "", 1, 1))

    def test_reset_all_and_cancel(self, project, tmp_path):
        other = tmp_path / "other"
        _fill(other / "__pycache__", 3000)
        usages = du.scan_many([project, other])
        freed, _ = du.reset_all(usages, cancel=lambda: False)
        assert freed > 0 and not (other / "__pycache__").exists()
        _fill(other / "__pycache__", 3000)
        usages = du.scan_many([other])
        assert du.reset_all(usages, cancel=lambda: True)[0] == 0 and (other / "__pycache__").exists()


class TestThreshold:
    def test_default_and_configured_threshold(self, isolated_data_dir):
        assert du.confirm_threshold_bytes() == 500 * 1024 * 1024
        assert not du.needs_double_confirmation(100 * 1024 * 1024)
        assert du.needs_double_confirmation(600 * 1024 * 1024)
        cfg = core.get_app_config()
        cfg["disk_reset_confirm_mb"] = 10
        core.set_app_config(cfg)
        assert du.needs_double_confirmation(11 * 1024 * 1024) and not du.needs_double_confirmation(5 * 1024 * 1024)
        cfg["disk_reset_confirm_mb"] = "n'importe quoi"
        core.set_app_config(cfg)
        assert du.confirm_threshold_bytes() == 500 * 1024 * 1024

    def test_human(self):
        assert du.human(0) == "0 o" and du.human(1536) == "1.5 Ko" and du.human(5 * 1024**3) == "5.0 Go"
