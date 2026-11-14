"""Focus Timer 1.1 : machine à états, statistiques, options, interface."""

from datetime import date

import pytest
from plugin_stub import StubApi, load_plugin, submodule


@pytest.fixture(scope="module")
def plg():
    return load_plugin("focus-timer"), submodule("focus-timer", "pomodoro")


def test_cycle_with_long_break(plg):
    _m, pm = plg
    c = pm.Pomodoro(work=1, short=1, long=2, cycles=2)
    c.toggle()
    phases = []
    for _ in range(60 * 1 + 60 * 1 + 60 * 1 + 120):
        f = c.tick()
        if f:
            phases.append(f)
    assert phases == [pm.WORK, pm.SHORT, pm.WORK, pm.LONG] and c.phase == pm.WORK and c.done == 2


def test_paused_does_not_tick_and_reset_skip(plg):
    _m, pm = plg
    c = pm.Pomodoro(work=2, short=1, long=3, cycles=2)
    assert c.tick() is None and c.left == 120
    c.toggle()
    c.tick(30)
    assert c.left == 90
    c.reset()
    assert c.left == 120 and not c.running
    assert c.skip() == pm.SHORT and c.done == 0 and c.left == 60          # sauter un travail ne le compte pas
    assert c.skip() == pm.WORK


def test_configure_updates_idle_timer_only(plg):
    _m, pm = plg
    c = pm.Pomodoro()
    c.configure(work=50)
    assert c.left == 3000
    c.toggle()
    c.tick(10)
    c.configure(work=10)
    assert c.left == 2990                                                  # en marche : la durée en cours ne bouge pas


def test_format_and_position(plg):
    _m, pm = plg
    assert pm.fmt(0) == "00:00" and pm.fmt(3599) == "59:59" and pm.fmt(-5) == "00:00"
    c = pm.Pomodoro(cycles=4)
    assert c.position == 1


def test_stats_persist_and_markdown(plg, tmp_path):
    _m, pm = plg
    s = pm.Stats(tmp_path / "s" / "stats.json")
    assert s.today() == {"sessions": 0, "minutes": 0}
    day = date(2026, 11, 13)
    s.add(25, day)
    s.add(25, day)
    s.add(50, date(2026, 11, 12))
    assert s.today(day) == {"sessions": 2, "minutes": 50}
    assert s.last_days(3, day) == [("2026-11-11", 0, 0), ("2026-11-12", 1, 50), ("2026-11-13", 2, 50)]
    md = s.to_markdown(3, day)
    assert "| 2026-11-13 | 2 | 50 |" in md and "3 session(s), 1 h 40 min" in md
    (tmp_path / "s" / "stats.json").write_text("pas du json")
    assert s.today(day)["sessions"] == 0                                    # fichier corrompu : repart de zéro


def test_widget_and_menu(plg, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    mod, pm = plg
    api = StubApi(tmp_path / "d")
    mod.on_load(api)
    assert api.options.get("work") == 25 and [m[1] for m in api.menu][0] == "Démarrer / pause"
    widget = api.status[0](None)
    assert "Travail  25:00 · 1/4" in widget._label.text()
    api.menu[0][2]()                                          # démarrer
    assert widget.clock.running and widget._timer.isActive()
    widget.clock.left = 1
    widget._tick()                                            # fin du travail
    assert widget._stats.today()["sessions"] == 1 and not widget.clock.running and api.notices
    assert widget.clock.phase == pm.SHORT
    api.options.set("short", 9)
    assert widget.clock.left == 9 * 60
    api.menu[2][2]()
    assert api.dialogs and "Focus" in api.dialogs[0][0]
