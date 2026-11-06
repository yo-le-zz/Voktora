"""
Voktora — plugins.runtime
Chargement, registre, API (version 2) et événements des plugins.

Deux formes de plugin :
  • dossier  `plugins/<id>/plugin.json` + `main.py` (+ fichiers annexes)  -> API 2, permissions vérifiées ;
  • fichier  `plugins/mon_plugin.py` (ancien format, API 1)               -> toujours chargé, toutes permissions.

⚠ Les plugins sont du code Python exécuté avec vos droits : les « permissions » sont une déclaration
vérifiée par l'API (et relue par le mainteneur du dépôt), PAS un bac à sable. N'installez que des plugins
dont vous avez confiance en l'auteur.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import core

from . import manifest as manifest_mod

# ── Événements ────────────────────────────────────────────────────────────────

EVENTS: dict[str, str] = {
    "on_start":         "L'application est prête (fenêtre affichée).",
    "on_quit":          "L'application va se fermer.",
    "on_open":          "Un projet vient d'être ouvert (ctx.project_path).",
    "on_close":         "On quitte le projet (retour à la liste).",
    "on_create":        "Un projet vient d'être créé (ctx.project_path).",
    "on_delete":        "Un projet vient d'être supprimé (ctx.project_path).",
    "on_rename":        "Un projet a été renommé (ctx.project_path, ctx.data['old_path']).",
    "on_refresh":       "La liste des projets a été rafraîchie.",
    "on_theme_changed": "Le thème a changé (ctx.data['theme']).",
}

SLOW_HANDLER_SECONDS = 0.25      # au-delà, l'événement est noté comme « lent » dans le gestionnaire
MAX_HTTP_BYTES = 2 * 1024 * 1024
MAX_ERRORS_KEPT = 20


class PluginError(RuntimeError):
    """Erreur d'utilisation de l'API de plugins (permission manquante, interface absente…)."""


# ── Types ─────────────────────────────────────────────────────────────────────

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
    icon:    str = ""


@dataclass
class PluginInfo:
    name:        str
    version:     str
    author:      str
    path:        Path
    id:          str = ""
    description: str = ""
    legacy:      bool = False                 # ancien plugin « fichier .py » (API 1)
    enabled:     bool = True
    loaded:      bool = False
    permissions: list[str] = field(default_factory=list)
    commands:    list[PluginCommand] = field(default_factory=list)
    buttons:     list[PluginButton]  = field(default_factory=list)
    hooks:       dict[str, list[Callable]] = field(default_factory=dict)
    error:       str = ""
    errors:      list[str] = field(default_factory=list)      # erreurs d'exécution récentes
    slow:        list[str] = field(default_factory=list)      # gestionnaires lents
    stylesheet:  str = ""
    module_name: str = ""
    teardown:    list[Callable] = field(default_factory=list)
    on_unload:   Callable | None = None

    def note_error(self, message: str) -> None:
        self.errors.append(message)
        del self.errors[:-MAX_ERRORS_KEPT]


class PluginContext:
    """Objet passé aux handlers de plugin."""

    def __init__(self, project_path: Path | None = None, log_cb: Callable | None = None,
                 args: dict | None = None, data: dict | None = None):
        self.project_path = project_path
        self.args         = args or {}
        self.data         = data or {}
        self._log_cb      = log_cb

    def log(self, msg: str) -> None:
        if self._log_cb:
            self._log_cb(msg)


# ── Registre global ───────────────────────────────────────────────────────────

_plugins: list[PluginInfo] = []
_ui_host: Any = None                    # plugins.ui_host.UIHost (ou un faux en test)
_extra_themes: dict[str, dict] = {}     # thèmes enregistrés par des plugins
_lock = threading.RLock()


def plugins_dir() -> Path:
    return core.get_data_dir() / "plugins"


def plugin_data_dir(plugin_id: str) -> Path:
    path = core.get_data_dir() / "plugins_data" / plugin_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_ui_host(host: Any) -> None:
    global _ui_host
    _ui_host = host


def get_ui_host() -> Any:
    return _ui_host


# ── Activation (persistée dans la config) ─────────────────────────────────────

def disabled_ids() -> set[str]:
    cfg = core.get_app_config().get("plugins", {})
    return set(cfg.get("disabled", [])) if isinstance(cfg, dict) else set()


def _save_disabled(ids: set[str]) -> None:
    app_cfg = core.get_app_config()
    section = app_cfg.get("plugins") if isinstance(app_cfg.get("plugins"), dict) else {}
    section["disabled"] = sorted(ids)
    app_cfg["plugins"] = section
    core.set_app_config(app_cfg)


def market_url() -> str:
    cfg = core.get_app_config().get("plugins", {})
    return (cfg.get("market_url") or "").strip() if isinstance(cfg, dict) else ""


def set_market_url(url: str) -> None:
    app_cfg = core.get_app_config()
    section = app_cfg.get("plugins") if isinstance(app_cfg.get("plugins"), dict) else {}
    section["market_url"] = url.strip()
    app_cfg["plugins"] = section
    core.set_app_config(app_cfg)


def set_enabled(plugin_id: str, enabled: bool) -> PluginInfo | None:
    """Active/désactive un plugin (persistant) et le (dé)charge immédiatement."""
    disabled = disabled_ids()
    (disabled.discard if enabled else disabled.add)(plugin_id)
    _save_disabled(disabled)
    info = find(plugin_id)
    if info is None:
        return None
    unload(info)
    info.enabled = enabled
    if enabled:
        _load_into(info)
    return info


# ── Stockage clé/valeur par plugin ────────────────────────────────────────────

class PluginSettings:
    """Petit stockage JSON persistant propre à un plugin (`plugins_data/<id>/settings.json`)."""

    def __init__(self, plugin_id: str):
        self._id = plugin_id
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return plugin_data_dir(self._id) / "settings.json"

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        text = json.dumps(data, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp, self.path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._read().get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            data = self._read()
            data[key] = value
            self._write(data)

    def delete(self, key: str) -> None:
        with self._lock:
            data = self._read()
            if data.pop(key, None) is not None:
                self._write(data)

    def all(self) -> dict:
        with self._lock:
            return self._read()


# ── API exposée aux plugins ───────────────────────────────────────────────────

class PluginAPI:
    """Objet reçu par `on_load(api)`. Toutes les méthodes sont documentées dans doc/PLUGINS.md."""

    api_version = manifest_mod.API_VERSION

    def __init__(self, info: PluginInfo):
        self._info = info
        self.settings = PluginSettings(info.id or info.name)
        self._events: dict[str, list[Callable]] = {}

    # -- méta -----------------------------------------------------------------
    @property
    def plugin_id(self) -> str:
        return self._info.id

    @property
    def app_version(self) -> str:
        return core.APP_VERSION

    @property
    def data_dir(self) -> Path:
        """Dossier privé du plugin (créé à la demande) pour ses fichiers."""
        return plugin_data_dir(self._info.id or self._info.name)

    @property
    def plugin_dir(self) -> Path:
        return self._info.path if self._info.path.is_dir() else self._info.path.parent

    def _require(self, permission: str) -> None:
        if self._info.legacy:
            return
        if permission not in self._info.permissions:
            raise PluginError(
                f"Le plugin « {self._info.name} » n'a pas déclaré la permission « {permission} » "
                f"dans plugin.json."
            )

    def _host(self) -> Any:
        self._require("ui")
        if _ui_host is None:
            raise PluginError("L'interface n'est pas disponible (Voktora lancé sans fenêtre).")
        return _ui_host

    def _track(self, undo: Callable[[], None]) -> None:
        self._info.teardown.append(undo)

    # -- enregistrement ---------------------------------------------------------
    def register_command(self, name: str, handler: Callable, desc: str = "") -> None:
        self._info.commands.append(PluginCommand(name, handler, desc))

    def register_button(self, label: str, handler: Callable, tooltip: str = "", icon: str = "") -> None:
        """Bouton dans le groupe « Plugins » de l'onglet Outils du projet."""
        self._info.buttons.append(PluginButton(label, handler, tooltip, icon))

    def register_hook(self, hook_name: str, handler: Callable) -> None:
        if hook_name not in EVENTS and not hook_name.startswith("plugin:"):
            raise PluginError(f"Événement inconnu : « {hook_name} ». Disponibles : {', '.join(EVENTS)}.")
        self._info.hooks.setdefault(hook_name, []).append(handler)

    on = register_hook

    def emit(self, event: str, **data: Any) -> None:
        """Événement entre plugins : `api.emit("mon-event", x=1)` -> hooks « plugin:mon-event »."""
        fire_hook(f"plugin:{event}", data=data)

    def register_theme(self, theme_id: str, name: str, colors: dict[str, str], description: str = "") -> None:
        """Ajoute un thème (apparaît dans Paramètres → Thèmes). `colors` : mêmes clés que les thèmes JSON."""
        self._require("ui")
        key = f"{self._info.id}-{theme_id}"
        _extra_themes[key] = {"name": name, "description": description or f"Thème du plugin {self._info.name}",
                              "colors": dict(colors)}
        self._track(lambda: _extra_themes.pop(key, None))

    # -- interface (permission « ui ») -------------------------------------------
    def add_menu_action(self, menu: str, label: str, handler: Callable, icon: str = "",
                        shortcut: str = "", checkable: bool = False, checked: bool = False,
                        tooltip: str = "") -> Any:
        """Action dans un menu. `menu` : « Outils », ou un chemin « Mon plugin/Sous-menu »
        (créé s'il n'existe pas). Retourne le QAction."""
        host = self._host()
        action = host.add_menu_action(self._info, menu, label, self._wrap(handler), icon, shortcut,
                                      checkable, checked, tooltip)
        return action

    def add_toolbar_button(self, label: str, handler: Callable, icon: str = "", tooltip: str = "") -> Any:
        """Bouton dans la barre d'outils des plugins (en haut de la fenêtre)."""
        return self._host().add_toolbar_button(self._info, label, self._wrap(handler), icon, tooltip)

    def add_project_tab(self, title: str, factory: Callable[[PluginContext], Any], icon: str = "") -> None:
        """Onglet dans la page d'un projet. `factory(ctx)` retourne un QWidget ; s'il possède une méthode
        `set_project(path)`, elle est appelée à chaque changement de projet."""
        self._host().add_project_tab(self._info, title, factory, icon)

    def add_sidebar_panel(self, title: str, factory: Callable[[PluginContext], Any], icon: str = "") -> None:
        """Panneau repliable en bas de la barre latérale gauche."""
        self._host().add_sidebar_panel(self._info, title, factory, icon)

    def add_status_widget(self, factory: Callable[[PluginContext], Any]) -> None:
        """Widget permanent à droite de la barre d'état."""
        self._host().add_status_widget(self._info, factory)

    def add_context_action(self, target: str, label: str, handler: Callable, icon: str = "") -> None:
        """Entrée dans le menu contextuel (clic droit). `target` : « project »."""
        self._host().add_context_action(self._info, target, label, self._wrap(handler), icon)

    def set_stylesheet(self, qss: str) -> None:
        """Ajoute une feuille de style Qt (QSS) par-dessus le thème. Remplace celle du plugin."""
        self._host()
        self._info.stylesheet = qss or ""
        _restyle()

    def notify(self, message: str, timeout_ms: int = 4000) -> None:
        self._host().notify(message, timeout_ms)

    def message(self, title: str, text: str) -> None:
        self._host().message(title, text)

    def confirm(self, title: str, text: str) -> bool:
        return bool(self._host().confirm(title, text))

    def ask_text(self, title: str, label: str, default: str = "") -> str | None:
        return self._host().ask_text(title, label, default)

    def main_window(self) -> Any:
        """La QMainWindow de Voktora, pour les plugins qui ont vraiment besoin d'agir dessus (mode zen…).
        Très puissant : préférez les méthodes `add_*` quand elles suffisent."""
        return self._host().window

    def open_project(self, path: str | Path) -> None:
        self._host().open_project(Path(path))

    def refresh(self) -> None:
        self._host().refresh()

    def icon(self, icon_id: str, color: str | None = None) -> Any:
        """QIcon vectoriel (« mdi:nom » ; voir le sélecteur d'icônes)."""
        import icons
        return icons.icon(icon_id, color=color)

    def theme_colors(self) -> dict[str, str]:
        """Couleurs du thème courant (base, text, blue, green, red…)."""
        import theme_manager
        try:
            theme = theme_manager.load_theme(core.get_app_config().get("theme", "default"))
        except (KeyError, ValueError):
            theme = theme_manager.load_theme("default")
        return dict(theme.get("colors", {}))

    def run_async(self, work: Callable[[], Any], on_done: Callable[[Any], None] | None = None,
                  on_error: Callable[[BaseException], None] | None = None) -> None:
        """Exécute `work()` dans un thread ; `on_done(résultat)` / `on_error(exc)` reviennent sur le
        thread de l'interface (on peut y toucher aux widgets)."""
        host = _ui_host

        def post(fn: Callable[[], None]) -> None:
            if host is not None:
                host.post(fn)
            else:
                fn()

        def runner() -> None:
            try:
                result = work()
            except BaseException as exc:              # noqa: BLE001 - renvoyé au plugin
                if on_error:
                    post(lambda error=exc: on_error(error))
                else:
                    self._info.note_error(f"run_async : {exc}")
                return
            if on_done:
                post(lambda: on_done(result))

        threading.Thread(target=runner, name=f"plugin-{self._info.id}", daemon=True).start()

    # -- données ------------------------------------------------------------------
    def projects(self) -> list[dict]:
        """Projets enregistrés : [{name, path, category, …}]."""
        self._require("projects.read")
        return [dict(p) for p in core.list_projects()]

    def current_project(self) -> Path | None:
        self._require("projects.read")
        host = _ui_host
        return host.current_project() if host is not None else None

    def project_info(self, path: str | Path) -> dict:
        self._require("projects.read")
        for entry in core.list_projects():
            if entry.get("path") == str(path):
                return dict(entry)
        return {}

    # -- réseau / système -----------------------------------------------------------
    def http_get(self, url: str, timeout: float = 10.0, max_bytes: int = MAX_HTTP_BYTES) -> bytes:
        """GET HTTPS (permission « network »). Limite de taille, pas de redirection vers http."""
        self._require("network")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise PluginError("http_get n'accepte que des URL https://.")
        request = urllib.request.Request(url, headers={"User-Agent": f"Voktora-plugin/{core.APP_VERSION}"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:   # noqa: S310 - https vérifié
                if not response.geturl().startswith("https://"):
                    raise PluginError("Redirection vers un site non sécurisé refusée.")
                data = response.read(max_bytes + 1)
        except urllib.error.URLError as exc:
            raise PluginError(f"Requête impossible : {exc.reason if hasattr(exc, 'reason') else exc}") from exc
        if len(data) > max_bytes:
            raise PluginError(f"Réponse trop grande (> {max_bytes // 1024} Ko).")
        return data

    def run(self, args: list[str], cwd: str | Path | None = None, timeout: float = 30.0) -> tuple[int, str]:
        """Lance un programme (permission « shell »), sans passer par un interpréteur de commandes.
        Retourne (code, sortie standard+erreur)."""
        self._require("shell")
        if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
            raise PluginError("run() attend une liste d'arguments, ex. ['git', 'status'].")
        try:
            done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout,   # noqa: S603
                                  encoding="utf-8", errors="replace", check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PluginError(f"Commande impossible : {exc}") from exc
        return done.returncode, (done.stdout or "") + (done.stderr or "")

    # -- interne ---------------------------------------------------------------------
    def _wrap(self, handler: Callable) -> Callable:
        """Les handlers d'UI reçoivent `ctx` (ou rien s'ils n'ont aucun paramètre) ; leurs erreurs
        sont capturées : un plugin qui plante ne fait pas planter Voktora."""
        import inspect
        info = self._info
        try:
            takes_ctx = len(inspect.signature(handler).parameters) >= 1
        except (TypeError, ValueError):
            takes_ctx = True

        def call(*_qt_args: Any) -> None:
            try:
                if takes_ctx:
                    handler(PluginContext(project_path=_current_project(), log_cb=_log))
                else:
                    handler()
            except Exception:
                info.note_error(traceback.format_exc())
                _log(f"[plugin:{info.name}] erreur — voir Paramètres → Plugins")
        return call


def _current_project() -> Path | None:
    host = _ui_host
    try:
        return host.current_project() if host is not None else None
    except Exception:
        return None


def _log(message: str) -> None:
    host = _ui_host
    if host is not None:
        with contextlib.suppress(Exception):
            host.log(message)


def _restyle() -> None:
    host = _ui_host
    if host is not None:
        with contextlib.suppress(Exception):
            host.restyle()


# ── Chargement ───────────────────────────────────────────────────────────────

def load_all() -> list[PluginInfo]:
    """(Re)charge tous les plugins du dossier `plugins/`."""
    with _lock:
        for info in list(_plugins):
            unload(info)
        _plugins.clear()
        folder = plugins_dir()
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            return _plugins
        disabled = disabled_ids()
        for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith(("_", ".")):
                continue
            info = _describe(entry, disabled)
            if info is None:
                continue
            _plugins.append(info)
            if info.enabled and not info.error:
                _load_into(info)
        return _plugins


def _describe(entry: Path, disabled: set[str]) -> PluginInfo | None:
    """Crée la fiche d'un plugin SANS exécuter son code."""
    if entry.is_dir():
        info = PluginInfo(name=entry.name, version="?", author="?", path=entry, id=entry.name)
        try:
            man = manifest_mod.load(entry)
        except manifest_mod.ManifestError as exc:
            info.error = str(exc)
            return info
        info.id, info.name, info.version, info.author = man.id, man.name, man.version, man.author
        info.description, info.permissions = man.description, list(man.permissions)
        info.module_name = f"voktora_plugin_{man.id.replace('-', '_')}"
    elif entry.suffix == ".py" and entry.is_file():
        info = PluginInfo(name=entry.stem, version="?", author="?", path=entry, id=entry.stem, legacy=True)
        info.module_name = f"voktora_plugin_{entry.stem}"
    else:
        return None
    if info.id in disabled:
        info.enabled = False
    return info


def _entry_file(info: PluginInfo) -> Path:
    if info.legacy:
        return info.path
    return info.path / manifest_mod.load(info.path).entry


def _load_into(info: PluginInfo) -> None:
    info.error = ""
    try:
        entry = _entry_file(info)
        kwargs = {} if info.legacy else {"submodule_search_locations": [str(info.path)]}
        spec = importlib.util.spec_from_file_location(info.module_name, entry, **kwargs)
        if spec is None or spec.loader is None:
            raise ImportError(f"Impossible de charger {entry}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[info.module_name] = module
        spec.loader.exec_module(module)
        if info.legacy:
            info.name = getattr(module, "PLUGIN_NAME", info.name)
            info.version = getattr(module, "PLUGIN_VERSION", info.version)
            info.author = getattr(module, "PLUGIN_AUTHOR", info.author)
        api = PluginAPI(info)
        if hasattr(module, "on_load"):
            module.on_load(api)
        info.on_unload = (lambda m=module, a=api: m.on_unload(a)) if hasattr(module, "on_unload") else None
        info.loaded = True
        if info.stylesheet:
            _restyle()          # le style n'est pris en compte qu'une fois le plugin marqué « chargé »
    except Exception:
        info.error = traceback.format_exc()
        info.loaded = False
        unload(info, keep_error=True)


def unload(info: PluginInfo, keep_error: bool = False) -> None:
    """Retire tout ce que le plugin a ajouté (menus, onglets, styles, hooks, thèmes)."""
    if info.on_unload is not None:
        with contextlib.suppress(Exception):
            info.on_unload()
    for undo in reversed(info.teardown):
        with contextlib.suppress(Exception):
            undo()
    info.teardown.clear()
    info.commands.clear()
    info.buttons.clear()
    info.hooks.clear()
    info.on_unload = None
    had_style = bool(info.stylesheet)
    info.stylesheet = ""
    info.loaded = False
    if info.module_name:
        for name in [n for n in sys.modules if n == info.module_name or n.startswith(info.module_name + ".")]:
            sys.modules.pop(name, None)
    if had_style:
        _restyle()
    if not keep_error:
        info.error = ""


def forget(plugin_id: str) -> None:
    """Retire le plugin du registre (après désinstallation)."""
    info = find(plugin_id)
    if info is not None:
        unload(info)
        _plugins.remove(info)


def find(plugin_id: str) -> PluginInfo | None:
    return next((p for p in _plugins if p.id == plugin_id), None)


def get_all() -> list[PluginInfo]:
    return _plugins


# ── Événements et accès au registre ────────────────────────────────────────────

def fire_hook(hook_name: str, project_path: Path | None = None, log_cb: Callable | None = None,
              data: dict | None = None) -> None:
    """Déclenche `hook_name` sur tous les plugins actifs. Une erreur dans un plugin n'affecte ni
    l'application ni les autres plugins."""
    ctx = PluginContext(project_path=project_path, log_cb=log_cb or _log, data=data)
    for plugin in list(_plugins):
        if not plugin.loaded:
            continue
        for handler in list(plugin.hooks.get(hook_name, [])):
            started = time.perf_counter()
            try:
                handler(ctx)
            except Exception as exc:
                plugin.note_error(f"{hook_name} : {exc}\n{traceback.format_exc()}")
                if ctx._log_cb:
                    ctx._log_cb(f"[plugin:{plugin.name}:{hook_name}] {exc}")
            elapsed = time.perf_counter() - started
            if elapsed > SLOW_HANDLER_SECONDS:
                note = f"{hook_name} : {elapsed:.2f} s"
                if note not in plugin.slow:
                    plugin.slow.append(note)
                    del plugin.slow[:-5]


def all_commands() -> list[tuple[PluginInfo, PluginCommand]]:
    return [(p, cmd) for p in _plugins if p.loaded for cmd in p.commands]


def all_buttons() -> list[tuple[PluginInfo, PluginButton]]:
    return [(p, btn) for p in _plugins if p.loaded for btn in p.buttons]


def extra_stylesheet() -> str:
    """QSS cumulé de tous les plugins actifs (ajouté après celui du thème)."""
    return "\n".join(p.stylesheet for p in _plugins if p.loaded and p.stylesheet)


def extra_themes() -> dict[str, dict]:
    return dict(_extra_themes)
