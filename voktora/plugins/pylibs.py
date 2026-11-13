"""
Voktora — plugins.pylibs (1.1.1)
Bibliothèques Python EXTERNES propres à chaque plugin.

  • `plugin.json` : `"requires": ["rich>=13", "pyyaml==6.0.2"]` (permission « libs », détectée automatiquement) ;
  • installées dans `plugins_data/<id>/libs/` (jamais dans l'environnement de Voktora ni dans celui d'un autre
    plugin) avec `uv pip install --target` ou, à défaut, `python -m pip install --target` ;
  • roues binaires uniquement (`--only-binary=:all:`) : aucun `setup.py` d'un paquet n'est exécuté à l'installation ;
  • deux plugins peuvent exiger deux VERSIONS différentes de la même bibliothèque : pendant que le code d'un plugin
    s'exécute (chargement, événements, boutons, menus), ses bibliothèques prennent la place de celles des autres
    (`scope`). Limite honnête : c'est un échange du cache d'import, pas un processus séparé — un thread d'arrière-plan
    qui importe tardivement une bibliothèque du plugin peut obtenir l'autre version ; importez en haut de fichier.

Les bibliothèques installées ne sont PAS auditées (c'est du code PyPI) : c'est pourquoi la permission « libs »
est affichée avant l'installation d'un plugin.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import core

INSTALL_TIMEOUT = 900.0
STAMP = ".voktora-requires.json"
_scope_lock = threading.RLock()
_caches: dict[str, dict[str, object]] = {}          # plugin → modules importés depuis ses libs
_install_lock = threading.Lock()


class LibsError(RuntimeError):
    """Installation ou préparation des bibliothèques impossible (message affichable)."""


def libs_dir(plugin_id: str) -> Path:
    return core.get_data_dir() / "plugins_data" / plugin_id / "libs"


def _fingerprint(requires: list[str]) -> str:
    text = json.dumps({"requires": sorted(requires), "py": sys.version_info[:2]}, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def is_ready(plugin_id: str, requires: list[str]) -> bool:
    """Les bibliothèques demandées sont-elles déjà installées (même liste, même version de Python) ?"""
    if not requires:
        return True
    try:
        stamp = json.loads((libs_dir(plugin_id) / STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return stamp.get("fingerprint") == _fingerprint(requires)


def installer() -> list[str] | None:
    """Commande de base de l'installateur (uv, sinon pip), ou None si aucun n'est disponible."""
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "pip", "install"]
        if Path(sys.executable).name.lower().startswith("python"):
            cmd += ["--python", sys.executable]
        return cmd
    if Path(sys.executable).name.lower().startswith("python"):
        return [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    python = shutil.which("python3") or shutil.which("python")
    return [python, "-m", "pip", "install", "--disable-pip-version-check"] if python else None


def install(plugin_id: str, requires: list[str], on_output: Callable[[str], None] | None = None,
            force: bool = False) -> None:
    """Installe `requires` pour ce plugin (remplace le dossier libs/). Lève LibsError avec la sortie utile."""
    if not requires:
        return
    if not force and is_ready(plugin_id, requires):
        return
    base = installer()
    if base is None:
        raise LibsError("Ni « uv » ni « pip » n'est disponible : installez uv (https://docs.astral.sh/uv/) pour que "
                        "Voktora puisse installer les bibliothèques de ce plugin.")
    with _install_lock:
        target = libs_dir(plugin_id)
        staging = target.with_name("libs.new")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        command = [*base, "--target", str(staging), "--only-binary=:all:", *requires]
        if on_output:
            on_output("$ " + " ".join(command))
        env = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONNOUSERSITE": "1"}
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=INSTALL_TIMEOUT,    # noqa: S603
                                  encoding="utf-8", errors="replace", env=env, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise LibsError(f"Installation impossible : {exc}") from exc
        output = (done.stdout or "") + (done.stderr or "")
        if on_output:
            on_output(output)
        if done.returncode != 0:
            shutil.rmtree(staging, ignore_errors=True)
            raise LibsError("L'installation des bibliothèques a échoué :\n" + output[-1500:])
        (staging / STAMP).write_text(json.dumps({"fingerprint": _fingerprint(requires), "requires": requires}),
                                     encoding="utf-8")
        shutil.rmtree(target, ignore_errors=True)
        staging.replace(target)
        _caches.pop(plugin_id, None)


def remove(plugin_id: str) -> None:
    shutil.rmtree(libs_dir(plugin_id), ignore_errors=True)
    _caches.pop(plugin_id, None)


def top_level_names(folder: Path) -> set[str]:
    """Noms de modules de premier niveau installés dans `folder`."""
    names: set[str] = set()
    for entry in folder.iterdir() if folder.is_dir() else []:
        n = entry.name
        if n.startswith(".") or n == "__pycache__" or n.endswith((".dist-info", ".egg-info", ".data")) or n == "bin":
            continue
        names.add(n[:-3] if n.endswith(".py") else n.split(".")[0] if entry.is_file() else n)
    return names


@contextlib.contextmanager
def scope(plugin_id: str) -> Iterator[None]:
    """Fait passer les bibliothèques de ce plugin avant toutes les autres, le temps du bloc."""
    folder = libs_dir(plugin_id)
    if not folder.is_dir():
        yield
        return
    with _scope_lock:
        names = top_level_names(folder)

        def owned(module: str) -> bool:
            return module.split(".")[0] in names

        saved = {m: sys.modules.pop(m) for m in [m for m in sys.modules if owned(m)]}
        sys.modules.update(_caches.get(plugin_id, {}))
        sys.path.insert(0, str(folder))
        try:
            yield
        finally:
            with contextlib.suppress(ValueError):
                sys.path.remove(str(folder))
            _caches[plugin_id] = {m: mod for m, mod in sys.modules.items() if owned(m)}
            for m in [m for m in sys.modules if owned(m)]:
                del sys.modules[m]
            sys.modules.update(saved)


def stdlib_or_installed(module: str) -> bool:
    """Le module (premier niveau) est-il importable sans rien installer (bibliothèque standard ou Voktora) ?"""
    import importlib.util
    top = module.split(".")[0]
    if top in sys.stdlib_module_names or top in sys.builtin_module_names:
        return True
    try:
        return importlib.util.find_spec(top) is not None
    except (ImportError, ValueError):
        return False
