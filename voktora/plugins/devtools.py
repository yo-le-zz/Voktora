"""
Voktora — plugins.devtools (1.1.1) : MODE DÉVELOPPEUR.

  • tracebacks : journal circulaire des erreurs (plugins ET Voktora), avec un rendu qui sépare « votre code » et
    « Voktora » pour que l'auteur d'un plugin voie tout de suite où ça casse ;
  • surveillance : dès qu'un fichier d'un plugin « en développement » change, il est rechargé ;
  • auto-installation : imports Python manquants → ajoutés à `requires` (et installés au rechargement par pylibs) ;
    permissions détectées → ajoutées à plugin.json si le manifeste est en liste explicite (`sync_manifest`) ;
  • validation RÉELLE : `validate(dossier)` lance le plugin dans un sous-processus isolé (dossier de données jetable,
    faux hôte graphique), appelle ses gestionnaires, le décharge, et rapporte erreurs, journaux et appels d'API.
    Python, JavaScript et Rust (la compilation Rust comprise).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_ENTRIES = 300
WATCH_SECONDS = 1.0
RUN_TIMEOUT = 1900.0
NEEDS_WINDOW = {"on_start", "on_quit", "on_close", "on_theme_changed"}
SKIP = {"__pycache__", ".git", "node_modules", "target"}

_entries: deque[dict] = deque(maxlen=MAX_ENTRIES)
_lock = threading.RLock()
_listeners: list[Callable[[dict], None]] = []
_hooks_installed = False
_previous_excepthook = sys.excepthook


# ── journal des erreurs ───────────────────────────────────────────────────────────────

def record(source: str, text: str, kind: str = "error") -> dict:
    entry = {"time": time.strftime("%H:%M:%S"), "source": source, "kind": kind, "text": text}
    with _lock:
        _entries.append(entry)
        listeners = list(_listeners)
    for listener in listeners:
        with contextlib.suppress(Exception):
            listener(entry)
    return entry


def entries(source: str | None = None) -> list[dict]:
    with _lock:
        return [e for e in _entries if source in (None, e["source"])]


def clear() -> None:
    with _lock:
        _entries.clear()


def subscribe(listener: Callable[[dict], None]) -> Callable[[], None]:
    with _lock:
        _listeners.append(listener)

    def stop() -> None:
        with _lock:
            if listener in _listeners:
                _listeners.remove(listener)
    return stop


def split_traceback(text: str, plugin_dir: Path | str | None = None) -> str:
    """Annote un traceback : « ▶ plugin » pour les lignes de votre code, « · Voktora » pour le reste."""
    marker = str(plugin_dir) if plugin_dir else ""
    out: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith('File "'):
            mine = bool(marker) and marker in line
            theirs = str(HERE.parent) in line
            out.append(("▶ " if mine else "· Voktora  " if theirs else "· ") + line.strip())
        else:
            out.append(line)
    return "\n".join(out)


def install_hooks() -> None:
    """Capture les exceptions non gérées de Voktora (principal + fils) dans le journal."""
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True

    def hook(exc_type, exc, tb):
        record("voktora", "".join(traceback.format_exception(exc_type, exc, tb)))
        _previous_excepthook(exc_type, exc, tb)

    def thread_hook(args):
        record(f"voktora/{args.thread.name if args.thread else '?'}",
               "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = hook
    threading.excepthook = thread_hook


def enable(on: bool = True) -> None:
    """Active/désactive le mode développeur : traces des plugins, tracebacks de Voktora, surveillance."""
    from . import runtime
    if on:
        install_hooks()
        runtime.set_trace_hook(lambda plugin_id, text: record(plugin_id, text))
        start_watcher()
    else:
        runtime.set_trace_hook(None)
        stop_watcher()


# ── surveillance des fichiers (rechargement automatique) ───────────────────────────────────

def snapshot(folder: Path) -> dict[str, float]:
    state: dict[str, float] = {}
    for path in Path(folder).rglob("*"):
        if path.is_file() and not SKIP & set(path.relative_to(folder).parts):
            with contextlib.suppress(OSError):
                state[str(path)] = path.stat().st_mtime
    return state


_watch_stop = threading.Event()
_watch_thread: threading.Thread | None = None


def changed_plugins(previous: dict[str, dict[str, float]]) -> list[str]:
    """Ids des plugins en développement dont un fichier a changé depuis `previous` (mis à jour en place)."""
    from . import runtime
    changed: list[str] = []
    for info in runtime.get_all():
        if not info.dev:
            continue
        state = snapshot(Path(info.path))
        if info.id in previous and state != previous[info.id]:
            changed.append(info.id)
        previous[info.id] = state
    return changed


def _reload(plugin_id: str) -> None:
    from . import runtime
    with contextlib.suppress(Exception):
        sync_manifest(runtime.plugins_dir() / plugin_id)
    try:
        info = runtime.reload_plugin(plugin_id)
    except Exception:  # noqa: BLE001
        record(plugin_id, traceback.format_exc())
        return
    if info is not None and info.error and not info.pending_libs:
        record(plugin_id, info.error)
    else:
        record(plugin_id, "rechargé", kind="info")


def start_watcher() -> None:
    global _watch_thread
    if _watch_thread is not None and _watch_thread.is_alive():
        return
    _watch_stop.clear()

    def run() -> None:
        from . import runtime
        seen: dict[str, dict[str, float]] = {}
        while not _watch_stop.wait(WATCH_SECONDS):
            for plugin_id in changed_plugins(seen):
                host = runtime.get_ui_host()
                (host.post(lambda p=plugin_id: _reload(p)) if host is not None else _reload(plugin_id))

    _watch_thread = threading.Thread(target=run, daemon=True, name="plugin-dev-watch")
    _watch_thread.start()


def stop_watcher() -> None:
    _watch_stop.set()


def set_dev(plugin_id: str, on: bool) -> bool:
    from . import runtime
    info = runtime.find(plugin_id)
    if info is None:
        return False
    info.dev = on
    return True


# ── auto-installation / manifeste ─────────────────────────────────────────────────────────

def missing_python_imports(folder: Path) -> list[str]:
    """Modules importés par le plugin qui ne sont ni la bibliothèque standard, ni Voktora, ni ses propres fichiers."""
    from . import detect, pylibs
    found = detect.detect_folder(folder, {"lang": "python"}).imports
    mine = pylibs.top_level_names(folder) | {p.stem for p in Path(folder).rglob("*.py")}
    return sorted(m for m in found if m.split(".")[0] not in mine and not pylibs.stdlib_or_installed(m.split(".")[0]))


# Nom d'import → nom du paquet PyPI, quand ils diffèrent.
PYPI = {"PIL": "pillow", "yaml": "pyyaml", "cv2": "opencv-python-headless", "bs4": "beautifulsoup4",
        "sklearn": "scikit-learn", "dateutil": "python-dateutil", "serial": "pyserial", "git": "gitpython"}


def sync_manifest(folder: Path, *, install_missing: bool = True) -> dict:
    """Met plugin.json d'aplomb d'après le code : permissions manquantes ajoutées (manifeste explicite),
    bibliothèques manquantes ajoutées à `requires`. Retourne {"permissions": [...], "requires": [...]} (ajouts)."""
    from . import detect
    folder = Path(folder)
    path = folder / "plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    added: dict[str, list[str]] = {"permissions": [], "requires": []}
    if data.get("permissions") not in ("auto", None):
        missing = detect.missing_permissions(folder, list(data["permissions"]), data)
        if missing:
            data["permissions"] = sorted({*data["permissions"], *missing})
            added["permissions"] = sorted(missing)
    if install_missing and data.get("lang", "python") == "python":
        wanted = {r.split("[")[0].split("=")[0].split("<")[0].split(">")[0].split("~")[0].strip().lower()
                  for r in data.get("requires", [])}
        for module in missing_python_imports(folder):
            package = PYPI.get(module.split(".")[0], module.split(".")[0])
            if package.lower() not in wanted:
                data.setdefault("requires", []).append(package)
                added["requires"].append(package)
    if any(added.values()):
        if added["requires"] and "libs" not in (data.get("permissions") or []) and data.get("permissions") != "auto":
            data["permissions"] = sorted({*data["permissions"], "libs"})
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return added


# ── validation réelle ───────────────────────────────────────────────────────────────────

def validate(folder: Path, *, run: bool = True, timeout: float = RUN_TIMEOUT) -> dict:
    """{"ok", "errors": [...], "warnings": [...], "logs": [...], "detected": {perm: raisons}, "runtime": {...}}."""
    from . import detect, manifest
    folder = Path(folder)
    result: dict = {"ok": False, "errors": [], "warnings": [], "logs": [], "detected": {}, "runtime": {}}
    try:
        man = manifest.load(folder)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"plugin.json : {exc}")
        return result
    raw = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
    found = detect.detect_folder(folder, raw)
    result["detected"] = {p: found.reasons.get(p, []) for p in sorted(found.permissions)}
    result["warnings"] += list(found.warnings)
    declared = raw.get("permissions")
    if declared not in ("auto", None):
        for perm, reasons in detect.missing_permissions(folder, list(declared), raw).items():
            result["errors"].append(f"permission « {perm} » utilisée mais non déclarée ({'; '.join(reasons[:2])})")
        for perm in detect.unused_permissions(folder, list(declared), raw):
            result["warnings"].append(f"permission « {perm} » déclarée mais inutilisée")
    del man
    if raw.get("lang", "python") == "python":
        for module in missing_python_imports(folder):
            result["warnings"].append(f"module « {module} » introuvable : ajoutez-le à « requires » (sync_manifest le fait)")
    if run and not result["errors"]:
        result["runtime"] = run_in_subprocess(folder, timeout)
        result["errors"] += result["runtime"].get("errors", [])
        result["logs"] = result["runtime"].get("logs", [])
    result["ok"] = not result["errors"]
    return result


def run_in_subprocess(folder: Path, timeout: float = RUN_TIMEOUT) -> dict:
    scratch = Path(tempfile.mkdtemp(prefix="voktora-validate-"))
    try:
        boot = f"import sys; sys.path.insert(0, {str(HERE.parent)!r}); from plugins import devtools; devtools.child_main()"
        command = [sys.executable, "-c", boot, str(Path(folder).resolve()), str(scratch)]
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR",
                                                           "CARGO_HOME", "RUSTUP_HOME", "PYTHONPATH", "VIRTUAL_ENV", "LD_LIBRARY_PATH", "HTTPS_PROXY", "HTTP_PROXY",
                                                           "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "QT_QPA_PLATFORM"}}
        env["VOKTORA_NO_NATIVE"] = "1"
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env, encoding="utf-8",  # noqa: S603
                                  errors="replace", check=False)
        except subprocess.TimeoutExpired:
            return {"errors": [f"Le plugin n'a pas terminé en {int(timeout)} s (boucle infinie ?)."], "logs": []}
        for line in reversed((done.stdout or "").splitlines()):
            if line.startswith("@@RESULT@@"):
                return json.loads(line[len("@@RESULT@@"):])
        return {"errors": ["Validation interrompue :\n" + ((done.stderr or done.stdout or "")[-1500:])], "logs": []}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


class _QuietHost:
    """Faux hôte graphique pour la validation : accepte tout, ne montre rien, exécute tout de suite."""
    window = None

    def __init__(self) -> None:
        self.calls: list[str] = []

    def post(self, fn):
        fn()

    def confirm(self, *_a, **_k):
        return True

    def current_project(self):
        return None

    def log(self, *_a):
        pass

    def __getattr__(self, name):
        def noop(*_a, **_k):
            self.calls.append(name)
        return noop


def _copy_dependencies(folder: Path, destination: Path, seen: set[str] | None = None) -> None:
    """Copie (récursivement) les plugins dont dépend `folder`, cherchés à côté de lui puis dans marketplace/plugins."""
    seen = seen if seen is not None else set()
    try:
        wanted = json.loads((folder / "plugin.json").read_text(encoding="utf-8")).get("dependencies", {})
    except (OSError, ValueError):
        return
    roots = [folder.parent, HERE.parents[2] / "marketplace" / "plugins", Path.cwd() / "marketplace" / "plugins"]
    for dep in wanted:
        if dep in seen:
            continue
        seen.add(dep)
        source = next((r / dep for r in roots if (r / dep / "plugin.json").is_file()), None)
        if source is not None:
            shutil.copytree(source, destination / dep, ignore=shutil.ignore_patterns(*SKIP), dirs_exist_ok=True)
            _copy_dependencies(source, destination, seen)


def _child(folder: str, scratch: str) -> dict:
    """Exécuté DANS le sous-processus : charge réellement le plugin dans un environnement jetable."""
    import core

    from plugins import runtime
    data = Path(scratch) / "data"
    data.mkdir()
    core.paths.get_app_dir.cache_clear()
    core.paths.get_data_dir = lambda: data
    core.paths.get_config_path = lambda: data / core.constants.CONFIG_FILENAME
    core.config_store._config_cache = None
    plugin_id = json.loads((Path(folder) / "plugin.json").read_text(encoding="utf-8"))["id"]
    target = runtime.plugins_dir() / plugin_id
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(folder, target, ignore=shutil.ignore_patterns(*SKIP))
    _copy_dependencies(Path(folder), runtime.plugins_dir())
    host = _QuietHost()
    runtime.set_ui_host(host)
    out: dict = {"errors": [], "logs": [], "api_calls": []}
    runtime.load_all()
    info = runtime.find(plugin_id)
    if info is None:
        out["errors"].append("Le plugin n'a pas été trouvé après copie (manifeste invalide ?).")
        return out
    deadline = time.time() + RUN_TIMEOUT - 60
    while info.pending_libs and time.time() < deadline:
        time.sleep(0.3)
    if info.error:
        out["errors"].append(split_traceback(info.error, target))
    elif not info.loaded:
        out["errors"].append("Le plugin ne s'est pas chargé (désactivé ou dépendance manquante).")
    else:
        for hook_name in sorted(info.hooks):                  # chaque événement écouté reçoit un appel d'essai
            if hook_name in NEEDS_WINDOW:                       # le faux hôte n'a pas de vraie fenêtre
                continue
            with contextlib.suppress(Exception):
                runtime.fire_hook(hook_name, target)
        for command in info.commands:
            out["api_calls"].append(f"commande : {getattr(command, 'name', command)}")
        for message in info.errors:
            out["errors"].append(split_traceback(message, target))
        runtime.set_enabled(plugin_id, False)                  # exerce aussi on_unload
        if info.error:
            out["errors"].append("à la fermeture : " + split_traceback(info.error, target))
    out["logs"] = list(info.logs)[-100:]
    out["api_calls"] += host.calls[:200]
    return out


def child_main() -> None:
    try:
        outcome = _child(sys.argv[1], sys.argv[2])
    except Exception:  # noqa: BLE001
        outcome = {"errors": [traceback.format_exc()], "logs": []}
    sys.stdout.write("\n@@RESULT@@" + json.dumps(outcome) + "\n")
    sys.stdout.flush()
    os._exit(0)           # ne pas attendre d'éventuels fils (minuteries de plugin)
