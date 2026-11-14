"""devmon.core — fichiers, niveaux, masquage, lecture en direct (sans Qt)."""

from __future__ import annotations

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


class Writer:
    """Ajoute des lignes JSON à un fichier : sûr entre threads, vidé à chaque ligne (un plantage ne perd rien), plafonné."""

    def __init__(self, path: Path, max_bytes: int = MAX_BYTES):
        self.path, self.max_bytes = Path(path), max_bytes
        self._lock = threading.Lock()
        self._size = 0
        self._seq = 0
        self._full = False
        self._fh = open(self.path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — fermé par close()

    def write(self, event: dict) -> None:
        with self._lock:
            if self._full:
                return
            self._seq += 1
            event = {"n": self._seq, "t": round(time.time(), 3), **event}
            line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
            if self._size + len(line) > self.max_bytes:
                self._full = True
                line = json.dumps({"n": self._seq, "t": round(time.time(), 3), "sev": "warning", "cat": "app", "src": "devmon",
                                   "msg": "Journal plein : les événements suivants ne sont plus enregistrés."}) + "\n"
            try:
                self._fh.write(line)
                self._size += len(line)
            except (OSError, ValueError):
                self._full = True

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

    def __init__(self, path: Path):
        self.path, self.offset, self._partial = Path(path), 0, b""

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
            try:
                ev = json.loads(raw.decode("utf-8", errors="replace"))
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
