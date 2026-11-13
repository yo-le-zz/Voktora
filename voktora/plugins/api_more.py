"""
Voktora — plugins.api_more (API de plugins v5, Voktora 1.1.1)
Méthodes supplémentaires de `PluginAPI`. Même règle que api_ext : chaque méthode exige la permission déclarée,
et ce qui change l'apparence ou la sécurité passe par une confirmation montrée avec le nom du plugin.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import core


class MoreAPI:
    """Mixin : s'appuie sur `_require`, `_info`, `_confirm_security`, `_host`, `_track`, `_error` de PluginAPI."""

    # -- boutiques d'apparence (thèmes, icônes, styles) ------------------------------
    def register_shop_source(self, kind: str, name: str, url: str) -> None:
        """Ajoute une source (boutique) de thèmes (« themes »), d'icônes (« icons ») ou de styles (« styles »).
        `url` : https://…/ contenant `shops/<kind>/index.json`. Retirée au déchargement du plugin."""
        self._host()
        import shops
        try:
            undo = shops.register_plugin_source(self._info.name, kind, name, url)
        except shops.ShopError as exc:
            raise self._error(str(exc)) from exc
        self._track(undo)

    def shop_installed(self, kind: str) -> list[dict]:
        """Objets installés d'une boutique : [{id, name, version, author, description…}]."""
        self._require("config.read")
        import shops
        return shops.installed(kind)

    def set_theme(self, theme_id: str) -> None:
        """Change le thème de l'application (confirmé)."""
        self._require("ui")
        import theme_manager
        if theme_id not in theme_manager.get_available_themes():
            raise self._error(f"Thème inconnu : « {theme_id} ».")
        if not self._confirm_security("Changer de thème", f"Appliquer le thème « {theme_id} » ?"):
            raise self._error("Changement refusé par l'utilisateur.")
        theme_manager.set_theme(theme_id)
        self._restyle_now()

    def set_icon_pack(self, pack_id: str) -> None:
        """Active un pack d'icônes installé (« » pour revenir aux icônes d'origine ; confirmé)."""
        self._require("ui")
        import shops
        if not self._confirm_security("Changer de pack d'icônes", f"Activer « {pack_id or 'icônes d’origine'} » ?"):
            raise self._error("Changement refusé par l'utilisateur.")
        try:
            shops.set_icon_pack(pack_id)
        except shops.ShopError as exc:
            raise self._error(str(exc)) from exc
        self._restyle_now()

    def set_style_enabled(self, style_id: str, enabled: bool) -> None:
        """Active/désactive un style installé (confirmé)."""
        self._require("ui")
        import shops
        if not self._confirm_security("Style de la fenêtre", f"{'Activer' if enabled else 'Désactiver'} « {style_id} » ?"):
            raise self._error("Changement refusé par l'utilisateur.")
        shops.set_style_enabled(style_id, bool(enabled))
        self._restyle_now()

    def _restyle_now(self) -> Any:
        from . import runtime
        runtime._restyle()

    # -- fichiers privés du plugin (aucune permission : c'est son propre dossier) -------------------
    def data_path(self, relative: str | Path = "") -> Path:
        """Chemin SÛR dans le dossier de données du plugin (`..`, chemins absolus et liens refusés)."""
        root = self.data_dir.resolve()
        rel = Path(str(relative))
        if rel.is_absolute() or ".." in rel.parts:
            raise self._error(f"Chemin refusé : {relative!s} (relatif au dossier du plugin, sans « .. »).")
        target = (root / rel).resolve()
        if target != root and not target.is_relative_to(root):
            raise self._error(f"Chemin refusé : {relative!s}.")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def read_text(self, relative: str, default: str | None = None, encoding: str = "utf-8") -> str | None:
        try:
            return self.data_path(relative).read_text(encoding=encoding)
        except FileNotFoundError:
            return default

    def write_text(self, relative: str, text: str, encoding: str = "utf-8") -> Path:
        target = self.data_path(relative)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(text, encoding=encoding)
        tmp.replace(target)
        return target

    def read_bytes(self, relative: str) -> bytes | None:
        try:
            return self.data_path(relative).read_bytes()
        except FileNotFoundError:
            return None

    def write_bytes(self, relative: str, data: bytes) -> Path:
        target = self.data_path(relative)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        return target

    def list_data(self, relative: str = "") -> list[str]:
        base = self.data_path(relative)
        return sorted(p.name for p in base.iterdir()) if base.is_dir() else []

    def delete_data(self, relative: str) -> bool:
        target = self.data_path(relative)
        if target.is_file():
            target.unlink()
            return True
        return False

    # -- journal (visible dans la console développeur) ---------------------------------------------
    def log(self, message: Any, level: str = "info") -> None:
        self._info.note_log(level, str(message))

    def debug(self, message: Any) -> None:
        self.log(message, "debug")

    def warn(self, message: Any) -> None:
        self.log(message, "warn")

    def error(self, message: Any) -> None:
        self.log(message, "error")
        from . import runtime
        runtime._dev_trace(self._info, str(message))

    # -- temps ------------------------------------------------------------------------------------
    def after(self, seconds: float, handler: Callable[[], None]) -> None:
        """Appelle `handler()` une fois, dans `seconds` s, sur le thread de l'interface. Annulé au déchargement."""
        self._timer(seconds, handler, repeat=False)

    def every(self, seconds: float, handler: Callable[[], None]) -> None:
        """Appelle `handler()` toutes les `seconds` s (au moins 0,2 s), sur le thread de l'interface.
        Arrêté au déchargement du plugin ; une erreur est notée, sans arrêter la répétition."""
        self._timer(max(0.2, float(seconds)), handler, repeat=True)

    def _timer(self, seconds: float, handler: Callable[[], None], repeat: bool) -> None:
        from . import runtime
        stop = threading.Event()
        info = self._info
        self._track(stop.set)

        def fire() -> None:
            if stop.is_set():
                return
            try:
                handler()
            except Exception as exc:  # noqa: BLE001
                info.note_error(f"minuterie : {exc}")

        def loop() -> None:
            while not stop.wait(seconds):
                host = runtime.get_ui_host()
                (host.post(fire) if host is not None else fire())
                if not repeat:
                    return

        threading.Thread(target=loop, daemon=True, name=f"plugin-timer-{info.id}").start()

    # -- interface : plus de points d'accroche (permission « ui ») ----------------------------------
    def add_shortcut(self, sequence: str, handler: Callable, description: str = "") -> None:
        """Raccourci clavier global (ex. « Ctrl+Alt+N »). Retiré au déchargement."""
        self._host().add_shortcut(self._info, sequence, self._wrap(handler), description)

    def add_dock(self, title: str, factory: Callable[[Any], Any], area: str = "right", icon: str = "") -> None:
        """Panneau flottant/ancrable (QDockWidget) à gauche, à droite, en haut ou en bas de la fenêtre."""
        if area not in ("left", "right", "top", "bottom"):
            raise self._error("add_dock : area vaut left, right, top ou bottom.")
        self._host().add_dock(self._info, title, factory, area, icon)

    def add_palette_command(self, label: str, handler: Callable) -> None:
        """Commande dans la palette (Ctrl+K), préfixée du nom du plugin."""
        self._host()
        from . import runtime
        entry = (self._info, str(label)[:80], self._wrap(handler))
        runtime._palette.append(entry)
        self._track(lambda: runtime._palette.remove(entry) if entry in runtime._palette else None)

    def pick_file(self, title: str = "Choisir un fichier", start: str = "", filter: str = "") -> str | None:  # noqa: A002
        return self._host().pick_path("file", title, start, filter)

    def pick_folder(self, title: str = "Choisir un dossier", start: str = "") -> str | None:
        return self._host().pick_path("dir", title, start, "")

    def pick_save_file(self, title: str = "Enregistrer sous", start: str = "", filter: str = "") -> str | None:  # noqa: A002
        return self._host().pick_path("save", title, start, filter)

    def ask_choice(self, title: str, label: str, choices: list[str], default: int = 0) -> str | None:
        return self._host().ask_choice(title, label, [str(c) for c in choices], default)

    def ask_number(self, title: str, label: str, default: float = 0, min: float = -1e9, max: float = 1e9,  # noqa: A002
                   decimals: int = 0) -> float | int | None:
        return self._host().ask_number(title, label, default, min, max, decimals)

    def show_markdown(self, title: str, markdown: str) -> None:
        """Fenêtre de lecture : Markdown (titres, listes, code, tableaux, liens http/https) rendu par Voktora."""
        self._host().show_markdown(title, markdown)

    def open_url(self, url: str) -> None:
        """Ouvre une adresse http(s):// dans le navigateur (confirmé)."""
        host = self._host()
        if not str(url).startswith(("http://", "https://")):
            raise self._error("open_url : http:// ou https:// uniquement.")
        if not self._confirm_security("Ouvrir un lien", str(url)):
            return
        host.open_url(str(url))

    def clipboard_text(self) -> str:
        self._require("clipboard")
        return self._host().clipboard_get()

    def set_clipboard_text(self, text: str) -> None:
        self._require("clipboard")
        self._host().clipboard_set(str(text))

    # -- système -------------------------------------------------------------------------------------
    def system_info(self, processes: int = 0) -> dict:
        """Processeur (%), mémoire, disques, charge ; `processes` > 0 : les plus gourmands (si psutil)."""
        self._require("system")
        import sysinfo
        return sysinfo.snapshot(processes)

    # -- fichiers de vos projets --------------------------------------------------------------------
    def _project_file(self, project: str | Path, relative: str) -> Path:
        root = Path(project).resolve()
        if not any(Path(p.get("path", "")).resolve() == root for p in core.list_projects()):
            raise self._error("Ce dossier n'est pas un projet enregistré dans Voktora.")
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise self._error(f"Chemin refusé : {relative}")
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            raise self._error(f"Chemin refusé : {relative}")
        return target

    def project_files(self, project: str | Path, pattern: str = "*", limit: int = 2000) -> list[str]:
        """Fichiers d'un projet correspondant à `pattern` (glob, ex. « **/*.py »), chemins relatifs."""
        self._require("files")
        root = self._project_file(project, "")
        skip = {".git", "node_modules", "target", "__pycache__", ".venv", "venv"}
        out: list[str] = []
        for path in root.glob(pattern):
            rel = path.relative_to(root)
            if path.is_file() and not skip & set(rel.parts):
                out.append(rel.as_posix())
                if len(out) >= limit:
                    break
        return sorted(out)

    def project_read_text(self, project: str | Path, relative: str, max_bytes: int = 5_000_000) -> str:
        self._require("files")
        path = self._project_file(project, relative)
        if path.stat().st_size > max_bytes:
            raise self._error(f"Fichier trop volumineux (> {max_bytes} octets).")
        return path.read_text(encoding="utf-8", errors="replace")

    def project_write_text(self, project: str | Path, relative: str, text: str) -> None:
        """Écrit un fichier d'un projet (permission « files.write », confirmé à chaque écriture)."""
        self._require("files.write")
        path = self._project_file(project, relative)
        if not self._confirm_security("Écrire un fichier", f"{path}\n({len(text)} caractères)"):
            raise self._error("Écriture refusée par l'utilisateur.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    # -- assistant IA --------------------------------------------------------------------------------
    def register_ai_tool(self, name: str, description: str, handler: Callable[[dict], Any],
                         params: dict[str, str] | None = None, writes: bool = False) -> None:
        """Ajoute un outil à l'assistant IA. `handler(args: dict)` retourne du texte ou du JSON. L'assistant demande
        toujours l'accord de l'utilisateur pour les outils de plugin (jamais « automatique » si `writes`)."""
        self._require("ai.tools")
        import re as _re
        if not _re.match(r"^[a-z][a-z0-9_]{1,40}$", name):
            raise self._error("Nom d'outil : minuscules, chiffres et _ (2 à 41 caractères).")
        from . import runtime
        spec = {"name": f"{self._info.id.replace('-', '_')}_{name}", "description": str(description)[:300],
                "params": dict(params or {}), "handler": handler, "writes": bool(writes)}
        entry = (self._info, spec)
        runtime._ai_tools.append(entry)
        self._track(lambda: runtime._ai_tools.remove(entry) if entry in runtime._ai_tools else None)
