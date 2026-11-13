"""Déclencheurs : démarrage, ouverture de projet, fichiers, HEAD Git, GitHub, HTTP entrant (jeton obligatoire, 127.0.0.1), intervalles, cron.

Les déclencheurs « sondés » (fichiers, git, github, intervalle, cron) avancent par `tick(now)` ; l'horloge est injectable."""

from __future__ import annotations

import fnmatch
import hmac
import json
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import cron

MIN_TOKEN = 16
MAX_BODY = 1_000_000


class TriggerError(Exception):
    pass


def snapshot(root: str, pattern: str, limit: int = 5000) -> dict[str, float]:
    out: dict[str, float] = {}
    for dp, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "target")]
        for f in files:
            rel = os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(f, pattern):
                try:
                    out[rel] = os.stat(os.path.join(dp, f)).st_mtime
                except OSError:
                    continue
                if len(out) >= limit:
                    return out
    return out


class Manager:
    """`fire(workflow_id, payload)` est appelé lorsqu'un déclencheur se produit. `git_head(project)` et `github_latest(repo)` sont injectables."""

    def __init__(self, fire, project: str = "", git_head=None, github_latest=None, clock=time.time):
        self.fire, self.project, self.clock = fire, project, clock
        self.git_head, self.github_latest = git_head, github_latest
        self.entries: list[dict] = []
        self.servers: dict[int, ThreadingHTTPServer] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- enregistrement -----------------------------------------------------------------------
    def register(self, wf_id: str, trig: dict) -> None:
        kind = trig.get("kind")
        e = {"wf": wf_id, "t": dict(trig), "last": self.clock(), "state": None, "last_minute": None}
        if kind == "cron":
            cron.parse(trig.get("expr", ""))
        elif kind == "interval":
            if float(trig.get("seconds", 0)) < 1:
                raise TriggerError("Intervalle : au moins 1 seconde.")
        elif kind == "file_change":
            if not trig.get("pattern"):
                raise TriggerError("Motif requis.")
            e["state"] = snapshot(self.project, trig["pattern"])
        elif kind == "git_head":
            e["state"] = self.git_head(self.project) if self.git_head else None
        elif kind == "github_poll":
            e["state"] = self.github_latest(trig.get("repo", "")) if self.github_latest else None
        elif kind == "http_in":
            self._start_http(e)
        elif kind not in ("manual", "on_start", "on_open"):
            raise TriggerError(f"Déclencheur inconnu : {kind}")
        self.entries.append(e)

    def clear(self) -> None:
        self.stop()
        self.entries.clear()

    def event(self, kind: str, payload: dict | None = None) -> int:
        """Événements applicatifs : `on_start`, `on_open`."""
        n = 0
        for e in self.entries:
            if e["t"]["kind"] == kind:
                self.fire(e["wf"], {"kind": kind, **(payload or {})})
                n += 1
        return n

    # -- sondage ----------------------------------------------------------------------------------
    def tick(self, now: float | None = None) -> int:
        now = self.clock() if now is None else now
        fired = 0
        for e in self.entries:
            kind, t = e["t"]["kind"], e["t"]
            try:
                if kind == "interval" and now - e["last"] >= float(t["seconds"]):
                    e["last"] = now
                    self.fire(e["wf"], {"kind": kind, "time": now})
                    fired += 1
                elif kind == "cron":
                    dt = datetime.fromtimestamp(now)
                    minute = (dt.year, dt.month, dt.day, dt.hour, dt.minute)
                    if minute != e["last_minute"] and cron.matches(t["expr"], dt):
                        e["last_minute"] = minute
                        self.fire(e["wf"], {"kind": kind, "time": now})
                        fired += 1
                elif kind == "file_change" and now - e["last"] >= float(t.get("every", 2)):
                    e["last"] = now
                    snap = snapshot(self.project, t["pattern"])
                    old = e["state"] or {}
                    added = sorted(set(snap) - set(old))
                    removed = sorted(set(old) - set(snap))
                    changed = sorted(f for f in snap if f in old and snap[f] != old[f])
                    e["state"] = snap
                    if added or removed or changed:
                        self.fire(e["wf"], {"kind": kind, "added": added, "removed": removed, "changed": changed})
                        fired += 1
                elif kind == "git_head" and self.git_head and now - e["last"] >= float(t.get("every", 5)):
                    e["last"] = now
                    head = self.git_head(self.project)
                    if head and e["state"] and head != e["state"]:
                        self.fire(e["wf"], {"kind": kind, "old": e["state"], "new": head})
                        fired += 1
                    e["state"] = head or e["state"]
                elif kind == "github_poll" and self.github_latest and now - e["last"] >= float(t.get("every", 60)):
                    e["last"] = now
                    latest = self.github_latest(t.get("repo", ""))
                    if latest and e["state"] and latest != e["state"]:
                        self.fire(e["wf"], {"kind": kind, "old": e["state"], "new": latest, "repo": t.get("repo", "")})
                        fired += 1
                    e["state"] = latest or e["state"]
            except (OSError, ValueError, KeyError):
                continue
        return fired

    def start(self, every: float = 1.0) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.wait(every):
                self.tick()
        self._thread = threading.Thread(target=loop, daemon=True, name="workflow-forge-triggers")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        for srv in list(self.servers.values()):
            srv.shutdown()
            srv.server_close()
        self.servers.clear()

    # -- HTTP entrant ---------------------------------------------------------------------------------
    def _start_http(self, e: dict) -> None:
        t = e["t"]
        token = str(t.get("token", ""))
        if len(token) < MIN_TOKEN:
            raise TriggerError(f"HTTP entrant : un jeton d'au moins {MIN_TOKEN} caractères est obligatoire.")
        path = t.get("path", "/hook")
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):  # noqa: N802
                given = self.headers.get("X-Voktora-Token", "")
                if not hmac.compare_digest(given.encode(), token.encode()):
                    return self._reply(401, {"error": "jeton invalide"})
                if self.path.split("?")[0] != path:
                    return self._reply(404, {"error": "inconnu"})
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    return self._reply(413, {"error": "corps trop grand"})
                raw = self.rfile.read(n).decode("utf-8", "replace") if n else ""
                try:
                    body = json.loads(raw) if raw else {}
                except ValueError:
                    body = {"raw": raw}
                outer.fire(e["wf"], {"kind": "http_in", "body": body})
                return self._reply(202, {"accepted": True})

            do_GET = do_PUT = do_DELETE = lambda self: self._reply(405, {"error": "POST uniquement"})  # noqa: E731

        srv = ThreadingHTTPServer(("127.0.0.1", int(t.get("port", 0))), H)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True, name="workflow-forge-http").start()
        t["port"] = srv.server_address[1]
        self.servers[t["port"]] = srv
