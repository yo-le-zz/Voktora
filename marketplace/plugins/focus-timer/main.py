"""Focus Timer 1.1 — Pomodoro dans la barre d'état : durées réglables, longue pause, passer, statistiques.

Montre : add_status_widget, options, add_menu_action avec raccourci, api.notify, data_path, show_markdown, une machine
à états pure (pomodoro.py) testée à part.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from . import pomodoro as pm


class TimerWidget(QWidget):
    def __init__(self, api, stats):
        super().__init__()
        self._api, self._stats = api, stats
        o = api.options
        self.clock = pm.Pomodoro(o.get("work"), o.get("short"), o.get("long"), o.get("cycles"))
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        self._label = QLabel()
        self._play = self._button("mdi:play", "Démarrer / pause (Ctrl+Alt+T)", self.toggle)
        self._skip = self._button("mdi:skip-next", "Passer à la phase suivante", self.skip)
        self._reset = self._button("mdi:restore", "Remettre la phase à zéro", self.reset)
        for w in (self._label, self._play, self._skip, self._reset):
            layout.addWidget(w)
        self.render()

    def _button(self, icon, tip, handler):
        b = QToolButton()
        b.setAutoRaise(True)
        b.setIcon(self._api.icon(icon))
        b.setToolTip(tip)
        b.clicked.connect(handler)
        return b

    def configure(self):
        o = self._api.options
        self.clock.configure(o.get("work"), o.get("short"), o.get("long"), o.get("cycles"))
        self.render()

    def render(self):
        c = self.clock
        extra = f" · {c.position}/{c.cycles}" if c.phase == pm.WORK else ""
        today = self._stats.today()["sessions"]
        self._label.setText(f"{pm.LABELS[c.phase]}  {pm.fmt(c.left)}{extra}  ·  aujourd'hui : {today}")
        self._play.setIcon(self._api.icon("mdi:pause" if c.running else "mdi:play"))

    def toggle(self):
        self._timer.start() if self.clock.toggle() else self._timer.stop()
        self.render()

    def reset(self):
        self.clock.reset()
        self._timer.stop()
        self.render()

    def skip(self):
        self.clock.skip()
        self.render()

    def _tick(self):
        finished = self.clock.tick()
        if finished:
            self.on_finished(finished)
        self.render()

    def on_finished(self, finished):
        if finished == pm.WORK:
            self._stats.add(self.clock.work)
        if not self._api.options.get("auto_start"):
            self.clock.running = False
            self._timer.stop()
        if self._api.options.get("notify"):
            self._api.notify("Pause bien méritée." if finished == pm.WORK else "Au travail !", 8000)


def on_load(api):
    o = api.options
    o.group("Durées (minutes)")
    o.add_int("work", "Travail", default=25, min=1, max=180)
    o.add_int("short", "Pause courte", default=5, min=1, max=60)
    o.add_int("long", "Longue pause", default=15, min=1, max=120)
    o.add_int("cycles", "Travaux avant la longue pause", default=4, min=1, max=12)
    o.group("Comportement")
    o.add_bool("auto_start", "Enchaîner automatiquement la phase suivante", default=False)
    o.add_bool("notify", "Notifier en fin de phase", default=True)
    holder = {}
    from .pomodoro import Stats
    stats = Stats(api.data_path("stats.json"))

    def factory(_ctx):
        holder["widget"] = TimerWidget(api, stats)
        return holder["widget"]

    def act(method):
        def go(*_):
            widget = holder.get("widget")
            if widget is not None:
                method(widget)
        return go

    o.on_change(lambda _k, _v: act(TimerWidget.configure)())
    api.add_status_widget(factory)
    api.add_menu_action("Plugins/Focus Timer", "Démarrer / pause", act(TimerWidget.toggle), shortcut="Ctrl+Alt+T", icon="mdi:timer-outline")
    api.add_menu_action("Plugins/Focus Timer", "Passer à la phase suivante", act(TimerWidget.skip), icon="mdi:skip-next")
    api.add_menu_action("Plugins/Focus Timer", "Statistiques (7 jours)", lambda *_: api.show_markdown("Focus", stats.to_markdown()),
                        icon="mdi:chart-bar")
