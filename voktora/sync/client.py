"""
Voktora — sync.client
Accès à un pair : même interface que `LocalStore` (spaces/manifest/open_reader/write/delete/commit) mais via le
protocole signé + chiffré du serveur. Les erreurs réseau deviennent `ConnectionError` (le moteur les traite
comme « pair éteint » et reprendra plus tard).
"""

from __future__ import annotations

import http.client
import json
import urllib.parse
from collections.abc import Iterator

from . import secure
from .store import Entry, SyncPathError

TIMEOUT = 20.0


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
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            conn.close()
            raise ConnectionError(f"{self.host}:{self.port} injoignable ({exc})") from exc
        return conn, resp, ctx

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
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
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
            raise RemoteError(resp.status, message or f"HTTP {resp.status}")
        try:
            return json.loads(secure.decrypt_bytes(self._enc, ctx + b"R", raw))
        except (secure.AuthError, ValueError) as exc:
            raise RemoteError(502, "réponse invalide ou altérée") from exc

    # ── appairage / état ─────────────────────────────────────────────────────

    def hello(self) -> dict:
        return self._call("GET", "/hello")

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
        return list(self._call("GET", "/spaces")["spaces"])

    def manifest(self, space: str) -> dict[str, Entry]:
        files = self._call("GET", "/manifest", {"space": space})["files"]
        return {rel: Entry(v[0], int(v[1]), int(v[2])) for rel, v in files.items()}

    def open_reader(self, space: str, rel: str) -> tuple[int, Iterator[bytes]]:
        path = "/file?" + urllib.parse.urlencode({"space": space, "rel": rel})
        conn, resp, ctx = self._request("GET", "/file", {"space": space, "rel": rel})
        if resp.status != 200:
            raw = resp.read()
            conn.close()
            if resp.status == 400:
                raise SyncPathError(json.loads(raw).get("error", "refusé"))
            raise RemoteError(resp.status, raw[:200].decode("utf-8", "replace"))
        size = int(resp.getheader("X-Voktora-Size", "0"))
        enc = self._enc

        def stream() -> Iterator[bytes]:
            try:
                yield from secure.decrypt_stream(enc, ctx, resp.read)
            except (OSError, http.client.HTTPException) as exc:
                raise ConnectionError(str(exc)) from exc
            except secure.AuthError as exc:
                raise ConnectionError(f"flux interrompu ou altéré ({exc})") from exc
            finally:
                conn.close()
        del path
        return size, stream()

    def write(self, space: str, rel: str, size: int, chunks, mode: int = 0, sha: str = "") -> None:
        params = {"space": space, "rel": rel, "mode": mode, "sha": sha}
        path = "/file?" + urllib.parse.urlencode(params)
        headers = secure.sign_headers(self.secret, self.device_id, "PUT", path)
        ctx = (headers["X-Voktora-Nonce"] + path).encode()
        headers["Content-Length"] = str(secure.encrypted_length(size))
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
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
        if resp.status != 200:
            message = json.loads(raw).get("error", "") if raw else ""
            if resp.status in (400, 423):
                raise SyncPathError(message or f"refusé ({resp.status})")
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
