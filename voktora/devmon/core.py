"""devmon.core — fichiers, niveaux, masquage, lecture en direct (sans Qt)."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

LEVELS = ("crash", "normal", "verbose", "trace")
RANK = {name: i for i, name in enumerate(LEVELS)}
LABELS = {
    "crash": "Plantages seulement",
    "normal": "Normal — erreurs, avertissements, fenêtres",
    "verbose": "Détaillé — + clics, menus, hooks, blocages",
    "trace": "Trace complète — + messages Qt, DEBUG, focus",
}
SEVERITIES = ("debug", "info", "warning", "error", "critical")
MAX_BYTES = 25 * 1024 * 1024
KEEP_SESSIONS = 10
MAX_MESSAGE = 4000

_SECRETS = [
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b"),
    re.compile(r"(?i)\b(bearer|token|authorization)\b(\s*[:=]\s*|\s+)([A-Za-z0-9._~+/=-]{12,})"),
    re.compile(r"(?i)(\"?(?:password|passwd|secret|api[_-]?key|token)\"?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;}]+)"),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),
]


def redact(text: str) -> str:
    """Masque jetons, clés et mots de passe courants (best effort : n'enregistrez pas de secrets dans vos messages)."""
    text = str(text)
    text = _SECRETS[0].sub("«secret»", text)
    text = _SECRETS[1].sub("«secret»", text)
    text = _SECRETS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}«secret»", text)
    text = _SECRETS[3].sub(lambda m: f"{m.group(1)}«secret»", text)
    return _SECRETS[4].sub("«identifiants»", text)


def base_dir() -> Path:
    override = os.environ.get("VOKTORA_DEVMON_DIR")
    if override:
        return Path(override)
    import core
    return core.get_data_dir() / "devmon"


def new_session(directory: Path | None = None) -> Path:
    directory = directory or base_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        directory.chmod(0o700)                      # réservé à l'utilisateur
    prune(directory)
    return directory / f"session-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.jsonl"


def crash_file(session: Path) -> Path:
    return session.with_suffix(".crash.txt")


def control_file(session: Path) -> Path:
    return session.with_suffix(".control.json")


def prune(directory: Path, keep: int = KEEP_SESSIONS) -> None:
    sessions = sorted(directory.glob("session-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in sessions[keep:]:
        for f in (old, crash_file(old), control_file(old)):
            try:
                f.unlink()
            except OSError:
                pass


def read_prefs(directory: Path | None = None) -> dict:
    try:
        data = json.loads(((directory or base_dir()) / "prefs.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_prefs(prefs: dict, directory: Path | None = None) -> None:
    directory = directory or base_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "prefs.json").write_text(json.dumps(prefs, indent=1), encoding="utf-8")


def valid_level(level, default: str = "normal") -> str:
    return level if level in RANK else default


class Codec:
    """Canal authentifié et CHIFFRÉ entre Voktora et le moniteur : AES-256-GCM, clé dérivée d'un secret partagé (32 octets
    aléatoires, créé au lancement et transmis au moniteur par un tube anonyme — jamais par un fichier, un argument ni une variable
    d'environnement). Chaque ligne est liée à la précédente (étiquette GCM chaînée + numéro) : une ligne modifiée, supprimée,
    déplacée, rejouée ou forgée sans le secret est rejetée. Limite : un processus du MÊME utilisateur capable de lire la mémoire
    de Voktora (ptrace) peut obtenir le secret."""

    def __init__(self, secret: bytes):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if len(secret) < 16:
            raise ValueError("secret trop court")
        self._lines = AESGCM(hmac.new(secret, b"voktora-devmon-lines", hashlib.sha256).digest())
        self._ctl = AESGCM(hmac.new(secret, b"voktora-devmon-control", hashlib.sha256).digest())
        self._prev = b"\0" * 16
        self._seq = 0                                 # côté lecture : prochain numéro attendu

    @staticmethod
    def _nonce(seq: int) -> bytes:
        return b"\0\0\0\0" + seq.to_bytes(8, "big")

    def encode(self, event: dict, seq: int) -> str:
        ct = self._lines.encrypt(self._nonce(seq), json.dumps(event, ensure_ascii=False, default=str).encode(),
                                 self._prev + seq.to_bytes(8, "big"))
        self._prev = ct[-16:]
        return base64.b64encode(ct).decode()

    def decode(self, line: str) -> dict | None:
        """Événement authentique, ou None (ligne rejetée : le chaînage reste inchangé)."""
        try:
            ct = base64.b64decode(line.strip(), validate=True)
            plain = self._lines.decrypt(self._nonce(self._seq + 1), ct, self._prev + (self._seq + 1).to_bytes(8, "big"))
            event = json.loads(plain.decode())
        except Exception:  # noqa: BLE001 — toute anomalie = rejet
            return None
        self._seq += 1
        self._prev = ct[-16:]
        return event if isinstance(event, dict) else None

    def seal_control(self, message: dict) -> str:
        nonce = os.urandom(12)
        return base64.b64encode(nonce + self._ctl.encrypt(nonce, json.dumps(message).encode(), b"control")).decode()

    def open_control(self, blob: str) -> dict | None:
        try:
            raw = base64.b64decode(blob.strip(), validate=True)
            data = json.loads(self._ctl.decrypt(raw[:12], raw[12:], b"control").decode())
            return data if isinstance(data, dict) else None
        except Exception:  # noqa: BLE001
            return None


def write_control(session: Path, codec: Codec, mode: str, counter: int) -> None:
    """Commande « changer de mode » envoyée par le moniteur ; le compteur croissant empêche le rejeu d'une ancienne commande."""
    path = control_file(session)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(codec.seal_control({"mode": mode, "ctr": counter}))
    os.replace(tmp, path)


def read_control(session: Path, codec: Codec, last_counter: int) -> tuple[str, int] | None:
    try:
        data = codec.open_control(control_file(session).read_text(encoding="utf-8"))
    except OSError:
        return None
    if not data or not isinstance(data.get("ctr"), int) or data["ctr"] <= last_counter or data.get("mode") not in RANK:
        return None
    return data["mode"], data["ctr"]


class Writer:
    """Ajoute des lignes JSON à un fichier : sûr entre threads, vidé à chaque ligne (un plantage ne perd rien), plafonné."""

    def __init__(self, path: Path, max_bytes: int = MAX_BYTES, codec: Codec | None = None):
        self.path, self.max_bytes, self.codec = Path(path), max_bytes, codec
        self._lock = threading.Lock()
        self._size = 0
        self._seq = 0
        self._full = False
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)       # lisible par l'utilisateur seul
        self._fh = os.fdopen(fd, "a", encoding="utf-8", buffering=1)

    def write(self, event: dict) -> None:
        with self._lock:
            if self._full:
                return
            self._seq += 1
            event = {"n": self._seq, "t": round(time.time(), 3), **event}
            line = self._line(event)
            if self._size + len(line) > self.max_bytes:
                self._full = True
                line = self._line({"n": self._seq, "t": round(time.time(), 3), "sev": "warning", "cat": "app", "src": "devmon",
                                   "msg": "Journal plein : les événements suivants ne sont plus enregistrés."})
            try:
                self._fh.write(line)
                self._size += len(line)
            except (OSError, ValueError):
                self._full = True

    def _line(self, event: dict) -> str:
        if self.codec:
            return self.codec.encode(event, self._seq) + "\n"
        return json.dumps(event, ensure_ascii=False, default=str) + "\n"

    def close(self) -> None:
        with self._lock:
            try:
                self._fh.close()
            except OSError:
                pass


def make_event(cat: str, msg: str, sev: str = "info", src: str = "voktora", data: dict | None = None) -> dict:
    ev = {"sev": sev if sev in SEVERITIES else "info", "cat": cat, "src": src, "msg": redact(str(msg))[:MAX_MESSAGE]}
    if data:
        ev["data"] = json.loads(redact(json.dumps(data, ensure_ascii=False, default=str)))
    return ev


class Tail:
    """Relit un fichier JSON Lines au fil de l'eau (ignore les lignes incomplètes et les lignes illisibles)."""

    def __init__(self, path: Path, codec: Codec | None = None):
        self.path, self.offset, self._partial, self.codec = Path(path), 0, b"", codec
        self.rejected = 0

    def read(self) -> list[dict]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.offset:                        # fichier remplacé : on repart du début
            self.offset, self._partial = 0, b""
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                chunk = fh.read(8 * 1024 * 1024)
        except OSError:
            return []
        self.offset += len(chunk)
        data = self._partial + chunk
        *lines, self._partial = data.split(b"\n")
        out = []
        for raw in lines:
            text = raw.decode("utf-8", errors="replace")
            if self.codec:
                ev = self.codec.decode(text)
                if ev is None:
                    if text.strip():
                        self.rejected += 1
                        out.append({"t": time.time(), "sev": "critical", "cat": "security", "src": "devmon",
                                    "msg": "Ligne rejetée : authentification impossible (fichier modifié ou forgé ?)."})
                    continue
            else:
                try:
                    ev = json.loads(text)
                except ValueError:
                    continue
            if isinstance(ev, dict):
                out.append(ev)
        return out


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259                                                  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # Un zombie répond à kill(0) : on vérifie /proc quand il existe.
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        return state != "Z"
    except (OSError, IndexError):
        return True


def app_state(events: list[dict], now: float, alive: bool, stale_after: float = 8.0) -> tuple[str, str]:
    """(code, texte) : running / exited / crashed / hung / waiting — d'après les événements, l'heure et l'existence du processus."""
    last_beat = None
    exit_event = None
    for ev in events:
        if ev.get("cat") == "heartbeat":
            last_beat = ev
        elif ev.get("cat") == "app" and ev.get("data", {}).get("event") == "exit":
            exit_event = ev
    if exit_event:
        code = exit_event["data"].get("code", 0)
        return ("exited", f"Voktora s'est arrêté (code {code})")
    if last_beat is None:
        return ("waiting", "En attente de Voktora…")
    pid = last_beat.get("data", {}).get("pid", 0)
    if not alive:
        return ("crashed", f"Voktora (pid {pid}) a disparu sans s'arrêter proprement : plantage probable")
    if now - last_beat["t"] > stale_after:
        return ("hung", f"Voktora (pid {pid}) ne répond plus depuis {int(now - last_beat['t'])} s")
    rss = last_beat.get("data", {}).get("rss_mb")
    return ("running", f"Voktora en marche (pid {pid}" + (f", {rss} Mo" if rss else "") + ")")
