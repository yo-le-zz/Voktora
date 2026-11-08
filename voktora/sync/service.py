"""
Voktora — sync.service
Orchestration : serveur local, surveillance des pairs (uniquement sur le même réseau), synchronisation
automatique, statuts en pourcentage, reprise après extinction.

Qui démarre ? Un PC secondaire se synchronise vers le principal dès qu'il le voit ; le principal peut demander
à un secondaire de le faire (`request-sync`). Si l'un des deux s'éteint ou perd le réseau, la passe s'arrête
(`paused`), l'état déjà échangé est conservé et tout reprend au prochain passage réussi de la surveillance.
"""

from __future__ import annotations

import collections
import contextlib
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from . import net, secure
from .client import RemoteError, RemoteStore, pair
from .engine import Cancelled, PeerGone, Plan, SyncEngine, SyncError
from .server import SyncServer
from .settings import DEFAULT_PORT, SyncSettings
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
        self.logs: collections.deque[str] = collections.deque(maxlen=400)
        self._log_path = self.dir / "sync.log"

    # ── statut ───────────────────────────────────────────────────────────────

    def add_listener(self, fn: Callable[[dict], None]) -> None:
        self.listeners.append(fn)

    def snapshot(self) -> dict:
        return {"enabled": self.settings["enabled"], "device_id": self.settings.device_id,
                "primary_id": self.settings["primary_id"], "own": dict(self._own),
                "port": self.server.port, "log": list(self.logs)[-120:],
                "peers": {k: dict(v) for k, v in self.status.items()}}

    def log(self, text: str, peer_id: str = "") -> None:
        """Journal lisible (interface + fichier `sync/sync.log`, tourné à 1 Mo)."""
        name = (self.settings.peer(peer_id) or {}).get("name", "") if peer_id else ""
        line = f"{time.strftime('%H:%M:%S')}  {('[' + name + '] ') if name else ''}{text}"
        self.logs.append(line)
        with contextlib.suppress(OSError):
            self.dir.mkdir(parents=True, exist_ok=True)
            if self._log_path.exists() and self._log_path.stat().st_size > 1_000_000:
                self._log_path.replace(self._log_path.with_suffix(".log.1"))
            with open(self._log_path, "a", encoding="utf-8") as handle:
                handle.write(time.strftime("%Y-%m-%d ") + line + "\n")
        self._emit()

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
        if not self._start_server():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="voktora-sync", daemon=True)
        self._thread.start()

    def _start_server(self) -> bool:
        """Ouvre le port d'écoute ; s'il est pris, en choisit un libre tout seul (les pairs le retrouvent)."""
        wanted = int(self.settings["port"] or DEFAULT_PORT)
        candidates = [wanted] + ([p for p in range(DEFAULT_PORT, DEFAULT_PORT + 20) if p != wanted] + [0]
                                 if self.settings["port_auto"] else [])
        last: OSError | None = None
        for port in candidates:
            try:
                self.server = SyncServer(self.settings, self.store, self._own_status, self._request_from_peer,
                                         self.is_busy)
                actual = self.server.start(port=port)
            except OSError as exc:
                last = exc
                continue
            if actual != wanted:
                self.log(f"Le port {wanted} était occupé : écoute sur le port {actual} (les autres PC le retrouvent seuls).")
                self.settings["port"] = actual
                self.settings.save()
            else:
                self.log(f"À l'écoute sur le port {actual} (réseaux autorisés : LAN privé et Tailscale).")
            return True
        self._own = {"state": ERROR, "percent": 0, "detail": f"aucun port disponible ({last})"}
        self.log(f"Impossible d'ouvrir un port d'écoute : {last}")
        return False

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
                info = self._hello(peer, remote)
            except (ConnectionError, RemoteError) as exc:
                if self.status.get(pid, {}).get("state") not in (OFFLINE,):
                    self.log(f"Plus de contact : {exc}", pid)
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

    def _hello(self, peer: dict, remote: RemoteStore) -> dict:
        """Prend des nouvelles du pair ; si son port a changé, le retrouve et mémorise le nouveau."""
        try:
            info = remote.hello()
        except ConnectionError:
            found = self._discover_port(peer)
            if not found:
                raise
            remote = self._remote(peer)
            info = remote.hello()
        if info.get("port") and int(info["port"]) != int(peer["port"]):
            self._remember_port(peer, int(info["port"]))
        was = self.status.get(peer["id"], {}).get("state")
        if was in (None, OFFLINE):
            self.log(f"Contact établi ({info.get('rtt_ms', '?')} ms)", peer["id"])
        return info

    def _remember_port(self, peer: dict, port: int) -> None:
        if port != peer["port"]:
            self.log(f"Nouveau port de l'autre PC : {port}", peer["id"])
            peer["port"] = port
            self.settings.save()

    def _discover_port(self, peer: dict) -> bool:
        """Le pair a peut-être changé de port (le sien était occupé) : on essaie la plage habituelle."""
        for port in range(DEFAULT_PORT, DEFAULT_PORT + 20):
            if port == peer["port"] or self._stop.is_set():
                continue
            probe = RemoteStore(peer["host"], port, self.settings.device_id, self.settings.peer_secret(peer), timeout=1.2)
            try:
                if probe.hello().get("id") == peer["id"]:
                    self._remember_port(peer, port)
                    return True
            except (ConnectionError, RemoteError):
                continue
        return False

    def diagnose(self, peer_id: str) -> list[tuple[bool, str]]:
        """Test de connexion pas à pas, avec la cause probable à chaque échec (bouton « Tester la connexion »)."""
        import socket
        peer = self.settings.peer(peer_id)
        out: list[tuple[bool, str]] = []
        if not peer:
            return [(False, "PC inconnu : refaites l'appairage.")]
        host, port = peer["host"], int(peer["port"])
        ok = net.same_network(peer["host"])
        out.append((ok, f"Réseau : {host} " + ("est sur le même réseau (LAN / Tailscale)." if ok else
                    "n'est pas sur votre réseau : connectez les deux PC au même Wi-Fi ou à Tailscale (`tailscale up`).")))
        if not ok:
            return out
        started = time.monotonic()
        try:
            socket.create_connection((host, port), timeout=4).close()
            out.append((True, f"Port {port} ouvert ({int((time.monotonic() - started) * 1000)} ms)."))
        except OSError as exc:
            found = self._discover_port(peer)
            if found:
                out.append((True, f"Le port avait changé : retrouvé sur {peer['port']}."))
            else:
                out.append((False, f"Port {port} injoignable ({exc}). L'autre PC est-il allumé avec Voktora ouvert ? "
                                   "Pare-feu : autorisez le port TCP (ex. `sudo firewall-cmd --add-port=47821/tcp` sous Fedora, "
                                   "`sudo ufw allow 47821/tcp` sous Ubuntu/Arch)."))
                return out
        remote = self._remote(peer)
        try:
            info = remote.hello()
        except RemoteError as exc:
            hint = ""
            if "horloge" in str(exc):
                hint = " → l'heure des deux PC diffère de plus de 2 minutes : activez la synchronisation automatique de l'heure."
            elif exc.status == 401:
                hint = " → appairage périmé ou secret différent : supprimez le PC des deux côtés et refaites le code."
            out.append((False, f"Authentification refusée : {exc}{hint}"))
            return out
        except ConnectionError as exc:
            out.append((False, f"Connexion coupée pendant l'échange : {exc}"))
            return out
        skew = abs(float(info.get("time", time.time())) - time.time())
        out.append((True, f"Authentification OK, échange chiffré fonctionnel ({info.get('rtt_ms', '?')} ms)."))
        out.append((skew < 60, f"Horloge : écart de {skew:.0f} s" + ("." if skew < 60 else " (trop grand : réglez l'heure).")))
        out.append((not info.get("busy"), "L'autre PC est libre." if not info.get("busy") else "L'autre PC est occupé (réessayez dans un instant)."))
        return out

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
        started = time.monotonic()
        try:
            self._progress(peer_id, 0, f"Connexion à {peer['name']} ({peer['host']}:{peer['port']})…")
            self.log(f"Début de la synchronisation avec {peer['name']} ({'principal' if self.peer_is_primary(peer_id) else 'secondaire'})", peer_id)
            try:
                info = self._hello(peer, remote)
            except (ConnectionError, RemoteError) as exc:
                raise PeerGone(f"{peer['name']} est injoignable ({exc}). Utilisez « Tester la connexion » pour le détail.") from exc
            remote = self._remote(peer)              # le port a pu changer pendant la recherche
            self._progress(peer_id, 0, f"Connecté ({info.get('rtt_ms', '?')} ms) — réservation de {peer['name']}…")
            remote.lock()
            locked = True
            self.log("Autre PC réservé : aucune autre synchronisation ne peut l'écrire en même temps", peer_id)
            engine = SyncEngine(self.store, remote, peer_id, self.settings, self.dir / "state" / "base",
                                self.settings.is_primary, lambda p, d: self._progress(peer_id, p, d),
                                self._cancel_flag.is_set, self.settings["device_name"],
                                lambda text: self.log(text, peer_id), peer["name"])
            plan = engine.plan(first_sync or self._first_sync())
            for warning in plan.warnings:
                self.log(f"Attention : {warning}", peer_id)
            if plan.needs_decision:
                self._pending[peer_id] = plan
                self.log(f"{sum(d.count for d in plan.decisions)} divergence(s) au premier échange : choix de la source demandé", peer_id)
                self._set(peer_id, state=DECISION, percent=0, summary=plan.summary(),
                          detail="les deux PC ont des contenus différents : choisissez la source")
                return plan
            self._pending.pop(peer_id, None)
            result = engine.apply(plan)
            problems = result["errors"]
            for problem in problems[:20]:
                self.log(f"Erreur : {problem}", peer_id)
            elapsed = time.monotonic() - started
            self.log(f"Terminé en {elapsed:.1f} s : {plan.summary()}" + (f" — {len(problems)} erreur(s)" if problems else ""), peer_id)
            self._set(peer_id, state=DONE if not problems else ERROR, percent=100, last_sync=time.time(),
                      summary=plan.summary(), detail="à jour" if not problems else f"{len(problems)} erreur(s) : {problems[0]}")
        except Cancelled:
            self.log("Synchronisation arrêtée", peer_id)
            self._set(peer_id, state=PAUSED, detail="arrêtée — reprendra au prochain passage")
        except (PeerGone, ConnectionError) as exc:
            self.log(f"Pause : {exc} — reprise automatique dès que l'autre PC revient", peer_id)
            self._set(peer_id, state=PAUSED, detail=f"pair indisponible, reprise automatique ({exc})")
        except RemoteError as exc:
            hint = " (heure des deux PC différente ?)" if "horloge" in str(exc) else ""
            self.log(f"Refusé par l'autre PC : {exc}{hint}", peer_id)
            self._set(peer_id, state=ERROR, detail=f"{exc}{hint}")
        except SyncError as exc:
            self.log(f"Erreur : {exc}", peer_id)
            self._set(peer_id, state=ERROR, detail=str(exc))
        except Exception as exc:  # noqa: BLE001 — jamais de fil mort silencieux : tout est expliqué dans le journal
            self.log(f"Erreur interne {type(exc).__name__}: {exc}", peer_id)
            for line in traceback.format_exc().splitlines()[-12:]:
                self.log("   " + line, peer_id)
            self._set(peer_id, state=ERROR, detail=f"erreur interne ({type(exc).__name__}: {exc}) — voir le journal")
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
