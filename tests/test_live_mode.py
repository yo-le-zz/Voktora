"""Mode live (1.1.5) : dossier éphémère, garde-fous de suppression, scripts d'installation."""

import os
import subprocess
import sys
from pathlib import Path

import live
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def live_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(live.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    d = tmp_path / "voktora-live-abcd1234"
    d.mkdir()
    (d / live.MARKER).touch()
    monkeypatch.setenv(live.ENV, str(d))
    return d


def test_inactive_without_env(monkeypatch):
    monkeypatch.delenv(live.ENV, raising=False)
    assert not live.active() and live.cleanup() is False


def test_active_and_environment(live_dir, monkeypatch):
    for k in ("VOKTORA_DATA_DIR", "VOKTORA_NO_NATIVE"):
        monkeypatch.delenv(k, raising=False)
    assert live.active()
    live.prepare_environment()
    assert os.environ["VOKTORA_DATA_DIR"] == str(live_dir / "data") and (live_dir / "projects").is_dir()
    monkeypatch.delenv("VOKTORA_DATA_DIR")


def test_cleanup_removes_everything_but_marker(live_dir):
    (live_dir / "data").mkdir()
    (live_dir / "data" / "config.json").write_text("{}")
    (live_dir / "projects").mkdir()
    (live_dir / "projects" / "p").mkdir()
    (live_dir / "x.txt").write_text("x")
    assert live.cleanup() is True
    assert sorted(p.name for p in live_dir.iterdir()) == [live.MARKER] and live.cleanup() is False


@pytest.mark.parametrize("name", ["voktora-live-", "voktora-live-../x", "autre", "voktora-live-abc", "voktora-live-ab cd1234"])
def test_refuses_bad_names(tmp_path, monkeypatch, name):
    monkeypatch.setattr(live.tempfile, "gettempdir", lambda: str(tmp_path))
    d = tmp_path / name.replace("/", "_")
    d.mkdir()
    (d / live.MARKER).touch()
    monkeypatch.setenv(live.ENV, str(d))
    assert not live.active()


def test_refuses_without_marker_symlink_or_wrong_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(live.tempfile, "gettempdir", lambda: str(tmp_path))
    nomarker = tmp_path / "voktora-live-nomark1"
    nomarker.mkdir()
    monkeypatch.setenv(live.ENV, str(nomarker))
    assert not live.active()
    real = tmp_path / "voktora-live-real1234"
    real.mkdir()
    (real / live.MARKER).touch()
    link = tmp_path / "voktora-live-link1234"
    link.symlink_to(real)
    monkeypatch.setenv(live.ENV, str(link))
    assert not live.active()
    elsewhere = tmp_path / "sub" / "voktora-live-away1234"
    elsewhere.mkdir(parents=True)
    (elsewhere / live.MARKER).touch()
    monkeypatch.setenv(live.ENV, str(elsewhere))
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert not live.active()


def test_sweep_stale_only_dead_sessions(tmp_path):
    dead = tmp_path / "voktora-live-dead1234"
    dead.mkdir()
    (dead / live.MARKER).touch()
    (dead / ".pid").write_text("999999999")
    alive = tmp_path / "voktora-live-alive123"
    alive.mkdir()
    (alive / live.MARKER).touch()
    (alive / ".pid").write_text(str(os.getpid()))
    foreign = tmp_path / "voktora-live-foreign1"          # sans marqueur : jamais touché
    foreign.mkdir()
    assert live.sweep_stale(tmp_path) == ["voktora-live-dead1234"]
    assert alive.exists() and foreign.exists() and not dead.exists()


def test_data_dir_override(tmp_path):
    code = "import sys;sys.path.insert(0,'voktora');import core;print(core.get_data_dir())"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env={**os.environ, "VOKTORA_DATA_DIR": str(tmp_path / "d")},
                         capture_output=True, text=True, timeout=30, check=True)
    assert out.stdout.strip() == str(tmp_path / "d")


def test_scripts_are_valid_and_in_sync():
    sh = ROOT / "Installers" / "live" / "install-live.sh"
    assert subprocess.run(["sh", "-n", str(sh)], check=False).returncode == 0
    for name in ("install-live.sh", "install-live.ps1"):
        assert (ROOT / "Installers" / "live" / name).read_text() == (ROOT / "WebSite" / name).read_text(), f"{name} : copie du site désynchronisée"
    text = sh.read_text()
    assert "trap cleanup EXIT" in text and ".voktora-live" in text and "--strip-components=1" in text
    assert "$HOME" not in text and "~/" not in text           # le script n'écrit jamais dans le HOME


def test_live_end_to_end_cleanup_in_real_process(tmp_path):
    """Processus réel : prepare_environment + données écrites + cleanup() à la sortie (atexit) → dossier vidé."""
    d = tmp_path / "voktora-live-e2e12345"
    d.mkdir()
    (d / live.MARKER).touch()
    code = ("import sys,os;sys.path.insert(0,'voktora');import live;live.prepare_environment();live.main_cleanup_on_exit();"
            "open(os.path.join(os.environ['VOKTORA_DATA_DIR'],'secret.txt'),'w').write('x')")
    env = {**os.environ, live.ENV: str(d), "TMPDIR": str(tmp_path), "XDG_RUNTIME_DIR": str(tmp_path)}
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True, timeout=30)
    assert sorted(p.name for p in d.iterdir()) == [live.MARKER]
