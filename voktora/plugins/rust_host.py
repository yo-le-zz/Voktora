"""
Voktora — plugins.rust_host (1.1.1)
Plugins écrits en RUST : `plugin.json` avec `"lang": "rust"`, `"entry": "Cargo.toml"`, permission « native ».

  plugin/
    plugin.json
    Cargo.toml        crate-type = ["cdylib"] ; voktora-plugin = { path = "../voktora-sdk" } ; TOUTES les crates voulues
    src/lib.rs        plugin!(on_load, on_unload);  puis  fn on_load(api: &Api) { api.notify("Salut"); }

Voktora COMPILE le plugin lui-même (cargo requis ; première compilation : quelques minutes, ensuite seulement si le code
change) dans un dossier privé du plugin, puis charge la bibliothèque. Les crates externes (serde, regex, image…) sont
téléchargées par cargo ; elles sont compilées avec le plugin — « déjà compilées » du point de vue de Voktora.

Interface binaire (ABI 1, JSON dans les deux sens, aucune structure C partagée) : voir native/sdk/voktora-plugin.
  plugin exporte : voktora_plugin_abi() · voktora_plugin_init(host_call, host_free) ·
                   voktora_plugin_dispatch(requête JSON) · voktora_plugin_free(pointeur)
  Voktora fournit : host_call({"name","args"}) → JSON  (même pont que JavaScript : plugins.bridge)

SÉCURITÉ — à lire : c'est du code NATIF dans le processus de Voktora. Aucun bac à sable : il peut lire vos fichiers,
ouvrir le réseau, lancer des programmes, sans passer par les permissions (qui ne contrôlent que les appels à l'API).
D'où : permission « native » affichée avant l'installation, niveau officiel uniquement dans le marketplace, et pour les
plugins locaux, une confirmation à chaque (re)compilation.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import core

from . import bridge, manifest

ABI = 1
BUILD_TIMEOUT = 1800.0
SKIP_DIRS = {"target", ".git", "node_modules", "__pycache__"}
HOST_CALL = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p)
HOST_FREE = ctypes.CFUNCTYPE(None, ctypes.c_void_p)


class RustError(RuntimeError):
    """Compilation ou chargement impossible (message affichable)."""


def sdk_dir() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [Path(os.environ["VOKTORA_SDK"]) if os.environ.get("VOKTORA_SDK") else None,
                  here.parents[2] / "native" / "sdk" / "voktora-plugin",
                  here.parents[1] / "sdk" / "voktora-plugin",
                  Path(sys.executable).parent / "sdk" / "voktora-plugin"]
    return next((c for c in candidates if c and (c / "Cargo.toml").is_file()), None)


def cargo_path() -> str | None:
    return shutil.which("cargo") or next((str(p) for p in (Path.home() / ".cargo" / "bin" / "cargo",) if p.is_file()), None)


def _dirs(plugin_id: str) -> dict[str, Path]:
    base = core.get_data_dir() / "plugins_data" / plugin_id
    return {"build": base / "rust-build", "target": base / "rust-target", "lib": base / "rust-lib"}


def _source_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file() and not SKIP_DIRS & set(p.relative_to(folder).parts))


def fingerprint(plugin_dir: Path) -> str:
    digest = hashlib.sha256(b"abi1")
    for path in _source_files(plugin_dir):
        digest.update(path.relative_to(plugin_dir).as_posix().encode())
        digest.update(path.read_bytes())
    sdk = sdk_dir()
    if sdk is not None:
        for path in _source_files(sdk):
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def lib_name(plugin_dir: Path) -> str:
    text = (plugin_dir / "Cargo.toml").read_text(encoding="utf-8")
    import re
    lib = re.search(r"^\[lib\][^\[]*?^name\s*=\s*\"([^\"]+)\"", text, re.MULTILINE | re.DOTALL)
    pkg = re.search(r"^\[package\][^\[]*?^name\s*=\s*\"([^\"]+)\"", text, re.MULTILINE | re.DOTALL)
    name = (lib or pkg).group(1) if (lib or pkg) else ""
    if not name:
        raise RustError("Cargo.toml : nom du paquet introuvable.")
    return name.replace("-", "_")


def _lib_filename(name: str, tag: str = "") -> str:
    suffix = {"win32": ".dll", "darwin": ".dylib"}.get(sys.platform, ".so")
    prefix = "" if sys.platform == "win32" else "lib"
    return f"{prefix}{name}{('-' + tag) if tag else ''}{suffix}"


def built_library(plugin_id: str, plugin_dir: Path) -> Path | None:
    path = _dirs(plugin_id)["lib"] / _lib_filename(lib_name(plugin_dir), fingerprint(plugin_dir))
    return path if path.is_file() else None


def is_built(info: Any) -> bool:
    try:
        return built_library(info.id, Path(info.path)) is not None
    except (OSError, RustError):
        return False


def build(info: Any, on_output: Callable[[str], None] | None = None) -> Path:
    """Compile le plugin (cargo build --release) et retourne la bibliothèque, copiée sous un nom unique."""
    plugin_dir = Path(info.path)
    cargo, sdk = cargo_path(), sdk_dir()
    if cargo is None:
        raise RustError("« cargo » est introuvable : installez Rust (https://rustup.rs) pour compiler ce plugin.")
    if sdk is None:
        raise RustError("SDK Rust de Voktora introuvable (dossier native/sdk/voktora-plugin).")
    existing = built_library(info.id, plugin_dir)
    if existing is not None:
        return existing
    dirs = _dirs(info.id)
    tag = fingerprint(plugin_dir)
    stage = dirs["build"]
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(sdk, stage / "voktora-sdk", ignore=shutil.ignore_patterns("target", "Cargo.lock"))
    shutil.copytree(plugin_dir, stage / "plugin", ignore=shutil.ignore_patterns(*SKIP_DIRS))
    command = [cargo, "build", "--release", "--manifest-path", str(stage / "plugin" / "Cargo.toml"),
               "--target-dir", str(dirs["target"]), "--color", "never"]
    if on_output:
        on_output("$ " + " ".join(command))
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=BUILD_TIMEOUT, encoding="utf-8",   # noqa: S603
                              errors="replace", check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RustError(f"Compilation impossible : {exc}") from exc
    output = (done.stdout or "") + (done.stderr or "")
    if on_output:
        on_output(output[-3000:])
    if done.returncode != 0:
        raise RustError("La compilation du plugin Rust a échoué :\n" + output[-2500:])
    built = dirs["target"] / "release" / _lib_filename(lib_name(plugin_dir))
    if not built.is_file():
        raise RustError(f"Bibliothèque introuvable après compilation ({built.name}) : "
                        "vérifiez crate-type = [\"cdylib\"] dans Cargo.toml.")
    dirs["lib"].mkdir(parents=True, exist_ok=True)
    for old in dirs["lib"].glob("*"):                     # une seule version : les anciennes ne servent plus
        with contextlib.suppress(OSError):
            old.unlink()
    final = dirs["lib"] / _lib_filename(lib_name(plugin_dir), tag)
    shutil.copy2(built, final)
    shutil.rmtree(stage, ignore_errors=True)
    return final


class RustHost:
    def __init__(self, info: Any, api: Any, library: Path) -> None:
        self.info, self.api = info, api
        self._bridge = bridge.ApiBridge(api, self._callback)
        self._buffers: dict[int, Any] = {}
        try:
            self.lib = ctypes.CDLL(str(library))
        except OSError as exc:
            raise RustError(f"Chargement impossible de {library.name} : {exc}") from exc
        try:
            self.lib.voktora_plugin_abi.restype = ctypes.c_uint32
            abi = self.lib.voktora_plugin_abi()
        except AttributeError as exc:
            raise RustError("Ce n'est pas un plugin Voktora : utilisez la macro plugin!(on_load, on_unload).") from exc
        if abi != ABI:
            raise RustError(f"ABI {abi} incompatible (Voktora attend {ABI}) : recompilez avec le SDK actuel.")
        self.lib.voktora_plugin_init.argtypes = [HOST_CALL, HOST_FREE]
        self.lib.voktora_plugin_dispatch.argtypes = [ctypes.c_char_p]
        self.lib.voktora_plugin_dispatch.restype = ctypes.c_void_p
        self.lib.voktora_plugin_free.argtypes = [ctypes.c_void_p]
        self._host_call = HOST_CALL(self._on_host_call)          # références gardées : sinon ramassées par le GC
        self._host_free = HOST_FREE(self._on_host_free)
        self.lib.voktora_plugin_init(self._host_call, self._host_free)

    # -- plugin → application ---------------------------------------------------------------------------
    def _on_host_call(self, request: bytes) -> int | None:
        try:
            data = json.loads(request.decode("utf-8"))
            text = self._bridge.dispatch(str(data["name"]), list(data.get("args", [])))
        except Exception as exc:  # noqa: BLE001 — ne JAMAIS laisser une exception traverser vers du code natif
            text = json.dumps({"__error": f"{type(exc).__name__}: {exc}"})
        if text == "":
            return None
        buffer = ctypes.create_string_buffer(text.encode("utf-8"))
        address = ctypes.addressof(buffer)
        self._buffers[address] = buffer
        return address

    def _on_host_free(self, pointer: int) -> None:
        self._buffers.pop(pointer, None)

    # -- application → plugin -----------------------------------------------------------------------------
    def request(self, message: dict) -> dict:
        pointer = self.lib.voktora_plugin_dispatch(json.dumps(message, default=bridge.json_default).encode("utf-8"))
        if not pointer:
            return {}
        try:
            reply = json.loads(ctypes.string_at(pointer).decode("utf-8"))
        finally:
            self.lib.voktora_plugin_free(pointer)
        if isinstance(reply, dict) and reply.get("error"):
            raise RustError(str(reply["error"]))
        return reply

    def _callback(self, fn_id: int) -> Callable[..., Any]:
        def call(*args: Any) -> Any:
            ctx = bridge.context_to_dict(args[0]) if args and hasattr(args[0], "project_path") else (args[0] if args else None)
            return self.request({"op": "callback", "id": fn_id, "ctx": ctx}).get("value")
        return call

    def unload(self) -> None:
        with contextlib.suppress(Exception):
            self.request({"op": "unload"})


def load(info: Any, api: Any) -> None:
    """Appelé par runtime._load_into pour un plugin « rust » (déjà compilé : voir runtime._load_into)."""
    plugin_dir = Path(info.path)
    manifest.load(plugin_dir)
    library = built_library(info.id, plugin_dir)
    if library is None:
        raise RustError("Plugin non compilé.")
    host = RustHost(info, api, library)
    info.teardown.append(host.unload)
    host.request({"op": "load"})
