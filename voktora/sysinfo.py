"""
Voktora — sysinfo.py (1.1.1)
État de l'ordinateur (processeur, mémoire, disques, charge, processus) pour `api.system_info()`.
Sans dépendance : lit /proc sous Linux, `psutil` s'il est installé (toutes plateformes), sinon des valeurs partielles.
Les appels sont bon marché ; le pourcentage de processeur est calculé entre deux appels successifs.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

try:                                    # facultatif
    import psutil
except ImportError:                     # pragma: no cover
    psutil = None

_lock = threading.Lock()
_last_cpu: tuple[float, list[int]] | None = None


def _proc_cpu() -> list[int] | None:
    try:
        first = Path("/proc/stat").read_text().splitlines()[0].split()
        return [int(x) for x in first[1:]]
    except (OSError, ValueError, IndexError):
        return None


def cpu_percent() -> float | None:
    """Occupation du processeur (0-100) depuis l'appel précédent (0 au tout premier appel)."""
    global _last_cpu
    if psutil is not None:
        return float(psutil.cpu_percent(interval=None))
    now = _proc_cpu()
    if now is None:
        return None
    with _lock:
        before, _last_cpu = _last_cpu, (time.time(), now)
    if before is None:
        return 0.0
    delta = [a - b for a, b in zip(now, before[1], strict=False)]
    total = sum(delta)
    idle = delta[3] + (delta[4] if len(delta) > 4 else 0)
    return round(100.0 * (total - idle) / total, 1) if total > 0 else 0.0


def memory() -> dict:
    if psutil is not None:
        m = psutil.virtual_memory()
        return {"total": m.total, "used": m.total - m.available, "percent": float(m.percent)}
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0]) * 1024
        total, avail = info["MemTotal"], info.get("MemAvailable", info["MemFree"])
        return {"total": total, "used": total - avail, "percent": round(100.0 * (total - avail) / total, 1)}
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return {"total": 0, "used": 0, "percent": 0.0}


def disks(paths: list[str] | None = None) -> list[dict]:
    out = []
    for path in paths or [str(Path.home()), "/"]:
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        out.append({"path": path, "total": usage.total, "used": usage.used, "percent": round(100.0 * usage.used / usage.total, 1)})
    return out


def snapshot(processes: int = 0) -> dict:
    """Tout d'un coup. `processes` > 0 : les N processus les plus gourmands (psutil uniquement)."""
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    data = {"cpu_percent": cpu_percent(), "cpu_count": os.cpu_count() or 1, "memory": memory(), "disks": disks(),
            "load": [round(x, 2) for x in load], "psutil": psutil is not None}
    if processes and psutil is not None:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            procs.append({k: p.info.get(k) for k in ("pid", "name", "cpu_percent", "memory_percent")})
        data["processes"] = sorted(procs, key=lambda x: -(x["cpu_percent"] or 0))[:processes]
    return data
