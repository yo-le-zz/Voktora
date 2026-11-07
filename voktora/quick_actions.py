"""
Voktora — quick_actions
Actions rapides : commandes personnelles lancées sur un projet en un clic (VS Code, terminal, build…).

Stockage : `app_config.quick_apps` (même clé qu'avant la 1.0.7, donc les actions déjà créées sont conservées).
Une action : {"name", "cmd", "icon", "terminal"}. `cmd` accepte {path} (dossier du projet) et {name}.
Aucun shell n'est utilisé : la commande est découpée (shlex) puis lancée directement, ce qui évite les
injections par un nom de projet contenant des caractères spéciaux.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import core

DEFAULT_ICON = "mdi:flash"
_TERMINALS = (
    ("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]), ("xfce4-terminal", ["-x"]),
    ("kitty", []), ("alacritty", ["-e"]), ("xterm", ["-e"]),
)


@dataclass
class QuickAction:
    name: str
    cmd: str
    icon: str = DEFAULT_ICON
    terminal: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "cmd": self.cmd, "icon": self.icon, "terminal": self.terminal}


def from_dict(raw: object) -> QuickAction | None:
    if not isinstance(raw, dict):
        return None
    name, cmd = str(raw.get("name", "")).strip(), str(raw.get("cmd", "")).strip()
    if not name or not cmd:
        return None
    return QuickAction(name=name, cmd=cmd, icon=str(raw.get("icon") or DEFAULT_ICON),
                       terminal=bool(raw.get("terminal", False)))


def load() -> list[QuickAction]:
    result, seen = [], set()
    for raw in core.get_quick_apps():
        action = from_dict(raw)
        if action and action.name.casefold() not in seen:
            seen.add(action.name.casefold())
            result.append(action)
    return result


def save(actions: list[QuickAction]) -> None:
    core.set_quick_apps([a.to_dict() for a in actions])


def validate(action: QuickAction, others: list[QuickAction] | None = None) -> str:
    """Message d'erreur, ou chaîne vide si l'action est valide."""
    if not action.name.strip():
        return "Donnez un nom à l'action."
    if not action.cmd.strip():
        return "Renseignez la commande."
    if any(o.name.casefold() == action.name.strip().casefold() for o in others or []):
        return f"Une action nommée « {action.name} » existe déjà."
    try:
        if not _split(action.cmd):
            return "Commande vide."
    except ValueError as exc:
        return f"Commande invalide : {exc}"
    return ""


def _split(cmd: str) -> list[str]:
    return shlex.split(cmd, posix=os.name != "nt")


def build_argv(action: QuickAction, project_path: Path | str) -> list[str]:
    """Arguments à exécuter. {path} / {name} remplacés APRÈS découpage (les espaces restent dans un seul argument)."""
    path = str(project_path)
    values = {"{path}": path, "{name}": Path(path).name}
    argv = []
    for part in _split(action.cmd):
        for key, value in values.items():
            part = part.replace(key, value)
        argv.append(part)
    if action.terminal:
        for exe, flag in _TERMINALS:
            found = shutil.which(exe)
            if found:
                return [found, *flag, *argv]
    return argv


def launch(action: QuickAction, project_path: Path | str) -> str:
    """Lance l'action. Retourne un message d'erreur, ou "" si le programme a démarré."""
    problem = validate(action)
    if problem:
        return problem
    try:
        argv = build_argv(action, project_path)
        kwargs = {"start_new_session": True} if os.name != "nt" else {"creationflags": 0x00000008}
        subprocess.Popen(argv, cwd=str(project_path), stdin=subprocess.DEVNULL,          # noqa: S603
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    except FileNotFoundError:
        return f"Programme introuvable : {argv[0] if argv else action.cmd}"
    except (OSError, ValueError) as exc:
        return str(exc)
    return ""


def suggestions() -> list[QuickAction]:
    """Actions proposées d'après les programmes réellement installés."""
    candidates = [
        ("VS Code", "code {path}", "mdi:microsoft-visual-studio-code", "code"),
        ("VSCodium", "codium {path}", "mdi:code-braces", "codium"),
        ("Zed", "zed {path}", "mdi:lightning-bolt", "zed"),
        ("PyCharm", "pycharm {path}", "mdi:language-python", "pycharm"),
        ("Nautilus", "nautilus {path}", "mdi:folder-open", "nautilus"),
        ("Dolphin", "dolphin {path}", "mdi:folder-open", "dolphin"),
        ("Lazygit", "lazygit", "mdi:git", "lazygit"),
        ("Terminal", "bash", "mdi:console", "bash"),
    ]
    return [QuickAction(n, c, i, terminal=(exe in {"lazygit", "bash"})) for n, c, i, exe in candidates
            if shutil.which(exe)]
