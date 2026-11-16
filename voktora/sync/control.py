"""
Voktora — sync.control (1.1.4)
Machine d'états « pause / reprise / stop » de la synchronisation. Logique pure : aucun Qt, aucun réseau, aucun disque.

États affichés :
  • STOPPED  « Arrêtée »          rien ne tourne, aucune boucle, aucune connexion, aucun verrou ;
  • RUNNING  « En cours »         la surveillance est active et/ou une passe est en cours ;
  • PAUSED   « En pause »         tout est suspendu, l'état est conservé : la reprise repart là où on s'était arrêté ;
  • BLOCKED  « Bloquée : config » au moins un pair a une configuration différente (voir configpack.evaluate_gate).

Fonctionnement : chaque passe de synchronisation reçoit un `RunToken` ; le moteur appelle `checkpoint(token)` entre deux
actions et entre deux blocs de fichier. `checkpoint` :
  • lève `StopRequested` si Stop a été demandé depuis (la passe se termine proprement : .part supprimés, verrou rendu) ;
  • attend sur place tant que la pause dure (en appelant `keepalive` pour garder le verrou de l'autre PC vivant) ;
  • lève `PauseTimeout` si la pause dure plus de `hold_seconds` : la passe se « suspend » (état de reprise écrit, verrou
    rendu) et sera relancée par `resume()` — on ne garde jamais l'autre PC verrouillé pendant des heures.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

STOPPED, RUNNING, PAUSED, BLOCKED = "stopped", "running", "paused", "blocked"
LABELS = {STOPPED: "Arrêtée", RUNNING: "En cours", PAUSED: "En pause", BLOCKED: "Bloquée : config"}
ICONS = {STOPPED: "⏹", RUNNING: "▶", PAUSED: "⏸", BLOCKED: "⛔"}


class StopRequested(Exception):
    """Stop demandé : le travail en cours doit se terminer proprement."""


class PauseTimeout(Exception):
    """La pause dure trop longtemps pour garder l'autre PC verrouillé : la passe se suspend (reprise relancée au resume)."""


@dataclass(frozen=True)
class RunToken:
    generation: int


class SyncController:
    def __init__(self, hold_seconds: float = 300.0, poll: float = 0.5, clock: Callable[[], float] = time.monotonic):
        self._cond = threading.Condition()
        self._paused = False
        self._running = False           # surveillance démarrée (boucle du service)
        self._runs = 0                  # passes en cours
        self._generation = 0            # incrémentée par stop() : invalide tous les jetons existants
        self._blocked: dict[str, str] = {}
        self._resources: list[object] = []
        self._cleanups: list[Callable[[], None]] = []
        self.hold_seconds = float(hold_seconds)
        self._poll = poll
        self._clock = clock
        self.listeners: list[Callable[[str], None]] = []
        self._last_state = STOPPED

    # ── lecture ──────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        with self._cond:
            return self._state_locked()

    def _state_locked(self) -> str:
        if self._paused:
            return PAUSED
        if self._blocked and self._runs == 0:
            return BLOCKED
        return RUNNING if (self._running or self._runs) else STOPPED

    @property
    def label(self) -> str:
        return LABELS[self.state]

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def active_runs(self) -> int:
        return self._runs

    def blocked_reasons(self) -> dict[str, str]:
        with self._cond:
            return dict(self._blocked)

    def snapshot(self) -> dict:
        state = self.state
        return {"state": state, "label": LABELS[state], "icon": ICONS[state], "paused": self._paused,
                "runs": self._runs, "blocked": self.blocked_reasons()}

    def can(self, action: str) -> bool:
        """Boutons utilisables : « pause », « resume », « stop »."""
        with self._cond:
            if action == "pause":
                return not self._paused and (self._running or self._runs > 0)
            if action == "resume":
                return self._paused
            if action == "stop":
                return self._running or self._paused or self._runs > 0 or bool(self._blocked)
        return False

    # ── commandes ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Démarre la surveillance (sort aussi de la pause)."""
        with self._cond:
            self._running, self._paused = True, False
            self._cond.notify_all()
        self._changed()

    def pause(self) -> bool:
        with self._cond:
            if self._paused or not (self._running or self._runs > 0):
                return False
            self._paused = True
            self._cond.notify_all()
        self._changed()
        return True

    def resume(self) -> bool:
        with self._cond:
            if not self._paused:
                return False
            self._paused = False
            self._cond.notify_all()
        self._changed()
        return True

    def stop(self) -> None:
        """Arrêt : invalide toutes les passes en cours (elles s'arrêtent au prochain point de contrôle), ferme les
        ressources enregistrées (connexions), lève la pause et le blocage, puis lance les nettoyages."""
        with self._cond:
            self._generation += 1
            self._running = self._paused = False
            self._blocked.clear()
            resources, self._resources = self._resources, []
            cleanups = list(self._cleanups)
            self._cond.notify_all()
        for resource in resources:
            with contextlib.suppress(Exception):
                resource.close()
        for cleanup in cleanups:
            with contextlib.suppress(Exception):
                cleanup()
        self._changed()

    # ── blocage « configuration » ────────────────────────────────────────────

    def block(self, key: str, reason: str) -> None:
        with self._cond:
            self._blocked[key] = reason
        self._changed()

    def unblock(self, key: str | None = None) -> None:
        with self._cond:
            if key is None:
                self._blocked.clear()
            else:
                self._blocked.pop(key, None)
        self._changed()

    # ── passes ───────────────────────────────────────────────────────────────

    def begin_run(self) -> RunToken | None:
        """Jeton d'une nouvelle passe, ou None si la synchronisation est en pause (on ne démarre rien en pause)."""
        with self._cond:
            if self._paused:
                return None
            self._runs += 1
            token = RunToken(self._generation)
        self._changed()
        return token

    def end_run(self, token: RunToken) -> None:
        with self._cond:
            self._runs = max(0, self._runs - 1)
        self._changed()

    def cancelled(self, token: RunToken) -> bool:
        return token.generation != self._generation

    def checkpoint(self, token: RunToken, keepalive: Callable[[], None] | None = None) -> None:
        """Point de contrôle : voir le docstring du module."""
        started = self._clock()
        while True:
            with self._cond:
                if token.generation != self._generation:
                    raise StopRequested("Synchronisation arrêtée.")
                if not self._paused:
                    return
                if self._clock() - started > self.hold_seconds:
                    raise PauseTimeout("Pause prolongée : synchronisation suspendue, elle reprendra à la reprise.")
                self._cond.wait(self._poll)
            if keepalive:
                with contextlib.suppress(Exception):
                    keepalive()

    # ── ressources et nettoyage ──────────────────────────────────────────────

    def register(self, resource: object) -> None:
        """Ressource à fermer (méthode `close()`) si Stop est demandé (ex. connexion en cours)."""
        with self._cond:
            self._resources.append(resource)

    def release(self, resource: object) -> None:
        with self._cond:
            self._resources = [r for r in self._resources if r is not resource]

    def add_cleanup(self, fn: Callable[[], None]) -> None:
        with self._cond:
            self._cleanups.append(fn)

    # ── notifications ────────────────────────────────────────────────────────

    def _changed(self) -> None:
        state = self.state
        if state == self._last_state:
            return
        self._last_state = state
        for fn in list(self.listeners):
            with contextlib.suppress(Exception):
                fn(state)
