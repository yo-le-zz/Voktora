"""Client WebSocket (RFC 6455) minimal mais complet : poignée de main, trames masquées, fragmentation, ping/pong, fermeture."""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import urllib.parse

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_MESSAGE = 16 * 1024 * 1024


class WebSocketError(Exception):
    pass


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()    # noqa: S324 — imposé par la RFC 6455


def encode_frame(opcode: int, payload: bytes, mask: bool = True, fin: bool = True) -> bytes:
    head = bytes([(0x80 if fin else 0) | opcode])
    n = len(payload)
    mbit = 0x80 if mask else 0
    if n < 126:
        head += bytes([mbit | n])
    elif n < 65536:
        head += bytes([mbit | 126]) + struct.pack("!H", n)
    else:
        head += bytes([mbit | 127]) + struct.pack("!Q", n)
    if mask:
        key = os.urandom(4)
        return head + key + bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return head + payload


def read_exact(sock, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise WebSocketError("Connexion fermée.")
        buf += chunk
    return bytes(buf)


def read_frame(sock) -> tuple[bool, int, bytes]:
    b1, b2 = read_exact(sock, 2)
    fin, opcode, masked, n = bool(b1 & 0x80), b1 & 0x0F, bool(b2 & 0x80), b2 & 0x7F
    if b1 & 0x70:
        raise WebSocketError("Bits réservés non nuls.")
    if n == 126:
        n = struct.unpack("!H", read_exact(sock, 2))[0]
    elif n == 127:
        n = struct.unpack("!Q", read_exact(sock, 8))[0]
    if n > MAX_MESSAGE:
        raise WebSocketError("Trame trop grande.")
    key = read_exact(sock, 4) if masked else b""
    data = read_exact(sock, n)
    if masked:
        data = bytes(b ^ key[i % 4] for i, b in enumerate(data))
    if opcode >= 0x8 and (not fin or n > 125):
        raise WebSocketError("Trame de contrôle invalide.")
    return fin, opcode, data


class WebSocketClient:
    def __init__(self, url: str, headers: dict | None = None, timeout: float = 10.0, verify_tls: bool = True):
        self.url, self.headers, self.timeout, self.verify = url, headers or {}, timeout, verify_tls
        self.sock: socket.socket | None = None
        self.closed = False

    def connect(self) -> None:
        p = urllib.parse.urlsplit(self.url)
        if p.scheme not in ("ws", "wss") or not p.hostname:
            raise WebSocketError("Adresse invalide : ws:// ou wss:// attendu.")
        port = p.port or (443 if p.scheme == "wss" else 80)
        raw = socket.create_connection((p.hostname, port), timeout=self.timeout)
        if p.scheme == "wss":
            ctx = ssl.create_default_context()
            if not self.verify:
                ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
            raw = ctx.wrap_socket(raw, server_hostname=p.hostname)
        self.sock = raw
        key = base64.b64encode(os.urandom(16)).decode()
        path = (p.path or "/") + (("?" + p.query) if p.query else "")
        lines = [f"GET {path} HTTP/1.1", f"Host: {p.hostname}:{port}", "Upgrade: websocket", "Connection: Upgrade",
                 f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13",
                 *[f"{k}: {v}" for k, v in self.headers.items() if "\r" not in k + v and "\n" not in k + v]]
        raw.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = raw.recv(1)
            if not chunk:
                raise WebSocketError("Poignée de main interrompue.")
            data += chunk
            if len(data) > 16384:
                raise WebSocketError("Réponse de poignée de main trop longue.")
        head = data.decode("latin-1").split("\r\n")
        if " 101 " not in head[0] + " ":
            raise WebSocketError(f"Le serveur a refusé la mise à niveau : {head[0]}")
        hdr = {k.strip().lower(): v.strip() for k, _, v in (h.partition(":") for h in head[1:] if ":" in h)}
        if hdr.get("sec-websocket-accept") != accept_key(key):
            raise WebSocketError("Sec-WebSocket-Accept invalide (serveur non conforme).")

    def send_text(self, text: str) -> None:
        self._send(OP_TEXT, text.encode("utf-8"))

    def send_binary(self, data: bytes) -> None:
        self._send(OP_BIN, data)

    def ping(self, payload: bytes = b"") -> None:
        self._send(OP_PING, payload)

    def _send(self, opcode: int, payload: bytes) -> None:
        if not self.sock or self.closed:
            raise WebSocketError("Connexion fermée.")
        self.sock.sendall(encode_frame(opcode, payload, mask=True))

    def recv(self, timeout: float | None = None):
        """Retourne (type, contenu) : ("text", str) | ("binary", bytes) | ("pong", bytes) | ("close", (code, raison))."""
        if not self.sock:
            raise WebSocketError("Non connecté.")
        self.sock.settimeout(timeout if timeout is not None else self.timeout)
        message, kind = bytearray(), None
        while True:
            fin, op, data = read_frame(self.sock)
            if op == OP_PING:
                self.sock.sendall(encode_frame(OP_PONG, data))
                continue
            if op == OP_PONG:
                return "pong", data
            if op == OP_CLOSE:
                code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else 1005
                if not self.closed:
                    self.closed = True
                    try:
                        self.sock.sendall(encode_frame(OP_CLOSE, data[:2]))
                    except OSError:
                        pass
                return "close", (code, data[2:].decode("utf-8", "replace"))
            if op in (OP_TEXT, OP_BIN):
                kind = "text" if op == OP_TEXT else "binary"
            elif op != OP_CONT or kind is None:
                raise WebSocketError("Trame inattendue.")
            message += data
            if len(message) > MAX_MESSAGE:
                raise WebSocketError("Message trop grand.")
            if fin:
                return kind, message.decode("utf-8") if kind == "text" else bytes(message)

    def close(self, code: int = 1000) -> None:
        if self.sock and not self.closed:
            self.closed = True
            try:
                self.sock.sendall(encode_frame(OP_CLOSE, struct.pack("!H", code)))
            except OSError:
                pass
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
