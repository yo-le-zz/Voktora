"""Aides de test pour les plugins du marketplace : paquet factice (imports relatifs) et API simulée (synchrone)."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

PLUGINS = Path(__file__).resolve().parent.parent / "marketplace" / "plugins"


def load_plugin(plugin_id: str):
    """Importe le plugin comme paquet `plg_<id>` et renvoie son module `main`."""
    name = "plg_" + plugin_id.replace("-", "_")
    for n in [n for n in sys.modules if n == name or n.startswith(name + ".")]:
        del sys.modules[n]
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(PLUGINS / plugin_id)]
    sys.modules[name] = pkg
    return importlib.import_module(name + ".main")


def submodule(plugin_id: str, dotted: str):
    return importlib.import_module("plg_" + plugin_id.replace("-", "_") + "." + dotted)


class Options:
    def __init__(self):
        self.values, self.defaults, self.groups = {}, {}, []

    def group(self, name):
        self.groups.append(name)

    def _add(self, key, *args, default=None, **_):
        self.defaults[key] = default

    def add_bool(self, key, label, default=False, **k): self.defaults[key] = default
    def add_text(self, key, label, default="", **k): self.defaults[key] = default
    def add_int(self, key, label, default=0, **k): self.defaults[key] = default
    def add_float(self, key, label, default=0.0, **k): self.defaults[key] = default
    def add_choice(self, key, label, choices, default=None, **k): self.defaults[key] = default if default is not None else choices[0]
    def add_multiline(self, key, label, default="", **k): self.defaults[key] = default
    def add_color(self, key, label, default="#89b4fa", **k): self.defaults[key] = default
    def add_shortcut(self, key, label, default="", **k): self.defaults[key] = default
    def add_path(self, key, label, default="", **k): self.defaults[key] = default
    def add_button(self, *a, **k): pass
    def on_change(self, cb): self.callback = cb

    def get(self, key, default=None):
        return self.values.get(key, self.defaults.get(key, default))

    def set(self, key, value):
        self.values[key] = value
        cb = getattr(self, "callback", None)
        if cb:
            cb(key, value)


class Settings:
    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class StubApi:
    """Enregistre ce que le plugin déclare ; `run_async` s'exécute tout de suite."""

    def __init__(self, data_dir: Path, project: Path | None = None):
        self.options = Options()
        self.settings = Settings()
        self._data = data_dir
        self.project = project
        self.tabs, self.menu, self.palette, self.status, self.toolbar, self.hooks, self.context = [], [], [], [], [], {}, []
        self.notices, self.clipboard, self.dialogs, self.timers, self.shortcuts = [], "", [], [], []

    def data_path(self, relative=""):
        path = self._data / relative if relative else self._data
        return path

    def add_project_tab(self, title, factory, icon=""): self.tabs.append((title, factory))
    def add_menu_action(self, menu, label, handler, **k): self.menu.append((menu, label, handler, k))
    def add_palette_command(self, label, handler): self.palette.append((label, handler))
    def add_status_widget(self, factory): self.status.append(factory)
    def add_toolbar_button(self, label, handler, **k): self.toolbar.append((label, handler))
    def add_context_action(self, scope, label, handler, **k): self.context.append((scope, label, handler))
    def add_shortcut(self, seq, handler, description=""): self.shortcuts.append((seq, handler))
    def on(self, event, handler): self.hooks.setdefault(event, []).append(handler)
    def run_async(self, work, done=None, fail=None):
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001
            if fail:
                fail(exc)
                return
            raise
        if done:
            done(result)

    def every(self, seconds, handler): self.timers.append((seconds, handler))
    def notify(self, message, ms=3000): self.notices.append(message)
    def show_markdown(self, title, markdown): self.dialogs.append((title, markdown))
    def set_clipboard_text(self, text): self.clipboard = text
    def clipboard_text(self): return self.clipboard
    def current_project(self): return self.project
    def icon(self, name):
        from PySide6.QtGui import QIcon
        return QIcon()

    def run(self, argv, cwd=None, timeout=30):
        import subprocess
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
        return p.returncode, p.stdout + p.stderr

    def project_files(self, project, pattern="*", limit=2000):
        root = Path(project)
        return [f.relative_to(root).as_posix() for f in sorted(root.rglob(pattern)) if f.is_file()][:limit]

    def project_read_text(self, project, relative, max_bytes=5_000_000):
        return (Path(project) / relative).read_text(encoding="utf-8")

    def project_write_text(self, project, relative, text):
        (Path(project) / relative).write_text(text, encoding="utf-8")

    def open_url(self, url): self.opened = url
    def ask_choice(self, title, label, choices, default=0): return self.choice if getattr(self, "choice", None) in choices else None
    def log(self, *a, **k): pass
    def main_window(self): return None
    def confirm(self, *a, **k): return True
