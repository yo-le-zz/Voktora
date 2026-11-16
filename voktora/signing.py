"""
Voktora — signing (1.1.4) : signature Ed25519 de l'index du marketplace.

L'index (index.json) contient les SHA-256 de tous les fichiers des plugins : le signer protège donc tout le catalogue.
  • clés de confiance : fichier `trusted_keys.json` (copié à côté de l'exécutable par les scripts de build) + réglage `marketplace.trusted_keys` ;
  • si au moins une clé est configurée, un index sans signature valide est REFUSÉ (réglage `marketplace.allow_unsigned` pour passer outre) ;
  • sans clé configurée, comportement inchangé (non signé) et l'état « non signé » est signalé.
Génération des clés et signature : `python tools/sign_index.py keygen|sign|verify` (la clé privée reste chez le mainteneur / dans un
secret CI, jamais dans le dépôt).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

SIG_NAME = "index.json.sig"


class SignatureError(ValueError):
    pass


KEYS_FILE = "trusted_keys.json"


def keys_file() -> Path:
    """Fichier recensant les clés publiques de confiance (à côté de l'application : copié par les scripts de build)."""
    try:
        import core
        candidate = core.get_app_dir() / KEYS_FILE
        if candidate.is_file():
            return candidate
    except Exception:  # noqa: BLE001
        pass
    return Path(__file__).resolve().parent / KEYS_FILE


def load_keys_file(path: Path | None = None) -> list[str]:
    """Clés publiques (hex, 64 caractères) listées dans trusted_keys.json : {"keys": [{"key": "…", "owner": "…"}]}."""
    try:
        data = json.loads((path or keys_file()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = data.get("keys", []) if isinstance(data, dict) else []
    return [e["key"] for e in entries if isinstance(e, dict) and isinstance(e.get("key"), str)]


def trusted_keys(extra: list[str] | None = None) -> list[str]:
    keys = [*load_keys_file(), *[k for k in (extra or []) if isinstance(k, str)]]
    return [k.strip().lower() for k in dict.fromkeys(keys) if isinstance(k, str) and len(k.strip()) == 64]


def verify(data: bytes, signature_b64: bytes | str, public_keys: list[str]) -> str:
    """Renvoie la clé publique (hex) qui a signé `data`, ou lève SignatureError."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        sig = base64.b64decode(signature_b64.strip() if isinstance(signature_b64, bytes | str) else b"", validate=True)
    except ValueError as exc:
        raise SignatureError("signature illisible") from exc
    for key in public_keys:
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(key)).verify(sig, data)
            return key
        except (InvalidSignature, ValueError):
            continue
    raise SignatureError("signature invalide : l'index n'a pas été signé par une clé de confiance")


def generate_keypair() -> tuple[str, str]:
    """(clé privée hex, clé publique hex)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return raw.hex(), pub.hex()


def sign(data: bytes, private_hex: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return base64.b64encode(Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex)).sign(data)).decode()
