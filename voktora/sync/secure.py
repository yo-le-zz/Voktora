"""
Voktora — sync.secure
Authentification et chiffrement du protocole de synchronisation.

Appairage : un secret aléatoire de 32 octets est échangé via un « code d'appairage » (copié/collé par
l'utilisateur, jamais sur le réseau). Il sert à dériver deux clés distinctes (HKDF-SHA256) :
  • une clé d'authentification : chaque requête est signée en HMAC-SHA256 (méthode, chemin, horodatage,
    nonce) ; horodatage ±120 s et nonce à usage unique → pas de rejeu ;
  • une clé de chiffrement : contenu des requêtes/réponses chiffré par blocs en AES-256-GCM (confidentialité
    même sur un LAN non fiable). Chaque bloc est lié à la requête (nonce, chemin, numéro de bloc) : un bloc ne
    peut être ni rejoué, ni réordonné, ni déplacé vers une autre requête.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from collections.abc import Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CHUNK = 1 << 20
FRAME_OVERHEAD = 4 + 12 + 16
MAX_SKEW = 120.0
PAIRING_VERSION = 1


class AuthError(Exception):
    """Signature invalide, requête rejouée ou horodatage hors tolérance."""


def new_secret() -> bytes:
    return os.urandom(32)


def derive(secret: bytes) -> tuple[bytes, bytes]:
    """(clé d'authentification, clé de chiffrement) dérivées du secret d'appairage."""
    material = HKDF(algorithm=hashes.SHA256(), length=64, salt=b"voktora-sync-v1", info=b"keys").derive(secret)
    return material[:32], material[32:]


def sign(auth_key: bytes, method: str, path: str, device: str, ts: str, nonce: str) -> str:
    msg = "\n".join((method.upper(), path, device, ts, nonce)).encode()
    return hmac.new(auth_key, msg, hashlib.sha256).hexdigest()


def sign_headers(secret: bytes, device_id: str, method: str, path: str) -> dict[str, str]:
    auth_key, _ = derive(secret)
    ts, nonce = f"{time.time():.3f}", base64.urlsafe_b64encode(os.urandom(12)).decode()
    return {"X-Voktora-Device": device_id, "X-Voktora-Ts": ts, "X-Voktora-Nonce": nonce,
            "X-Voktora-Sig": sign(auth_key, method, path, device_id, ts, nonce)}


class NonceCache:
    """Mémorise les nonces récents pour refuser un rejeu."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def check(self, nonce: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        for key in [k for k, t in self._seen.items() if now - t > 2 * MAX_SKEW]:
            del self._seen[key]
        if nonce in self._seen:
            return False
        self._seen[nonce] = now
        return True


def verify_headers(secret: bytes, headers, method: str, path: str, nonces: NonceCache) -> str:
    """Vérifie une requête entrante. Retourne l'identifiant de l'appareil ou lève AuthError."""
    device, ts = headers.get("X-Voktora-Device", ""), headers.get("X-Voktora-Ts", "")
    nonce, sig = headers.get("X-Voktora-Nonce", ""), headers.get("X-Voktora-Sig", "")
    if not (device and ts and nonce and sig):
        raise AuthError("en-têtes d'authentification manquants")
    try:
        if abs(time.time() - float(ts)) > MAX_SKEW:
            raise AuthError("horloge trop différente (±2 min) : vérifiez l'heure des deux PC")
    except ValueError as exc:
        raise AuthError("horodatage invalide") from exc
    auth_key, _ = derive(secret)
    if not hmac.compare_digest(sig, sign(auth_key, method, path, device, ts, nonce)):
        raise AuthError("signature invalide (secret d'appairage différent ?)")
    if not nonces.check(nonce):
        raise AuthError("requête rejouée")
    return device


# ── Chiffrement par blocs ─────────────────────────────────────────────────────

def _aad(context: bytes, index: int) -> bytes:
    return context + struct.pack(">Q", index)


def encrypted_length(size: int) -> int:
    frames = max(1, -(-size // CHUNK))
    return size + frames * FRAME_OVERHEAD


def encrypt_stream(key: bytes, context: bytes, chunks: Iterator[bytes]) -> Iterator[bytes]:
    """Blocs [longueur][nonce][chiffré+tag]. `chunks` ≤ CHUNK octets chacun ; au moins un bloc est émis."""
    aes, emitted = AESGCM(key), False
    for index, chunk in enumerate(chunks):
        nonce = os.urandom(12)
        body = aes.encrypt(nonce, chunk, _aad(context, index))
        yield struct.pack(">I", len(body)) + nonce + body
        emitted = True
    if not emitted:
        nonce = os.urandom(12)
        body = aes.encrypt(nonce, b"", _aad(context, 0))
        yield struct.pack(">I", len(body)) + nonce + body


def decrypt_stream(key: bytes, context: bytes, read) -> Iterator[bytes]:
    """`read(n)` → exactement n octets (ou moins en fin de flux). Lève AuthError si un bloc est altéré."""
    aes, index = AESGCM(key), 0
    while True:
        head = read(4)
        if not head:
            if index == 0:
                raise AuthError("flux vide")
            return
        if len(head) < 4:
            raise AuthError("flux tronqué")
        (length,) = struct.unpack(">I", head)
        if length > CHUNK + 16:
            raise AuthError("bloc trop grand")
        nonce, body = read(12), read(length)
        if len(nonce) < 12 or len(body) < length:
            raise AuthError("flux tronqué")
        try:
            yield aes.decrypt(nonce, body, _aad(context, index))
        except InvalidTag as exc:
            raise AuthError("bloc altéré ou clé incorrecte") from exc
        index += 1


def encrypt_bytes(key: bytes, context: bytes, data: bytes) -> bytes:
    chunks = (data[i:i + CHUNK] for i in range(0, len(data), CHUNK))
    return b"".join(encrypt_stream(key, context, chunks))


def decrypt_bytes(key: bytes, context: bytes, blob: bytes) -> bytes:
    pos = 0

    def read(n: int) -> bytes:
        nonlocal pos
        out = blob[pos:pos + n]
        pos += n
        return out
    return b"".join(decrypt_stream(key, context, read))


# ── Code d'appairage ──────────────────────────────────────────────────────────

def make_pairing_code(device_id: str, name: str, host: str, port: int, secret: bytes, primary_id: str) -> str:
    payload = {"v": PAIRING_VERSION, "id": device_id, "name": name, "host": host, "port": port,
               "primary": primary_id, "secret": base64.urlsafe_b64encode(secret).decode()}
    return "VKS1-" + base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def parse_pairing_code(code: str) -> dict:
    code = code.strip()
    if not code.startswith("VKS1-"):
        raise ValueError("Code d'appairage invalide (il doit commencer par VKS1-).")
    raw = code[5:]
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        secret = base64.urlsafe_b64decode(data["secret"])
        if data.get("v") != PAIRING_VERSION or len(secret) != 32 or not data["id"] or not data["host"]:
            raise ValueError
        return {"id": str(data["id"]), "name": str(data.get("name", "")), "host": str(data["host"]),
                "port": int(data["port"]), "primary": str(data.get("primary", "")), "secret": secret}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Code d'appairage illisible ou incomplet.") from exc
