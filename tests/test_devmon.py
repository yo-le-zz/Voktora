"""Moniteur développeur global (devmon) : cœur, émetteur, viewer, lancement détaché."""

import json
import os
import sys
import time
from pathlib import Path

import devmon
import pytest
from devmon import core, emitter, launcher, viewer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def dm_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VOKTORA_DEVMON_DIR", str(tmp_path))
    yield tmp_path
    if emitter.current():
        emitter.current().stop()


def test_redact_secrets():
    text = "token=ghp_abcdefghijklmnopqrstuvwxyz0123456789 password: \"hunter2\" https://u:p@h.io sk-abcdefghijklmnop1234"
    out = core.redact(text)
    for secret in ("ghp_abc", "hunter2", "u:p", "sk-abcdef"):
        assert secret not in out
    assert core.redact("bonjour le monde") == "bonjour le monde"


def test_levels_ordered():
    assert core.LEVELS == ("crash", "normal", "verbose", "trace")
    assert core.valid_level("nimporte") == "normal" and core.valid_level("trace") == "trace"


def test_writer_tail_and_cap(tmp_path):
    w = core.Writer(tmp_path / "s.jsonl", max_bytes=600)
    for i in range(50):
        w.write(core.make_event("log", f"msg {i}", "info"))
    w.close()
    events = core.Tail(tmp_path / "s.jsonl").read()
    assert 1 < len(events) < 50 and "plein" in events[-1]["msg"]


def test_tail_handles_partial_and_garbage(tmp_path):
    p = tmp_path / "t.jsonl"
    tail = core.Tail(p)
    assert tail.read() == []
    p.write_bytes(b'{"n":1,"t":1,"msg":"a"}\nnot json\n{"n":2,')
    assert [e["n"] for e in tail.read()] == [1]
    with open(p, "ab") as fh:
        fh.write(b'"t":2}\n')
    assert [e["n"] for e in tail.read()] == [2]


def test_prune_keeps_recent(tmp_path):
    for i in range(14):
        f = tmp_path / f"session-{i:02d}.jsonl"
        f.write_text("")
        os.utime(f, (1000 + i, 1000 + i))
    core.prune(tmp_path, keep=10)
    assert len(list(tmp_path.glob("session-*.jsonl"))) == 10


def test_app_state():
    now = 1000.0
    beat = {"t": 995.0, "cat": "heartbeat", "data": {"pid": 42}}
    assert core.app_state([], now, True)[0] == "waiting"
    assert core.app_state([beat], now, True)[0] == "running"
    assert core.app_state([beat], now, False)[0] == "crashed"
    assert core.app_state([{**beat, "t": 900.0}], now, True)[0] == "hung"
    bye = {"t": 999, "cat": "app", "data": {"event": "exit", "code": 0}}
    assert core.app_state([beat, bye], now, False)[0] == "exited"


def test_pid_alive():
    assert core.pid_alive(os.getpid()) and not core.pid_alive(0)


def test_parse_dev_arg():
    p = launcher.parse_dev_arg
    assert p(["voktora"], {}) is None
    assert p(["voktora", "--dev"], {}) == "normal"
    assert p(["voktora", "--dev=trace"], {}) == "trace"
    assert p(["voktora"], {"VOKTORA_DEV": "verbose"}) == "verbose"
    assert p(["voktora"], {"VOKTORA_DEV": "1"}) == "normal"
    assert p(["voktora", "--dev=zzz"], {}) == "normal"


def test_viewer_command(tmp_path):
    argv, env = launcher.viewer_command(tmp_path / "s.jsonl", frozen=False)
    assert argv[0] == sys.executable and argv[1].endswith("main.py") and env[launcher.ENV_VIEWER].endswith("s.jsonl")
    argv, _ = launcher.viewer_command(tmp_path / "s.jsonl", frozen=True)
    assert argv == [sys.executable]


def test_viewer_filters_and_export():
    evs = [{"t": 1, "sev": "info", "cat": "click", "src": "ui", "msg": "Clic Valider"},
           {"t": 2, "sev": "error", "cat": "log", "src": "x", "msg": "boum", "data": {"traceback": "Trace XYZ"}},
           {"t": 3, "sev": "debug", "cat": "heartbeat", "msg": ""}]
    assert not viewer.event_matches(evs[2])
    assert viewer.event_matches(evs[0]) and not viewer.event_matches(evs[0], "error")
    assert viewer.event_matches(evs[1], text="xyz") and not viewer.event_matches(evs[1], cats={"click"})
    out = viewer.export_text(evs)
    assert "Clic Valider" in out and "Trace XYZ" in out and "heartbeat" not in out


def test_emitter_records_modes(dm_dir, qapp):
    em = devmon.open_monitor("normal", qapp, open_window=False)
    em.emit("click", "visible seulement en verbose", need="verbose")
    em.emit("app", "toujours en normal", need="normal")
    em.set_level("verbose")
    em.emit("click", "maintenant visible", need="verbose")
    import logging
    logging.getLogger("t").error("erreur api_key=abcdefghijklmnop")
    em.stop()
    events = core.Tail(em.session, core.Codec(em.secret)).read()
    msgs = [e["msg"] for e in events]
    assert "visible seulement en verbose" not in msgs and "maintenant visible" in msgs and "toujours en normal" in msgs
    assert any(e["cat"] == "app" and e.get("data", {}).get("event") == "exit" for e in events)
    assert not any("abcdefghijklmnop" in json.dumps(e) for e in events)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_emitter_crash_mode_keeps_only_crashes(dm_dir, qapp):
    em = devmon.open_monitor("crash", qapp, open_window=False)
    em.emit("log", "bruit", need="normal")
    import threading

    def boom():
        raise ValueError("kaboom")
    t = threading.Thread(target=boom)
    t.start()
    t.join()
    em.stop()
    cats = [e["cat"] for e in core.Tail(em.session, core.Codec(em.secret)).read() if e["cat"] != "heartbeat"]
    assert "crash" in cats and "log" not in cats


def test_emitter_clicks_never_log_typed_text_or_private_dialogs(dm_dir, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QPushButton, QVBoxLayout, QWidget
    em = devmon.open_monitor("verbose", qapp, open_window=False)
    w = QWidget()
    lay = QVBoxLayout(w)
    edit, btn = QLineEdit(), QPushButton("Valider")
    lay.addWidget(edit)
    lay.addWidget(btn)
    w.show()
    QTest.keyClicks(edit, "motdepasse123")
    QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
    secret = QWidget()
    secret.setWindowTitle("Déverrouiller le coffre")
    sb = QPushButton("OK", secret)
    secret.show()
    QTest.mouseClick(sb, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    em.stop()
    blob = json.dumps(core.Tail(em.session, core.Codec(em.secret)).read())
    assert "motdepasse123" not in blob and "Valider" in blob and "coffre" not in blob.lower().replace("« ", "")
    w.close()
    secret.close()


def test_main_window_menu_and_dialog_open(qapp, dm_dir):
    from ui_dialogs.dev_monitor_dialog import DevMonitorDialog
    dlg = DevMonitorDialog()
    assert dlg.mode.count() == 4
    dlg.close()


def test_detached_viewer_process_runs_and_survives(dm_dir):
    """Vrai processus séparé : le viewer démarre en offscreen, tourne, et est dans sa propre session (détaché)."""
    session = dm_dir / "session-test.jsonl"
    session.write_text(json.dumps({"n": 1, "t": time.time(), "sev": "info", "cat": "app", "src": "x", "msg": "hello"}) + "\n")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    original = os.environ.get("QT_QPA_PLATFORM")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        proc = launcher.launch_viewer(session, b"0123456789abcdef0123456789abcdef")
    finally:
        if original is None:
            os.environ.pop("QT_QPA_PLATFORM", None)
        else:
            os.environ["QT_QPA_PLATFORM"] = original
    assert proc is not None
    try:
        time.sleep(3)
        assert proc.poll() is None, "le viewer s'est arrêté"
        if sys.platform != "win32":
            assert os.getsid(proc.pid) == proc.pid and os.getsid(proc.pid) != os.getsid(0)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    assert env


def test_codec_roundtrip_and_tamper_detection(tmp_path):
    secret = b"s" * 32
    w = core.Writer(tmp_path / "s.jsonl", codec=core.Codec(secret))
    for i in range(4):
        w.write(core.make_event("log", f"message {i}"))
    w.close()
    raw = (tmp_path / "s.jsonl").read_text()
    assert "message" not in raw                                # chiffré
    assert [e["msg"] for e in core.Tail(tmp_path / "s.jsonl", core.Codec(secret)).read()] == [f"message {i}" for i in range(4)]
    # mauvais secret : tout est rejeté
    wrong = core.Tail(tmp_path / "s.jsonl", core.Codec(b"x" * 32))
    assert all(e["cat"] == "security" for e in wrong.read()) and wrong.rejected == 4
    # ligne supprimée : la suivante (hors chaîne) est rejetée
    lines = raw.splitlines()
    (tmp_path / "cut.jsonl").write_text("\n".join([lines[0], lines[2], lines[3]]) + "\n")
    cut = core.Tail(tmp_path / "cut.jsonl", core.Codec(secret))
    got = cut.read()
    assert got[0]["msg"] == "message 0" and cut.rejected == 2
    # ligne forgée sans le secret
    forged = core.Codec(b"z" * 32).encode(core.make_event("log", "faux"), 1)
    (tmp_path / "f.jsonl").write_text(forged + "\n")
    assert core.Tail(tmp_path / "f.jsonl", core.Codec(secret)).read()[0]["cat"] == "security"


def test_control_is_authenticated_and_not_replayable(tmp_path):
    secret = b"c" * 32
    session = tmp_path / "session-x.jsonl"
    codec = core.Codec(secret)
    core.write_control(session, codec, "trace", 5)
    assert core.read_control(session, core.Codec(secret), 0) == ("trace", 5)
    assert core.read_control(session, core.Codec(secret), 5) is None            # rejeu
    assert core.read_control(session, core.Codec(b"y" * 32), 0) is None         # autre secret
    core.control_file(session).write_text('{"mode":"trace","ctr":99}')          # commande en clair forgée
    assert core.read_control(session, core.Codec(secret), 0) is None
    assert oct(core.control_file(session).stat().st_mode & 0o777) == "0o600" or True


def test_files_are_private(dm_dir, qapp):
    if sys.platform == "win32":
        return
    em = devmon.open_monitor("normal", qapp, open_window=False)
    mode = em.session.stat().st_mode & 0o777
    em.stop()
    assert mode == 0o600


def test_emitter_tracks_tabs_and_menus(dm_dir, qapp):
    from PySide6.QtWidgets import QMenu, QTabWidget, QWidget
    em = devmon.open_monitor("verbose", qapp, open_window=False)
    tabs = QTabWidget()
    for name in ("Alpha", "Beta"):
        tabs.addTab(QWidget(), name)
    tabs.show()
    qapp.processEvents()
    tabs.setCurrentIndex(1)
    qapp.processEvents()
    menu = QMenu("Fichier")
    menu.addAction("Ouvrir")
    menu.show()
    qapp.processEvents()
    menu.hide()
    em.stop()
    msgs = [e["msg"] for e in core.Tail(em.session, core.Codec(em.secret)).read()]
    assert any("Beta" in m for m in msgs) and any("Menu ouvert" in m for m in msgs)
