"""Chaque outil : fonction (texte, options) → texte. Pur Python, sans interface : testable seul."""

import base64
import hashlib
import json
import re
import secrets
import string
import time
import urllib.parse
import uuid
from datetime import UTC, datetime


def b64(text, o):
    text = text.strip()
    try:
        return base64.b64decode(text, validate=True).decode("utf-8")
    except Exception:  # noqa: BLE001
        return base64.b64encode(text.encode("utf-8")).decode()


def make_uuid(text, o):
    n = max(1, min(100, int(text.strip() or 1))) if text.strip().isdigit() else 1
    return "\n".join(str(uuid.uuid4()) for _ in range(n))


def timestamp(text, o):
    t = text.strip()
    if not t:
        t = str(int(time.time()))
    if re.fullmatch(r"-?\d+(\.\d+)?", t):
        v = float(t)
        v = v / 1000 if abs(v) > 1e11 else v
        return datetime.fromtimestamp(v, UTC).isoformat()
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return str(int(dt.timestamp()))


def pretty_json(text, o):
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False, sort_keys=False)
    except ValueError as exc:
        return f"JSON invalide : {exc}"


def hashes(text, o):
    raw = text.encode("utf-8")
    return "\n".join(f"{name:<7} {hashlib.new(name, raw).hexdigest()}" for name in ("md5", "sha1", "sha256", "sha512"))


def url_codec(text, o):
    return urllib.parse.unquote(text) if "%" in text else urllib.parse.quote(text, safe="")


def password(text, o):
    length = int(text) if text.strip().isdigit() else o.get("pw_length", 20)
    alphabet = string.ascii_letters + string.digits + (string.punctuation if o.get("pw_symbols", True) else "")
    return "".join(secrets.choice(alphabet) for _ in range(max(4, min(256, length))))


TOOLS = {
    "Base64": b64, "UUID": make_uuid, "Horodatage": timestamp, "JSON": pretty_json,
    "Hachages": hashes, "URL": url_codec, "Mot de passe": password,
}
