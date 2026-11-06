"""Focus Timer — Pomodoro dans la barre d'état.

Montre : add_status_widget, add_menu_action avec raccourci, api.notify, hooks (on_quit).
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

WORK, BREAK = 25 * 60, 5 * 60


class TimerWidget(QWidget):
    def __init__(self, api):
        super().__init__()
        self._api = api
        self._left = WORK
        self._working = True
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 0)
        self._label = QLabel()
        self._button = QToolButton()
        self._button.setAutoRaise(True)
        self._button.setIcon(api.icon("mdi:play"))
        self._button.clicked.connect(self.toggle)
        layout.addWidget(self._label)
        layout.addWidget(self._button)
        self._render()

    def _render(self):
        minutes, seconds = divmod(self._left, 60)
        self._label.setText(f"{'Travail' if self._working else 'Pause'}  {minutes:02d}:{seconds:02d}")

    def toggle(self):
        running = self._timer.isActive()
        self._timer.stop() if running else self._timer.start()
        self._button.setIcon(self._api.icon("mdi:play" if running else "mdi:pause"))

    def _tick(self):
        self._left -= 1
        if self._left <= 0:
            self._working = not self._working
            self._left = WORK if self._working else BREAK
            self._api.notify("Temps de travail !" if self._working else "Pause bien méritée.", 8000)
        self._render()


def on_load(api):
    holder = {}

    def factory(_ctx):
        holder["widget"] = TimerWidget(api)
        return holder["widget"]

    api.add_status_widget(factory)
    api.add_menu_action("Plugins/Focus Timer", "Démarrer / pause", lambda: holder["widget"].toggle(),
                        shortcut="Ctrl+Alt+T", icon="mdi:timer-outline")
