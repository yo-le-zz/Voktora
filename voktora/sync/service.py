"""
Voktora — sync.service
Orchestration : serveur local, surveillance des pairs (uniquement sur le même réseau), synchronisation
automatique, statuts en pourcentage, reprise après extinction.

Qui démarre ? Un PC secondaire se synchronise vers le principal dès qu'il le voit ; le principal peut demander
à un secondaire de le faire (`request-sync`). Si l'un des deux s'éteint ou perd le réseau, la passe s'arrête
(`paused`), l'état déjà échangé est conservé et tout reprend au prochain passage réussi de la surveillance.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import net, secure
from .client import RemoteError, RemoteStore, pair
from .engine import Cancelled, PeerGone, Plan, SyncEngine, SyncError
from .server import SyncServer
from .settings import SyncSettings
from .store import ConfigIO, LocalStore

OFFLINE, ONLINE, SYNCING, DONE, DECISION, PAUSED, ERROR, IDLE = (
    "offline", "online", "syncing", "done", "decision", "paused", "error", "idle")
INVITE_TTL = 600.0


class SyncService:
    def __init__(self, data_dir: Path, config_io: ConfigIO, extras: dict[str, Path] | None = None):
        self.dir = Path(data_dir) / "sync"
        self.settings = SyncSettings(self.dir)
        self.store = LocalStore(self.settings, config_io, self.dir / "state", extras)
        self.server = SyncServer(self.settings, self.store, self._own_status, self._request_from_peer, self.is_busy)
        self.listeners: list[Callable[[dict], None]] = []
        self.status: dict[str, dict] = {}
        self._own = {"state": IDLE, "percent": 0, "detail": ""}
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._run = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pending: dict[str, Plan] = {}
        self._requested: set[str] = set()
        self._cancel_flag = threading.Event()
        self._tick = 0

    # ── statut ───────────────────────────────────────────────────────────────

    def add_listener(self, fn: Callable[[dict], None]) -> None:
        self.listeners.append(fn)

    def snapshot(self) -> dict:
        return {"enabled": self.settings["enabled"], "device_id": self.settings.device_id,
                "primary_id": self.settings["primary_id"], "own": dict(self._own),
                "peers": {k: dict(v) for k, v in self.status.items()}}

    def _emit(self) -> None:
        snap = self.snapshot()
        for fn in list(self.listeners):
            with contextlib.suppress(Exception):
                fn(snap)

    def _set(self, peer_id: str, **fields) -> None:
        peer = self.settings.peer(peer_id) or {}
        entry = self.status.setdefault(peer_id, {"name": peer.get("name", peer_id), "state": OFFLINE, "percent": 0,
                                                  "detail": "", "last_sync": 0.0, "summary": "", "remote": {}})
        entry["name"] = peer.get("name", entry["name"])
        entry.update(fields)
        self._emit()

    def _own_status(self) -> dict:
        return dict(self._own)

    def is_busy(self) -> bool:
        return self._run.locked()

    def peer_is_primary(self, peer_id: str) -> bool:
        return self.settings["primary_id"] == peer_id

    # ── cycle de vie ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.settings["enabled"] or self._thread:
            return
        with contextlib.suppress(OSError):
            self.store.purge_trash()
        try:
            self.server.start()
        except OSError as exc:
            self._own = {"state": ERROR, "percent": 0, "detail": f"port {self.settings['port']} indisponible ({exc})"}
            self._emit()
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="voktora-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._cancel_flag.set()
        self._wake.set()
        self.server.stop()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None

    def restart(self) -> None:
        self.stop()
        self._cancel_flag.clear()
        self.start()

    def refresh_now(self) -> None:
        self._wake.set()

    def cancel(self) -> None:
        self._cancel_flag.set()

    # ── boucle de surveillance ───────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._tick += 1
            with contextlib.suppress(Exception):
                self._scan()
            self._wake.wait(max(5, int(self.settings["interval"])))
            self._wake.clear()

    def _scan(self) -> None:
        for peer in list(self.settings["peers"]):
            if self._stop.is_set():
                return
            pid = peer["id"]
            if not net.same_network(peer["host"]):
                self._set(pid, state=OFFLINE, detail="pas sur le même réseau (LAN / Tailscale)", remote={})
                continue
            remote = self._remote(peer)
            try:
                info = remote.hello()
            except (ConnectionError, RemoteError) as exc:
                self._set(pid, state=OFFLINE, detail=f"éteint ou injoignable ({exc})", remote={})
                continue
            current = self.status.get(pid, {})
            keep = current.get("state") in (DECISION, SYNCING)
            self._set(pid, remote=info.get("status", {}), reachable=True,
                      **({} if keep else {"state": ONLINE, "detail": "connecté"}))
            if not self.settings["auto"] or keep or self._run.locked():
                continue
            if pid in self._requested or not self.settings.is_primary or self._tick % 4 == 0:
                self._requested.discard(pid)
                if not self.settings.is_primary:
                    self.sync_peer(pid)
                elif not info.get("busy"):
                    with contextlib.suppress(ConnectionError, RemoteError):
                        remote.request_sync()

    def _remote(self, peer: dict) -> RemoteStore:
        return RemoteStore(peer["host"], peer["port"], self.settings.device_id, self.settings.peer_secret(peer))

    def _request_from_peer(self, device: str) -> bool:
        """Le PC principal nous demande de nous synchroniser."""
        if self._run.locked() or not self.settings["enabled"]:
            return False
        self._requested.add(device)
        self._wake.set()
        return True

    # ── synchronisation ──────────────────────────────────────────────────────

    def _first_sync(self) -> str:
        return {"ask": "ask"}.get(self.settings["policy"], "primary")

    def sync_peer(self, peer_id: str, first_sync: str | None = None) -> Plan | None:
        """Synchronise avec un pair (appelable depuis l'UI ou la surveillance). Retourne le plan exécuté,
        ou celui en attente d'une décision de l'utilisateur."""
        peer = self.settings.peer(peer_id)
        if not peer or not self._run.acquire(blocking=False):
            return None
        self._cancel_flag.clear()
        remote = self._remote(peer)
        locked = False
        plan = None
        try:
            self._set(peer_id, state=SYNCING, percent=0, detail="préparation…")
            self._own = {"state": SYNCING, "percent": 0, "detail": f"avec {peer['name']}"}
            remote.lock()
            locked = True
            engine = SyncEngine(self.store, remote, peer_id, self.settings, self.dir / "state" / "base",
                                self.settings.is_primary, lambda p, d: self._progress(peer_id, p, d),
                                self._cancel_flag.is_set, self.settings["device_name"])
            plan = engine.plan(first_sync or self._first_sync())
            if plan.needs_decision:
                self._pending[peer_id] = plan
                self._set(peer_id, state=DECISION, percent=0, summary=plan.summary(),
                          detail="les deux PC ont des contenus différents : choisissez la source")
                return plan
            self._pending.pop(peer_id, None)
            result = engine.apply(plan)
            problems = result["errors"]
            self._set(peer_id, state=DONE if not problems else ERROR, percent=100, last_sync=time.time(),
                      summary=plan.summary(), detail="à jour" if not problems else f"{len(problems)} erreur(s) : {problems[0]}")
        except Cancelled:
            self._set(peer_id, state=PAUSED, detail="arrêtée — reprendra au prochain passage")
        except (PeerGone, ConnectionError) as exc:
            self._set(peer_id, state=PAUSED, detail=f"pair indisponible, reprise automatique ({exc})")
        except (SyncError, RemoteError) as exc:
            self._set(peer_id, state=ERROR, detail=str(exc))
        finally:
            if locked:
                remote.unlock()
            self._own = {"state": IDLE, "percent": 0, "detail": ""}
            self._run.release()
            self._emit()
        return plan

    def resolve(self, peer_id: str, choice: str) -> None:
        """Réponse à « de quelle source synchroniser ? » : 'local' (ce PC), 'remote' (l'autre), 'primary'."""
        if choice not in ("local", "remote", "primary"):
            self._pending.pop(peer_id, None)
            self._set(peer_id, state=ONLINE, detail="synchronisation annulée")
            return
        self._pending.pop(peer_id, None)
        threading.Thread(target=self.sync_peer, args=(peer_id, choice), daemon=True, name="voktora-sync-run").start()

    def _progress(self, peer_id: str, percent: int, detail: str) -> None:
        self._own = {"state": SYNCING, "percent": percent, "detail": detail}
        self._set(peer_id, state=SYNCING, percent=percent, detail=detail)

    # ── appairage ────────────────────────────────────────────────────────────

    def preferred_address(self) -> str:
        addrs = net.local_addresses()
        return (addrs["tailscale"] or addrs["lan"] or ["127.0.0.1"])[0]

    def create_invite(self, host: str | None = None) -> str:
        """Code d'appairage à saisir sur l'autre PC (valable 10 min, usage unique)."""
        import base64
        secret = secure.new_secret()
        s = self.settings
        s["invites"] = [i for i in s["invites"] if i.get("expires", 0) > time.time()][-4:] + [
            {"secret": base64.urlsafe_b64encode(secret).decode(), "expires": time.time() + INVITE_TTL}]
        s.save()
        return secure.make_pairing_code(s.device_id, s["device_name"], host or self.preferred_address(),
                                        s["port"], secret, s["primary_id"])

    def join(self, code: str) -> dict:
        """Utilise un code reçu de l'autre PC. Lève ValueError (code), ConnectionError ou RemoteError."""
        data = secure.parse_pairing_code(code)
        if data["id"] == self.settings.device_id:
            raise ValueError("Ce code vient de ce PC : saisissez-le sur l'autre.")
        s = self.settings
        reply = pair(data, s.device_id, s["device_name"], s["port"])
        s.add_peer(data["id"], reply.get("name") or data["name"], data["host"], data["port"], data["secret"])
        if data["primary"]:
            s.set_primary(data["primary"])
        s["enabled"] = True
        s.save()
        self.restart()
        return reply

    def forget(self, peer_id: str) -> None:
        self.settings.remove_peer(peer_id)
        self.settings.save()
        self.status.pop(peer_id, None)
        self._emit()

    def set_primary(self, device_id: str) -> None:
        self.settings.set_primary(device_id)
        self.settings.save()
        self._emit()
