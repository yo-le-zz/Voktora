"""Le journal global voit les commandes, le réseau, la console et les panneaux (1.1.5)."""

import subprocess
import sys
import time

import devmon
import pytest
from devmon import core, emitter


@pytest.fixture()
def em(tmp_path, monkeypatch):
    monkeypatch.setenv("VOKTORA_DEVMON_DIR", str(tmp_path))
    e = emitter.Emitter("trace", session=tmp_path / "s.jsonl", secret=b"k" * 32)
    emitter._current = e
    e.start()
    yield e
    e.stop()
    emitter._current = None


def test_note_noop_without_monitor():
    emitter._current = None
    devmon.note("rien")        # ne lève pas


def test_activity_logged(em):
    em._install_activity()        # pytest remplace sys.stdout après la fixture : on réinstalle le relais dans le corps du test
    subprocess.run([sys.executable, "-c", "pass"], check=False)
    print("bonjour console")
    sys.stderr.write("avertissement console\n")
    devmon.note("<b>ligne</b> du panneau", src="project")
    time.sleep(0.2)
    got = core.Tail(em.session, core.Codec(b"k" * 32)).read()
    cats = {(e["cat"], e["src"]) for e in got}
    assert ("process", "subprocess") in cats
    assert ("console", "stdout") in cats and ("console", "stderr") in cats
    assert any(e["msg"] == "ligne du panneau" for e in got)
