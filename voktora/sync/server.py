"""
Voktora — sync.server
Serveur HTTP de synchronisation (un par PC). Toutes les requêtes sont signées (HMAC) et leur contenu est chiffré
(AES-GCM) ; seuls les PC appairés — ou un invité présentant un code d'appairage valide — sont servis, et
seulement depuis une adresse réseau local / Tailscale / loopback (voir `net.is_allowed_address`).
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import net, secure, transfer
from .settings import SyncSettings
from .store import LocalStore, SyncPathError

LOCK_TTL = 120.0
MAX_JSON = 1 << 20


class Session:
    """Un seul pair à la fois peut écrire dans ce PC (verrou à durée limitée, renouvelé à chaque requête)."""

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self.owner = ""
        self.expires = 0.0

    def acquire(self, who: str) -> bool:
        with self._mutex:
            now = time.time()
            if self.owner and self.owner != who and now < self.expires:
                return False
            self.owner, self.expires = who, now + LOCK_TTL
            return True

    def touch(self, who: str) -> bool:
        with self._mutex:
            if self.owner == who and time.time() < self.expires:
                self.expires = time.time() + LOCK_TTL
                return True
            return False

    def release(self, who: str) -> None:
        with self._mutex:
            if self.owner == who:
                self.owner, self.expires = "", 0.0

    def held_by_other(self, who: str) -> bool:
        with self._mutex:
            return bool(self.owner and self.owner != who and time.time() < self.expires)


class SyncServer:
    def __init__(self, settings: SyncSettings, store: LocalStore, status_fn=None, request_fn=None,
                 busy_fn=None):
        self.settings, self.store = settings, store
        self.status_fn = status_fn or (lambda: {})
        self.request_fn = request_fn or (lambda device: False)
        self.busy_fn = busy_fn or (lambda: False)          # ce PC synchronise-t-il lui-même ?
        self.nonces = secure.NonceCache()
        self.session = Session()
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.port = 0

    def start(self, host: str = "0.0.0.0", port: int | None = None) -> int:
        server = self
        port = self.settings["port"] if port is None else port

        class Handler(_Handler):
            owner = server

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="voktora-sync-server", daemon=True)
        self.thread.start()
        return self.port

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None


class _Handler(BaseHTTPRequestHandler):
    owner: SyncServer
    server_version = "VoktoraSync"
    sys_version = ""

    def log_message(self, *args) -> None:       # silence
        pass

    # ── entrée ───────────────────────────────────────────────────────────────

    def _reply(self, code: int, body: bytes = b"", ctype: str = "application/octet-stream") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _fail(self, code: int, message: str) -> None:
        self._reply(code, json.dumps({"error": message}).encode(), "application/json")

    def _handle(self, method: str) -> None:
        owner = self.owner
        try:
            if not net.is_allowed_address(self.client_address[0]):
                return self._fail(403, "réseau non autorisé")
            if not owner.settings["enabled"]:
                return self._fail(503, "synchronisation désactivée")
            self._path = self.path
            url = urlsplit(self.path)
            route, query = url.path, {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
            device = self.headers.get("X-Voktora-Device", "")
            if route == "/pair":
                return self._pair(method, device)
            peer = owner.settings.peer(device)
            if not peer:
                return self._fail(401, "appareil inconnu")
            secret = owner.settings.peer_secret(peer)
            try:
                secure.verify_headers(secret, self.headers, method, self._path, owner.nonces)
            except secure.AuthError as exc:
                return self._fail(401, str(exc))
            self._enc = secure.derive(secret)[1]
            self._ctx = (self.headers["X-Voktora-Nonce"] + self._path).encode()
            self._device = device
            self._dispatch(method, route, query)
        except SyncPathError as exc:
            self._fail(400, str(exc))
        except KeyError as exc:
            self._fail(400, f"paramètre manquant ou inconnu : {exc}")
        except (secure.AuthError, ValueError) as exc:
            self._fail(400, str(exc))
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception as exc:  # noqa: BLE001 — ne jamais faire tomber le serveur
            with __import__("contextlib").suppress(Exception):
                self._fail(500, f"erreur interne : {exc}")

    do_GET = lambda self: self._handle("GET")      # noqa: E731
    do_POST = lambda self: self._handle("POST")    # noqa: E731
    do_PUT = lambda self: self._handle("PUT")      # noqa: E731

    # ── corps chiffrés ───────────────────────────────────────────────────────

    def _read_exact(self, n: int) -> bytes:
        return self.rfile.read(n)

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_JSON:
            raise ValueError("requête trop grande")
        raw = self.rfile.read(length)
        data = secure.decrypt_bytes(self._enc, self._ctx, raw) if raw else b"{}"
        out = json.loads(data or b"{}")
        if not isinstance(out, dict):
            raise ValueError("requête invalide")
        return out

    def _json(self, value) -> None:
        body = secure.encrypt_bytes(self._enc, self._ctx + b"R", json.dumps(value).encode())
        self._reply(200, body)

    # ── routes ───────────────────────────────────────────────────────────────

    def _dispatch(self, method: str, route: str, query: dict) -> None:
        o, store, dev = self.owner, self.owner.store, self._device
        if route == "/hello":
            return self._json({"id": o.settings.device_id, "name": o.settings["device_name"],
                               "primary_id": o.settings["primary_id"], "status": o.status_fn(),
                               "busy": o.busy_fn() or o.session.held_by_other(dev),
                               "port": o.port, "time": time.time(), "version": 3,
                               "features": ["delta", "zip"]})
        if route == "/keepalive":
            return self._json({"ok": o.session.touch(dev)})
        if route == "/request-sync":
            return self._json({"accepted": bool(o.request_fn(dev))})
        if route == "/lock":
            if o.busy_fn() or not o.session.acquire(dev):
                return self._fail(423, "ce PC est déjà occupé par une synchronisation")
            return self._json({"ok": True})
        if route == "/unlock":
            o.session.release(dev)
            return self._json({"ok": True})
        if method != "GET" and not o.session.touch(dev):
            return self._fail(423, "verrou absent : appelez /lock d'abord")
        if route == "/spaces":
            return self._json({"spaces": store.spaces()})
        if route == "/signatures":
            o.session.touch(dev)
            return self._json({"sigs": store.signatures()})
        if route == "/manifest":
            return self._manifest(query["space"])
        if route == "/blocks" and method == "GET":
            o.session.touch(dev)
            size, hashes = store.block_hashes(query["space"], query["rel"])
            return self._json({"size": size, "hashes": hashes})
        if route == "/file" and method == "GET":
            if query.get("blocks"):
                indices = transfer.decode_ranges(query["blocks"])
                chunks = store.open_blocks(query["space"], query["rel"], indices)
                size = sum(1 for _ in indices)
            else:
                size, chunks = store.open_reader(query["space"], query["rel"])
            zipped = query.get("z") == "1"
            if zipped:
                chunks = transfer.compress_chunks(chunks)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-Voktora-Size", str(size))
            if zipped:
                self.send_header("X-Voktora-Zip", "1")
            self.send_header("Connection", "close")
            self.end_headers()
            for block in secure.encrypt_stream(self._enc, self._ctx, chunks):
                self.wfile.write(block)
            return None
        if route == "/file" and method == "PUT":
            length = int(self.headers.get("Content-Length", "0"))
            remaining = length

            def read(n: int) -> bytes:
                nonlocal remaining
                n = min(n, remaining)
                data = self.rfile.read(n) if n > 0 else b""
                remaining -= len(data)
                return data
            incoming = secure.decrypt_stream(self._enc, self._ctx, read)
            if query.get("z") == "1":
                incoming = transfer.decompress_chunks(incoming)
            mode = int(query.get("mode", "0") or 0)
            if query.get("blocks"):
                store.write_delta(query["space"], query["rel"], int(query["total"]), transfer.decode_ranges(query["blocks"]),
                                  incoming, mode, expected_sha=query.get("sha", ""))
            else:
                store.write(query["space"], query["rel"], incoming, mode, expected_sha=query.get("sha", ""))
            return self._json({"ok": True})
        if route == "/delete" and method == "POST":
            body = self._body_json()
            store.delete(body["space"], body["rel"])
            return self._json({"ok": True})
        if route == "/commit" and method == "POST":
            store.commit(self._body_json()["space"])
            return self._json({"ok": True})
        return self._fail(404, "route inconnue")

    def _manifest(self, space: str) -> None:
        """Réponse en flux : lignes de progression (« p ») puis le résultat (« files »). Tant que l'analyse dure,
        le client reçoit de quoi savoir que ce PC travaille (pas de délai d'attente, pas de « préparation » muette)."""
        if space != "cfg":
            self.owner.store._root(space)        # espace invalide → erreur 400 propre, avant d'envoyer l'en-tête
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        writer = secure.FrameWriter(self._enc, self._ctx)

        def emit(line: dict) -> None:
            for block in writer.frames((json.dumps(line, separators=(",", ":")) + "\n").encode()):
                self.wfile.write(block)

        def progress(count: int, label: str) -> None:
            emit({"p": [count, label[-80:]]})
            self.owner.session.touch(self._device)

        try:
            entries = self.owner.store.manifest(space, None, progress)
        except Exception as exc:  # noqa: BLE001 — transmis au client, qui l'affiche
            emit({"error": f"{type(exc).__name__}: {exc}"})
            return
        emit({"files": {k: [e.sha, e.size, e.mode] for k, e in entries.items()}})
        self.close_connection = True

    # ── appairage ────────────────────────────────────────────────────────────

    def _pair(self, method: str, device: str) -> None:
        """Un nouveau PC se présente avec le secret d'un code d'appairage encore valide (usage unique)."""
        o = self.owner
        if method != "POST":
            return self._fail(405, "POST attendu")
        now = time.time()
        invites = [i for i in o.settings["invites"] if i.get("expires", 0) > now]
        match = None
        for invite in invites:
            secret = o.settings.peer_secret(invite)
            try:
                secure.verify_headers(secret, self.headers, "POST", self.path, o.nonces)
                match = (invite, secret)
                break
            except secure.AuthError:
                continue
        if match is None:
            return self._fail(401, "code d'appairage invalide ou expiré")
        invite, secret = match
        self._enc = secure.derive(secret)[1]
        self._ctx = (self.headers["X-Voktora-Nonce"] + self.path).encode()
        body = self._body_json()
        o.settings["invites"] = [i for i in invites if i is not invite]
        o.settings.add_peer(device, str(body.get("name", ""))[:64], self.client_address[0],
                            int(body.get("port", o.settings["port"])), secret)
        o.settings.save()
        self._json({"id": o.settings.device_id, "name": o.settings["device_name"],
                    "primary_id": o.settings["primary_id"]})
