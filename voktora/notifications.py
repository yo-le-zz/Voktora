"""
Voktora — notifications (1.1.4) : notifications de bureau (Linux : notify-send ; sinon icône de zone de notification) et historique.
Réglages (config « notifications ») : enabled, kinds (sync, update, plugin, task, crash), quiet_start/quiet_end (heures « ne pas déranger »).
Aucun contenu sensible : on ne notifie que des messages courts préparés par Voktora.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass

import core

KINDS = {"sync": "Synchronisation", "update": "Mises à jour", "plugin": "Erreurs de plugins", "task": "Tâches longues terminées",
         "crash": "Plantages"}
DEFAULTS = {"enabled": True, "kinds": list(KINDS), "quiet_start": "", "quiet_end": ""}
HISTORY: deque = deque(maxlen=200)
_last: dict[str, float] = {}
_sender = None          # injectable (tests) ; sinon notify-send / tray


@dataclass
class Note:
    when: float
    kind: str
    title: str
    body: str
    shown: bool


def settings() -> dict:
    cfg = core.get_app_config().get("notifications")
    return {**DEFAULTS, **(cfg if isinstance(cfg, dict) else {})}


def save_settings(values: dict) -> None:
    cfg = core.get_app_config()
    cfg["notifications"] = {**DEFAULTS, **values}
    core.set_app_config(cfg)


def _minutes(text: str) -> int | None:
    try:
        h, m = text.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def in_quiet_hours(now: time.struct_time | None = None, start: str = "", end: str = "") -> bool:
    a, b = _minutes(start), _minutes(end)
    if a is None or b is None or a == b:
        return False
    now = now or time.localtime()
    cur = now.tm_hour * 60 + now.tm_min
    return a <= cur < b if a < b else (cur >= a or cur < b)


def notify(kind: str, title: str, body: str = "", dedupe_seconds: float = 30.0) -> bool:
    """Affiche (si autorisé) et enregistre dans l'historique. Renvoie True si une notification de bureau a été émise."""
    s = settings()
    key = f"{kind}|{title}|{body}"
    now = time.time()
    if now - _last.get(key, 0) < dedupe_seconds:
        return False                                           # même message répété : une seule fois
    _last[key] = now
    allowed = bool(s["enabled"]) and kind in s["kinds"] and not in_quiet_hours(None, s["quiet_start"], s["quiet_end"])
    shown = False
    if allowed:
        shown = _send(title[:80], body[:300])
    HISTORY.append(Note(now, kind, title, body, shown))
    return shown


def _send(title: str, body: str) -> bool:
    if _sender is not None:
        return bool(_sender(title, body))
    exe = shutil.which("notify-send")
    if exe:
        try:
            subprocess.run([exe, "--app-name=Voktora", "--", title, body], timeout=5, check=False, capture_output=True)  # noqa: S603
            return True
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon
        if QApplication.instance() and QSystemTrayIcon.isSystemTrayAvailable():
            tray = QSystemTrayIcon(QApplication.instance().windowIcon(), QApplication.instance())
            tray.show()
            tray.showMessage(title, body)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


class SyncWatcher:
    """Transforme les changements d'état de la synchronisation en notifications (erreur, blocage, fin, config reçue)."""

    def __init__(self):
        self._prev: dict[str, str] = {}
        self._blocked = False
        self._inbox = 0

    def feed(self, snap: dict) -> None:
        peers = snap.get("peers", {})
        for pid, st in peers.items():
            state = str(st.get("state", ""))
            if state != self._prev.get(pid):
                if state == "error":
                    notify("sync", "Synchronisation en erreur", str(st.get("detail", ""))[:200])
                elif state == "done" and self._prev.get(pid) in ("running", "scanning", "paused"):
                    notify("sync", "Synchronisation terminée", "")
                elif state == "decision":
                    notify("sync", "Synchronisation : votre choix est requis", "Ouvrez la fenêtre de synchronisation.")
                self._prev[pid] = state
        blocked = bool(snap.get("control", {}).get("blocked"))
        if blocked and not self._blocked:
            notify("sync", "Synchronisation bloquée", "Les configurations diffèrent : utilisez « Push config ».")
        self._blocked = blocked
        inbox = len(snap.get("config", {}).get("inbox", []))
        if inbox > self._inbox:
            notify("sync", "Configuration reçue", "Un autre PC vous a envoyé sa configuration : aperçu puis application.")
        self._inbox = inbox
