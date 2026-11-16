"""Sync 1.1.4 : Push config (paquet), chef/époque, pause/stop, panneau d'interface."""

import threading
import time

import pytest
from sync import configpack as cp
from sync import roles
from sync.control import PAUSED, RUNNING, STOPPED, PauseTimeout, StopRequested, SyncController


def test_group_state_roundtrip_and_epoch():
    a = roles.GroupState("directed", "A", 3, "A")
    assert roles.GroupState.from_dict(a.to_dict()) == a
    assert roles.GroupState.from_dict("n'importe quoi").mode == roles.EGALITARIAN
    newer = roles.GroupState("directed", "B", 4, "B")
    assert roles.resolve(a, newer).leader_id == "B"
    ok, _ = roles.fence(newer, 3)
    assert not ok


def test_follower_cannot_push_directly():
    state = roles.GroupState("directed", "A", 1, "A")
    assert roles.can_push_config(state, "A")[0] != "request"
    assert roles.can_push_config(state, "B")[0] == "request"
    assert roles.can_push_config(roles.GroupState(), "B")[0] != "request"


def test_controller_pause_resume_stop():
    c = SyncController(hold_seconds=0.2, poll=0.01)
    assert c.state == STOPPED
    c.start()
    assert c.state == RUNNING and c.pause() and c.state == PAUSED
    assert c.resume() and c.state == RUNNING
    token = c.begin_run()
    c.pause()
    with pytest.raises(PauseTimeout):
        c.checkpoint(token)
    c.resume()
    c.stop()
    with pytest.raises(StopRequested):
        c.checkpoint(token)
    c.end_run(token)
    assert c.state == STOPPED


def test_controller_pause_blocks_checkpoint_until_resume():
    c = SyncController(hold_seconds=5, poll=0.01)
    c.start()
    token = c.begin_run()
    c.pause()
    passed = threading.Event()
    threading.Thread(target=lambda: (c.checkpoint(token), passed.set()), daemon=True).start()
    time.sleep(0.1)
    assert not passed.is_set()
    c.resume()
    assert passed.wait(2)
    c.stop()


def test_config_pack_module_exposes_api():
    for name in ("build_pack", "verify_pack", "diff_packs", "apply_pack", "compute_rev"):
        assert callable(getattr(cp, name))
    with pytest.raises(cp.PackError):
        cp.verify_pack({"rev": "x"})


@pytest.fixture()
def _service(isolated_data_dir):
    from sync import appio
    appio.reset_service_for_tests()
    yield appio.get_service()
    appio.reset_service_for_tests()


def test_group_panel_builds_and_buttons_follow_state(_service):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from ui_dialogs.sync_group_panel import SyncGroupPanel
    panel = SyncGroupPanel(_service)
    panel.refresh(_service.snapshot())
    assert "Arrêtée" in panel.state.text() and not panel.stop_btn.isEnabled() and panel.start_btn.isEnabled()
    assert panel.mode.count() == 2


def test_service_public_api_for_pause_and_stop(_service):
    for name in ("pause", "resume", "stop", "push_config", "set_group_mode", "abdicate", "apply_received_config"):
        assert callable(getattr(_service, name))
    assert _service.pause() is False          # rien ne tourne : pas de pause possible
