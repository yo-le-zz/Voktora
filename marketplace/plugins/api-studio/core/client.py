"""Client HTTP complet (http.client) : toutes méthodes, en-têtes, corps JSON/XML/texte/formulaire/multipart, cookies, redirections."""

from __future__ import annotations

import http.client
import http.cookiejar
import json
import ssl
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field

from . import auth as auth_mod
from . import variables
from .model import Request, kv

MAX_BODY = 20 * 1024 * 1024
CT = {"json": "application/json", "text": "text/plain; charset=utf-8", "xml": "application/xml", "form": "application/x-www-form-urlencoded"}


@dataclass
class Response:
    status: int = 0
    reason: str = ""
    headers: list = field(default_factory=list)
    body: bytes = b""
    seconds: float = 0.0
    url: str = ""
    error: str = ""
    redirects: list = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def header(self, name: str) -> str:
        n = name.lower()
        return next((v for k, v in self.headers if k.lower() == n), "")

    def json(self):
        return json.loads(self.text)

    @property
    def ok(self) -> bool:
        return not self.error and 200 <= self.status < 400


def multipart(fields: list[dict]) -> tuple[bytes, str]:
    boundary = "----voktora" + uuid.uuid4().hex
    out = bytearray()
    for f in fields:
        name = f["key"].replace('"', "%22")
        if f.get("file"):
            with open(f["file"], "rb") as fh:
                data = fh.read()
            filename = f["file"].replace("\\", "/").rsplit("/", 1)[-1].replace('"', "%22")
            out += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n"
        else:
            out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{f.get("value", "")}\r\n'.encode()
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def prepare(req: Request, *scopes: dict) -> dict:
    """Résout les variables et construit la requête concrète. Retourne dict(method,url,headers,body) + `missing`."""
    missing: list[str] = []

    def sub(t):
        out, miss = variables.substitute(t, *scopes)
        missing.extend(miss)
        return out
    url = sub(req.url)
    params = [(sub(k), sub(v)) for k, v in kv(req.params)]
    headers = [(sub(k), sub(v)) for k, v in kv(req.headers)]
    a = {k: sub(v) if isinstance(v, str) else v for k, v in req.auth.items()}
    auth_mod.apply(a, headers, params)
    if params:
        parts = urllib.parse.urlsplit(url)
        q = urllib.parse.urlencode(params)
        url = urllib.parse.urlunsplit(parts._replace(query=(parts.query + "&" + q) if parts.query else q))
    body: bytes | None = None
    ctype = ""
    if req.body_type in ("json", "text", "xml"):
        body, ctype = sub(req.body).encode("utf-8"), CT[req.body_type]
    elif req.body_type == "form":
        body = urllib.parse.urlencode([(sub(f["key"]), sub(f.get("value", ""))) for f in req.body_fields if f.get("key")]).encode()
        ctype = CT["form"]
    elif req.body_type == "multipart":
        body, ctype = multipart([{**f, "key": sub(f["key"]), "value": sub(f.get("value", ""))} for f in req.body_fields if f.get("key")])
    names = {k.lower() for k, _ in headers}
    if ctype and "content-type" not in names:
        headers.append(("Content-Type", ctype))
    if "user-agent" not in names:
        headers.append(("User-Agent", "Voktora-API-Studio/1.0"))
    return {"method": req.method.upper(), "url": url, "headers": headers, "body": body, "missing": list(dict.fromkeys(missing))}


def _origin(url: str):
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Adresse invalide : http:// ou https:// attendu.")
    return p


def send(prepared: dict, timeout: float = 30.0, follow: bool = True, jar: http.cookiejar.CookieJar | None = None,
         verify_tls: bool = True) -> Response:
    method, url, headers, body = prepared["method"], prepared["url"], list(prepared["headers"]), prepared["body"]
    start = time.monotonic()
    resp = Response(url=url)
    ctx = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()   # noqa: S323 — choix explicite de l'utilisateur
    try:
        for hop in range(6):
            p = _origin(url)
            conn_cls = http.client.HTTPSConnection if p.scheme == "https" else http.client.HTTPConnection
            kw = {"context": ctx} if p.scheme == "https" else {}
            conn = conn_cls(p.hostname, p.port, timeout=timeout, **kw)
            hdrs = [(k, v) for k, v in headers if k.lower() != "cookie"] if hop else list(headers)
            if jar is not None:
                req0 = urllib.request.Request(url)
                jar.add_cookie_header(req0)
                ck = req0.get_header("Cookie")
                if ck and not any(k.lower() == "cookie" for k, _ in hdrs):
                    hdrs.append(("Cookie", ck))
            target = (p.path or "/") + (("?" + p.query) if p.query else "")
            try:
                conn.putrequest(method, target, skip_host=any(k.lower() == "host" for k, _ in hdrs), skip_accept_encoding=True)
                for k, v in hdrs:
                    conn.putheader(k, v)
                if body is not None:
                    conn.putheader("Content-Length", str(len(body)))
                conn.endheaders(body)
                r = conn.getresponse()
                data = r.read(MAX_BODY + 1)
                if len(data) > MAX_BODY:
                    resp.error = f"Réponse trop grande (> {MAX_BODY // 1048576} Mo) : tronquée."
                    data = data[:MAX_BODY]
                resp.status, resp.reason, resp.headers, resp.body, resp.url = r.status, r.reason, r.getheaders(), data, url
                if jar is not None:
                    class _R:
                        def __init__(self, h):
                            self.h = h

                        def info(self):
                            return self.h
                    jar.extract_cookies(_R(r.msg), urllib.request.Request(url))
            finally:
                conn.close()
            loc = resp.header("Location")
            if follow and resp.status in (301, 302, 303, 307, 308) and loc:
                resp.redirects.append({"status": resp.status, "to": loc})
                url = urllib.parse.urljoin(url, loc)
                if resp.status == 303 or (resp.status in (301, 302) and method == "POST"):
                    method, body = ("GET" if method != "HEAD" else "HEAD"), None
                    headers = [(k, v) for k, v in headers if k.lower() not in ("content-type", "content-length")]
                continue
            break
        else:
            resp.error = "Trop de redirections."
    except (OSError, http.client.HTTPException, ValueError) as exc:
        resp.error = f"{type(exc).__name__}: {exc}"
    resp.seconds = round(time.monotonic() - start, 4)
    return resp
