"""LOC Counter (Rust) : tests unitaires Rust (cargo test) puis compilation et chargement par Voktora, appel du menu."""

import shutil
import subprocess
import time
from pathlib import Path

import plugins
import pytest
from plugins import rust_host
from PySide6.QtTest import QTest
from test_plugins_ui import window  # noqa: F401 — fixture partagée

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "marketplace" / "plugins" / "loc-counter-rs"
pytestmark = pytest.mark.skipif(rust_host.cargo_path() is None or rust_host.sdk_dir() is None, reason="cargo ou SDK Rust absent")


def test_cargo_unit_tests(tmp_path):
    shutil.copytree(PLUGIN, tmp_path / "loc-counter-rs")
    shutil.copytree(rust_host.sdk_dir(), tmp_path / "voktora-sdk")
    out = subprocess.run([rust_host.cargo_path(), "test", "--quiet"], cwd=tmp_path / "loc-counter-rs", capture_output=True,
                         text=True, timeout=600, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "5 passed" in out.stdout


def _texts(menu):
    out = []
    for action in menu.actions():
        out.append(action.text())
        if action.menu() is not None:
            out += _texts(action.menu())
    return out


def test_plugin_builds_loads_and_counts(window, tmp_path):  # noqa: F811
    shutil.copytree(PLUGIN, plugins.plugins_dir() / "loc-counter-rs", ignore=shutil.ignore_patterns("target"))
    project = tmp_path / "demo"
    (project / "src").mkdir(parents=True)
    (project / "src" / "a.py").write_text("# c\nx = 1\n")
    try:
        plugins.load_all()
        info = plugins.find("loc-counter-rs")
        deadline = time.time() + 900
        while time.time() < deadline and (info.pending_libs or not info.loaded) and not (info.error and not info.pending_libs):
            QTest.qWait(500)             # la fin de la compilation est signalée au fil principal : il faut traiter les événements
        assert info.loaded, info.error
        assert any("LOC Counter prêt" in line for line in info.logs)
        assert "Compter les lignes de code" in _texts(window.menuBar())
    finally:
        plugins.set_enabled("loc-counter-rs", False)
        shutil.rmtree(plugins.plugins_dir() / "loc-counter-rs", ignore_errors=True)
        plugins.load_all()
