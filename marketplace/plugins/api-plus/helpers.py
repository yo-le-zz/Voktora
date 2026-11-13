"""Fonctions utilitaires d'API Plus (Python pur, testables seules)."""

import json
import threading
import time
import unicodedata


def fmt_bytes(n: float) -> str:
    units = ["o", "Ko", "Mo", "Go", "To"]
    n = float(n)
    for unit in units:
        if abs(n) < 1024 or unit == units[-1]:
            return f"{int(n)} {unit}" if unit == "o" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return ""


def fmt_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    if h:
        return f"{h} h {m:02d} min"
    return f"{m} min {sec:02d} s" if m else f"{sec} s"


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "-".join("".join(c.lower() if c.isalnum() else " " for c in plain).split())


def debounce(fn, delay: float):
    """Retarde `fn` : seul le dernier appel d'une rafale est exécuté, `delay` secondes après."""
    timer: list[threading.Timer | None] = [None]
    lock = threading.Lock()

    def wrapper(*args, **kwargs):
        with lock:
            if timer[0] is not None:
                timer[0].cancel()
            timer[0] = threading.Timer(delay, fn, args, kwargs)
            timer[0].daemon = True
            timer[0].start()
    return wrapper


class Store(dict):
    """dict persistant dans les données privées du plugin : `s = Store(api, "x.json"); s["a"] = 1; s.save()`."""

    def __init__(self, api, name: str):
        super().__init__()
        self._api, self._name = api, name
        try:
            self.update(json.loads(api.read_text(name, "{}") or "{}"))
        except ValueError:
            pass

    def save(self) -> None:
        self._api.write_text(self._name, json.dumps(self, ensure_ascii=False, indent=1))


class Cache:
    def __init__(self, ttl: float = 60.0):
        self.ttl, self._data = ttl, {}

    def get(self, key, compute):
        hit = self._data.get(key)
        if hit and time.time() - hit[0] < self.ttl:
            return hit[1]
        value = compute()
        self._data[key] = (time.time(), value)
        return value

    def clear(self) -> None:
        self._data.clear()


class Bus:
    """Bus d'événements : `bus.on("x", fn)` ; `bus.emit("x", 1)`. Les erreurs d'un abonné n'arrêtent pas les autres."""

    def __init__(self):
        self._subs: dict[str, list] = {}

    def on(self, name, fn):
        self._subs.setdefault(name, []).append(fn)
        return lambda: self._subs.get(name, []).remove(fn) if fn in self._subs.get(name, []) else None

    def emit(self, name, *args):
        for fn in list(self._subs.get(name, [])):
            try:
                fn(*args)
            except Exception:  # noqa: BLE001
                pass
