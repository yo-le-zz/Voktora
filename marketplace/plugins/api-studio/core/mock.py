"""Serveur de simulation (mock) HTTP + WebSocket d'écho, uniquement sur 127.0.0.1."""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import variables
from .websocket import OP_CLOSE, OP_PING, OP_PONG, OP_TEXT, WebSocketError, accept_key, encode_frame, read_frame


def compile_path(path: str):
    regex = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", r"(?P<\1>[^/]+)", re.escape(path).replace(r"\{", "{").replace(r"\}", "}"))
    return re.compile("^" + regex + "$")


class MockServer:
    """`routes` : [{"method","path","status","headers":{},"body":"…{{id}}…","delay_ms":0}]. Les `{param}` du chemin alimentent `{{param}}`."""

    def __init__(self, routes: list[dict], port: int = 0, ws_echo_path: str = "/ws"):
        self.routes = [{**r, "_re": compile_path(r["path"])} for r in routes]
        self.hits: list[dict] = []
        self.ws_path = ws_echo_path
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _handle(self):
                path, _, query = self.path.partition("?")
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(min(length, 5_000_000)).decode("utf-8", "replace") if length else ""
                if outer.ws_path and path == outer.ws_path and self.headers.get("Upgrade", "").lower() == "websocket" and self.command == "GET":
                    return outer._websocket(self)
                outer.hits.append({"method": self.command, "path": path, "query": query, "body": body, "time": time.time()})
                for r in outer.routes:
                    if r["method"].upper() in (self.command, "*"):
                        m = r["_re"].match(path)
                        if m:
                            if r.get("delay_ms"):
                                time.sleep(min(int(r["delay_ms"]), 10000) / 1000)
                            text, _ = variables.substitute(str(r.get("body", "")), m.groupdict(), {"method": self.command, "query": query, "request_body": body})
                            data = text.encode("utf-8")
                            self.send_response(int(r.get("status", 200)))
                            hdrs = {"Content-Type": "application/json", **r.get("headers", {})}
                            for k, v in hdrs.items():
                                self.send_header(k, v)
                            self.send_header("Content-Length", str(len(data)))
                            self.end_headers()
                            if self.command != "HEAD":
                                self.wfile.write(data)
                            return None
                data = json.dumps({"error": "aucune route simulée", "path": path}).encode()
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return None

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _handle

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread: threading.Thread | None = None

    def _websocket(self, h) -> None:
        key = h.headers.get("Sec-WebSocket-Key", "")
        h.send_response(101, "Switching Protocols")
        h.send_header("Upgrade", "websocket")
        h.send_header("Connection", "Upgrade")
        h.send_header("Sec-WebSocket-Accept", accept_key(key))
        h.end_headers()
        sock = h.connection
        sock.settimeout(30)
        try:
            while True:
                fin, op, data = read_frame(sock)
                if op == OP_CLOSE:
                    sock.sendall(encode_frame(OP_CLOSE, data[:2], mask=False))
                    return
                if op == OP_PING:
                    sock.sendall(encode_frame(OP_PONG, data, mask=False))
                elif op in (OP_TEXT, 0x2):
                    self.hits.append({"method": "WS", "path": self.ws_path, "body": data.decode("utf-8", "replace"), "time": time.time()})
                    sock.sendall(encode_frame(op, data, mask=False))
        except (WebSocketError, OSError):
            return

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> MockServer:
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="api-studio-mock")
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
