"""
Voktora — sync.client
Accès à un pair : même interface que `LocalStore` (spaces/manifest/open_reader/write/delete/commit) mais via le
protocole signé + chiffré du serveur. Les erreurs réseau deviennent `ConnectionError` (le moteur les traite
comme « pair éteint » et reprendra plus tard).
"""

from __future__ import annotations

import contextlib
import http.client
import json
import socket
import time
import urllib.parse
from collections.abc import Iterator

from . import secure, transfer
from .store import Entry, SyncPathError

TIMEOUT = 30.0
RETRY_DELAYS = (0.5, 1.5, 4.0)


class LockLost(ConnectionError):
    """Le verrou posé sur l'autre PC a expiré (réseau coupé trop longtemps) : il faut le reprendre."""


class RemoteError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class RemoteStore:
    def __init__(self, host: str, port: int, device_id: str, secret: bytes, timeout: float = TIMEOUT):
        self.host, self.port, self.device_id, self.secret, self.timeout = host, int(port), device_id, secret, timeout
        self._enc = secure.derive(secret)[1]
        self._locked = False

    # ── bas niveau ───────────────────────────────────────────────────────────

    def _request(self, method: str, route: str, params: dict | None = None, body: bytes | None = None,
                 content_length: int | None = None):
        path = route + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = secure.sign_headers(self.secret, self.device_id, method, path)
        ctx = (headers["X-Voktora-Nonce"] + path).encode()
        data = None
        if body is not None:
            headers["Content-Length"] = str(content_length if content_length is not None else len(body))
            data = body
        conn = self._connect()
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            conn.close()
            raise ConnectionError(f"{self.host}:{self.port} injoignable ({exc})") from exc
        return conn, resp, ctx

    def _connect(self) -> http.client.HTTPConnection:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.connect()
        except OSError as exc:
            conn.close()
            raise ConnectionError(f"{self.host}:{self.port} injoignable ({exc})") from exc
        with contextlib.suppress(OSError):
            conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        return conn

    def _call(self, method: str, route: str, params: dict | None = None, payload: dict | None = None) -> dict:
        path = route + ("?" + urllib.parse.urlencode(params) if params else "")
        if payload is not None:
            # le contexte dépend du nonce : on signe d'abord puis on chiffre
            return self._call_with_body(method, route, params, payload)
        conn, resp, ctx = self._request(method, route, params)
        return self._finish(conn, resp, ctx, path)

    def _call_with_body(self, method, route, params, payload) -> dict:
        path = route + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = secure.sign_headers(self.secret, self.device_id, method, path)
        ctx = (headers["X-Voktora-Nonce"] + path).encode()
        blob = secure.encrypt_bytes(self._enc, ctx, json.dumps(payload).encode())
        headers["Content-Length"] = str(len(blob))
        conn = self._connect()
        try:
            conn.request(method, path, body=blob, headers=headers)
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            conn.close()
            raise ConnectionError(f"{self.host}:{self.port} injoignable ({exc})") from exc
        return self._finish(conn, resp, ctx, path)

    def _finish(self, conn, resp, ctx: bytes, path: str) -> dict:
        try:
            raw = resp.read()
        except (OSError, http.client.HTTPException) as exc:
            raise ConnectionError(str(exc)) from exc
        finally:
            conn.close()
        if resp.status != 200:
            try:
                message = json.loads(raw).get("error", "")
            except (ValueError, AttributeError):
                message = raw[:200].decode("utf-8", "replace")
            if resp.status == 423 and not path.startswith("/lock"):
                raise LockLost(message or "verrou perdu")
            raise RemoteError(resp.status, message or f"HTTP {resp.status}")
        try:
            return json.loads(secure.decrypt_bytes(self._enc, ctx + b"R", raw))
        except (secure.AuthError, ValueError) as exc:
            raise RemoteError(502, "réponse invalide ou altérée") from exc

    # ── appairage / état ─────────────────────────────────────────────────────

    def _retry(self, fn, on_retry=None):
        """Rejoue une lecture idempotente après une coupure brève (réseau instable)."""
        last: Exception | None = None
        for attempt, delay in enumerate((0.0, *RETRY_DELAYS)):
            if attempt:
                if on_retry:
                    on_retry(attempt, len(RETRY_DELAYS), last)
                time.sleep(delay)
            try:
                return fn()
            except LockLost:
                self.relock()
                last = ConnectionError("verrou renouvelé")
            except ConnectionError as exc:
                last = exc
        raise last or ConnectionError("injoignable")

    features: set = frozenset()

    def hello(self) -> dict:
        started = time.monotonic()
        info = self._call("GET", "/hello")
        info["rtt_ms"] = int((time.monotonic() - started) * 1000)
        self.features = set(info.get("features", ()))          # delta / zip : seulement avec un pair 1.1.1+
        return info

    def keepalive(self) -> bool:
        return bool(self._call("GET", "/keepalive").get("ok"))

    def relock(self) -> None:
        self._locked = False
        self.lock()

    def request_sync(self) -> bool:
        return bool(self._call("POST", "/request-sync", payload={}).get("accepted"))

    def lock(self) -> None:
        try:
            self._call("POST", "/lock", payload={})
        except RemoteError as exc:
            if exc.status == 423:
                raise ConnectionError(str(exc)) from exc
            raise
        self._locked = True

    def unlock(self) -> None:
        if self._locked:
            self._locked = False
            try:
                self._call("POST", "/unlock", payload={})
            except (ConnectionError, RemoteError):
                pass

    # ── interface « magasin » ────────────────────────────────────────────────

    def spaces(self) -> list[str]:
        return list(self._retry(lambda: self._call("GET", "/spaces"))["spaces"])

    def signatures(self) -> dict[str, str]:
        """Empreintes rapides de tous les espaces de l'autre PC (aucune lecture de fichier là-bas)."""
        return dict(self._retry(lambda: self._call("GET", "/signatures"))["sigs"])

    def manifest(self, space: str, progress=None, on_retry=None) -> dict[str, Entry]:
        """Liste des fichiers d'un espace. Pendant que l'autre PC analyse, `progress(n, étiquette)` est appelé."""
        return self._retry(lambda: self._manifest_once(space, progress), on_retry)

    def _manifest_once(self, space: str, progress) -> dict[str, Entry]:
        conn, resp, ctx = self._request("GET", "/manifest", {"space": space})
        try:
            if resp.status != 200:
                raw = resp.read()
                try:
                    message = json.loads(raw).get("error", "")
                except ValueError:
                    message = raw[:200].decode("utf-8", "replace")
                if resp.status == 423:
                    raise LockLost(message)
                raise RemoteError(resp.status, message or f"HTTP {resp.status}")
            buffer, result = b"", None
            try:
                for block in secure.decrypt_stream(self._enc, ctx, resp.read):
                    buffer += block
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        msg = json.loads(line)
                        if "p" in msg and progress:
                            progress(int(msg["p"][0]), str(msg["p"][1]))
                        elif "error" in msg:
                            raise RemoteError(500, msg["error"])
                        elif "files" in msg:
                            result = msg["files"]
            except (OSError, http.client.HTTPException, secure.AuthError) as exc:
                raise ConnectionError(f"analyse interrompue ({exc})") from exc
        finally:
            conn.close()
        if result is None:
            raise ConnectionError("analyse interrompue (réponse incomplète)")
        return {rel: Entry(v[0], int(v[1]), int(v[2])) for rel, v in result.items()}

    def block_hashes(self, space: str, rel: str) -> tuple[int, list[str]] | None:
        """(taille, empreintes de blocs) du fichier de l'autre PC ; None si ce PC ne gère pas le delta (version < 1.1.1)."""
        try:
            data = self._call("GET", "/blocks", {"space": space, "rel": rel})
        except RemoteError as exc:
            if exc.status == 404:
                return None
            raise
        return int(data["size"]), list(data["hashes"])

    def open_reader(self, space: str, rel: str, blocks: list[int] | None = None,
                    zip: bool = False) -> tuple[int, Iterator[bytes]]:  # noqa: A002
        params = {"space": space, "rel": rel}
        if blocks is not None:
            params["blocks"] = transfer.encode_ranges(blocks)
        if zip:
            params["z"] = "1"
        conn, resp, ctx = self._request("GET", "/file", params)
        if resp.status != 200:
            raw = resp.read()
            conn.close()
            if resp.status == 400:
                raise SyncPathError(json.loads(raw).get("error", "refusé"))
            raise RemoteError(resp.status, raw[:200].decode("utf-8", "replace"))
        size = int(resp.getheader("X-Voktora-Size", "0"))
        enc = self._enc
        zipped = resp.getheader("X-Voktora-Zip") == "1"

        def stream() -> Iterator[bytes]:
            try:
                plain = secure.decrypt_stream(enc, ctx, resp.read)
                yield from (transfer.decompress_chunks(plain) if zipped else plain)
            except (OSError, http.client.HTTPException) as exc:
                raise ConnectionError(str(exc)) from exc
            except secure.AuthError as exc:
                raise ConnectionError(f"flux interrompu ou altéré ({exc})") from exc
            finally:
                conn.close()
        return size, stream()

    def write(self, space: str, rel: str, size: int, chunks, mode: int = 0, sha: str = "",
              blocks: list[int] | None = None, total: int = 0, zip: bool = False) -> None:  # noqa: A002
        """Envoie un fichier. `blocks` + `total` : delta (seuls ces blocs sont envoyés). `zip` : compression par blocs."""
        params = {"space": space, "rel": rel, "mode": mode, "sha": sha}
        if blocks is not None:
            params["blocks"], params["total"] = transfer.encode_ranges(blocks), total
        spool = None
        if zip:
            params["z"] = "1"
            spool = transfer.Spool(chunks)                    # taille chiffrée connue avant l'envoi
            chunks = spool.iter()
        path = "/file?" + urllib.parse.urlencode(params)
        headers = secure.sign_headers(self.secret, self.device_id, "PUT", path)
        ctx = (headers["X-Voktora-Nonce"] + path).encode()
        headers["Content-Length"] = str(spool.encrypted_length if spool else secure.encrypted_length(size))
        conn = self._connect()
        try:
            conn.putrequest("PUT", path, skip_accept_encoding=True)
            for key, value in headers.items():
                conn.putheader(key, value)
            conn.endheaders()
            sent = 0
            for block in secure.encrypt_stream(self._enc, ctx, chunks):
                conn.send(block)
                sent += len(block)
            if sent != int(headers["Content-Length"]):
                raise SyncPathError(f"{rel} a changé pendant l'envoi")
            resp = conn.getresponse()
            raw = resp.read()
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            raise ConnectionError(f"{self.host}:{self.port} injoignable ({exc})") from exc
        finally:
            conn.close()
            if spool:
                spool.close()
        if resp.status != 200:
            message = json.loads(raw).get("error", "") if raw else ""
            if resp.status == 423:
                raise LockLost(message or "verrou perdu")
            if resp.status == 400:
                raise SyncPathError(message or "refusé (400)")
            raise RemoteError(resp.status, message)

    def delete(self, space: str, rel: str) -> None:
        self._call("POST", "/delete", payload={"space": space, "rel": rel})

    def commit(self, space: str) -> None:
        self._call("POST", "/commit", payload={"space": space})


def pair(code_data: dict, device_id: str, name: str, my_port: int, timeout: float = TIMEOUT) -> dict:
    """Présente le code d'appairage au PC qui l'a créé ; retourne {"id","name","primary_id"}."""
    secret = code_data["secret"]
    path = "/pair"
    headers = secure.sign_headers(secret, device_id, "POST", path)
    ctx = (headers["X-Voktora-Nonce"] + path).encode()
    enc = secure.derive(secret)[1]
    blob = secure.encrypt_bytes(enc, ctx, json.dumps({"name": name, "port": my_port}).encode())
    headers["Content-Length"] = str(len(blob))
    conn = http.client.HTTPConnection(code_data["host"], code_data["port"], timeout=timeout)
    try:
        conn.request("POST", path, body=blob, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
    except (OSError, http.client.HTTPException) as exc:
        raise ConnectionError(f"{code_data['host']}:{code_data['port']} injoignable ({exc})") from exc
    finally:
        conn.close()
    if resp.status != 200:
        try:
            message = json.loads(raw).get("error", "")
        except ValueError:
            message = ""
        raise RemoteError(resp.status, message or f"HTTP {resp.status}")
    return json.loads(secure.decrypt_bytes(enc, ctx + b"R", raw))
