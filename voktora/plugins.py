"""
plugins.py — Système de plugins Voktora
Charge les plugins depuis data/plugins/ et expose un registre de hooks/commandes/boutons UI.

Interface d'un plugin (exemple — voir docs/plugins.md) :
    PLUGIN_NAME    = "MonPlugin"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_AUTHOR  = "toi"

    def on_load(api):              # appelé au chargement
        api.register_command("my_cmd", run_cmd)
        api.register_hook("on_create", on_project_created)
        api.register_button("🛠 Mon bouton", on_button_click)

    def run_cmd(ctx):              # ctx.project_path, ctx.log, ctx.args
        ctx.log("Hello from plugin!")

    def on_project_created(ctx):
        ctx.log(f"Projet créé : {ctx.project_path}")

    def on_button_click(ctx):
        ctx.log("Bouton cliqué !")
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any

import core


# ── Types ──────────────────────────────────────────────────────────────────────

@dataclass
class PluginCommand:
    name:    str
    handler: Callable
    desc:    str = ""


@dataclass
class PluginButton:
    label:   str
    handler: Callable
    tooltip: str = ""


@dataclass
class PluginInfo:
    name:     str
    version:  str
    author:   str
    path:     Path
    commands: list[PluginCommand] = field(default_factory=list)
    buttons:  list[PluginButton]  = field(default_factory=list)
    hooks:    dict[str, list[Callable]] = field(default_factory=dict)
    error:    str = ""


class PluginContext:
    """Objet passé aux handlers de plugin."""
    def __init__(self, project_path: Path | None = None,
                 log_cb: Callable | None = None, args: dict | None = None):
        self.project_path = project_path
        self.args         = args or {}
        self._log_cb      = log_cb

    def log(self, msg: str) -> None:
        if self._log_cb:
            self._log_cb(msg)


class PluginAPI:
    """API exposée aux plugins lors de on_load(api)."""
    def __init__(self, info: PluginInfo):
        self._info = info

    def register_command(self, name: str, handler: Callable, desc: str = "") -> None:
        self._info.commands.append(PluginCommand(name, handler, desc))

    def register_button(self, label: str, handler: Callable, tooltip: str = "") -> None:
        self._info.buttons.append(PluginButton(label, handler, tooltip))

    def register_hook(self, hook_name: str, handler: Callable) -> None:
        self._info.hooks.setdefault(hook_name, []).append(handler)


# ── Registre global ────────────────────────────────────────────────────────────

_plugins: list[PluginInfo] = []


def plugins_dir() -> Path:
    return core.get_data_dir() / "plugins"


def load_all() -> list[PluginInfo]:
    """Charge tous les plugins depuis data/plugins/*.py."""
    global _plugins
    _plugins = []
    d = plugins_dir()
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        _write_example_plugin(d)
        return _plugins

    for py_file in sorted(d.glob("*.py")):
        if py_file.stem.startswith("_"):
            continue
        _load_plugin_file(py_file)

    return _plugins


def _load_plugin_file(path: Path) -> None:
    info = PluginInfo(
        name=path.stem, version="?", author="?", path=path
    )
    try:
        spec   = importlib.util.spec_from_file_location(f"voktora_plugin_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        info.name    = getattr(module, "PLUGIN_NAME",    path.stem)
        info.version = getattr(module, "PLUGIN_VERSION", "?")
        info.author  = getattr(module, "PLUGIN_AUTHOR",  "?")

        if hasattr(module, "on_load"):
            api = PluginAPI(info)
            module.on_load(api)

        _plugins.append(info)
    except Exception:
        info.error = traceback.format_exc()
        _plugins.append(info)


def get_all() -> list[PluginInfo]:
    return _plugins


def fire_hook(hook_name: str, project_path: Path | None = None,
              log_cb: Callable | None = None) -> None:
    """Déclenche le hook `hook_name` sur tous les plugins chargés."""
    ctx = PluginContext(project_path=project_path, log_cb=log_cb)
    for plugin in _plugins:
        for handler in plugin.hooks.get(hook_name, []):
            try:
                handler(ctx)
            except Exception as e:
                if log_cb:
                    log_cb(f"[plugin:{plugin.name}:{hook_name}] {e}")


def all_commands() -> list[tuple[PluginInfo, PluginCommand]]:
    return [(p, cmd) for p in _plugins for cmd in p.commands]


def all_buttons() -> list[tuple[PluginInfo, PluginButton]]:
    return [(p, btn) for p in _plugins for btn in p.buttons]


# ── Plugin exemple ─────────────────────────────────────────────────────────────

def _write_example_plugin(d: Path) -> None:
    example = d / "_example_plugin.py"
    example.write_text(
        '''"""
_example_plugin.py — Template de plugin Voktora
Renommez ce fichier (sans underscore) pour l'activer.

Documentation complète : https://github.com/yo-le-zz/Voktora/docs/plugins.md
"""

PLUGIN_NAME    = "ExamplePlugin"
PLUGIN_VERSION = "1.0.0"
PLUGIN_AUTHOR  = "vous"


def on_load(api):
    """Enregistre les commandes, boutons et hooks du plugin."""
    api.register_command("hello", cmd_hello, desc="Affiche un message de bienvenue")
    api.register_button("👋 Hello Plugin", btn_hello, tooltip="Exemple de bouton plugin")
    api.register_hook("on_create", hook_on_create)
    api.register_hook("on_open",   hook_on_open)


def cmd_hello(ctx):
    """ctx.project_path, ctx.log(), ctx.args"""
    ctx.log(f"Hello depuis ExamplePlugin ! Projet : {ctx.project_path}")


def btn_hello(ctx):
    ctx.log("Bouton plugin cliqué !")


def hook_on_create(ctx):
    ctx.log(f"[ExamplePlugin] Nouveau projet créé : {ctx.project_path}")


def hook_on_open(ctx):
    ctx.log(f"[ExamplePlugin] Projet ouvert : {ctx.project_path}")
''',
        encoding="utf-8",
    )
