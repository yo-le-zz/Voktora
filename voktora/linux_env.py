"""
Voktora — linux_env.py
Compatibilité avec la diversité du monde Linux : distributions (Debian, Fedora, Arch, openSUSE,
Alpine, Void, Gentoo, NixOS…), environnements de bureau (GNOME, KDE, Xfce, Cinnamon, MATE, LXQt,
LXDE, Budgie, COSMIC, Pantheon, Deepin…), gestionnaires de fenêtres seuls (Hyprland, Sway, i3…) et
sessions Wayland ou X11.

Ce module ne dépend ni de Qt ni de core : il peut tourner avant la création de QApplication et se
teste avec de faux environnements (tout prend `env` / `read_file` en paramètre).
"""

from __future__ import annotations

import ctypes.util
import os
import shlex
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

IS_LINUX = sys.platform.startswith("linux")

# ──────────────────────────────────────────────
# DÉTECTION
# ──────────────────────────────────────────────

_FAMILIES = {
    "debian": "debian", "ubuntu": "debian", "linuxmint": "debian", "pop": "debian", "raspbian": "debian",
    "fedora": "fedora", "rhel": "fedora", "centos": "fedora", "rocky": "fedora", "almalinux": "fedora",
    "nobara": "fedora", "bazzite": "fedora",
    "arch": "arch", "manjaro": "arch", "endeavouros": "arch", "cachyos": "arch", "garuda": "arch",
    "opensuse": "suse", "suse": "suse", "sles": "suse",
    "alpine": "alpine", "void": "void", "gentoo": "gentoo", "nixos": "nixos",
}
_DESKTOP_ALIASES = {
    "x-cinnamon": "cinnamon", "ubuntu:gnome": "gnome", "unity": "unity", "plasma": "kde", "kde-plasma": "kde",
    "lxqt": "lxqt", "lxde": "lxde", "xfce": "xfce", "mate": "mate", "budgie": "budgie", "budgie:gnome": "budgie",
    "pantheon": "pantheon", "deepin": "deepin", "cosmic": "cosmic", "gnome": "gnome", "kde": "kde",
    "cinnamon": "cinnamon", "hyprland": "hyprland", "sway": "sway", "i3": "i3", "bspwm": "bspwm",
    "niri": "niri", "river": "river", "dwm": "dwm", "awesome": "awesome", "openbox": "openbox",
}


def parse_os_release(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        try:
            parts = shlex.split(value)
        except ValueError:
            parts = [value.strip("\"'")]
        data[key] = parts[0] if parts else ""
    return data


def detect_distro(read_file: Callable[[str], str] | None = None) -> dict[str, str]:
    """{id, name, version, family} de la distribution (« other » si inconnue)."""
    def default_read(path: str) -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")

    read = read_file or default_read
    data: dict[str, str] = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            data = parse_os_release(read(path))
            break
        except OSError:
            continue
    distro_id = data.get("ID", "").lower()
    candidates = [distro_id, *data.get("ID_LIKE", "").lower().split()]
    family = next((_FAMILIES[c] for c in candidates if c in _FAMILIES), "other")
    return {"id": distro_id or "linux", "name": data.get("PRETTY_NAME") or data.get("NAME") or "Linux",
            "version": data.get("VERSION_ID", ""), "family": family}


def detect_desktop(env: Mapping[str, str] | None = None) -> str:
    """Environnement de bureau en minuscules (« gnome », « kde », « xfce »… ou « unknown »)."""
    env = os.environ if env is None else env
    raw = ":".join(filter(None, (env.get("XDG_CURRENT_DESKTOP"), env.get("XDG_SESSION_DESKTOP"),
                                 env.get("DESKTOP_SESSION")))).lower()
    for token in raw.split(":"):
        token = token.strip()
        if token in _DESKTOP_ALIASES:
            return _DESKTOP_ALIASES[token]
    for token in raw.replace("-", ":").split(":"):
        if token in _DESKTOP_ALIASES:
            return _DESKTOP_ALIASES[token]
    return "unknown"


def detect_session(env: Mapping[str, str] | None = None) -> str:
    """« wayland », « x11 » ou « none » (console, SSH sans affichage)."""
    env = os.environ if env is None else env
    declared = env.get("XDG_SESSION_TYPE", "").lower()
    if declared in ("wayland", "x11"):
        return declared
    if env.get("WAYLAND_DISPLAY"):
        return "wayland"
    if env.get("DISPLAY"):
        return "x11"
    return "none"


# ──────────────────────────────────────────────
# PRÉPARATION DE QT (avant QApplication)
# ──────────────────────────────────────────────

def prepare_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    """Règle les variables d'environnement utiles à Qt ; retourne ce qui a été ajouté.

    Ne touche à rien si l'utilisateur a déjà fixé la variable, et n'agit que sous Linux.
    Sous Wayland, Qt essaie wayland puis retombe sur xcb (XWayland) au lieu d'échouer si le plugin
    wayland manque ; sous X11, l'inverse.
    """
    env = os.environ if env is None else env
    added: dict[str, str] = {}
    if not IS_LINUX:
        return added
    if "QT_QPA_PLATFORM" not in env:
        session = detect_session(env)
        if session == "wayland":
            added["QT_QPA_PLATFORM"] = "wayland;xcb"
        elif session == "x11":
            added["QT_QPA_PLATFORM"] = "xcb;wayland"
    # Pas de barre de titre dessinée à la main sous GNOME/Wayland : on laisse le compositeur décider.
    for key, value in added.items():
        env[key] = value
    return added


def missing_system_libs(env: Mapping[str, str] | None = None) -> list[str]:
    """Bibliothèques système nécessaires à Qt (plugin xcb) introuvables sur cette machine."""
    if not IS_LINUX:
        return []
    env = os.environ if env is None else env
    if detect_session(env) == "wayland" and "xcb" not in env.get("QT_QPA_PLATFORM", "xcb"):
        return []
    return [lib for lib in ("xcb-cursor", "xkbcommon-x11") if ctypes.util.find_library(lib) is None]


_INSTALL_HINTS = {
    "debian": "sudo apt install libxcb-cursor0 libxkbcommon-x11-0",
    "fedora": "sudo dnf install xcb-util-cursor libxkbcommon-x11",
    "arch": "sudo pacman -S xcb-util-cursor libxkbcommon-x11",
    "suse": "sudo zypper install libxcb-cursor0 libxkbcommon-x11-0",
    "alpine": "sudo apk add xcb-util-cursor libxkbcommon-x11",
    "void": "sudo xbps-install xcb-util-cursor libxkbcommon-x11",
    "gentoo": "sudo emerge x11-libs/xcb-util-cursor x11-libs/libxkbcommon",
    "nixos": "ajoutez xorg.xcbutilcursor et libxkbcommon à vos paquets système",
}


def install_hint(family: str) -> str:
    return _INSTALL_HINTS.get(family, "installez les bibliothèques xcb-cursor et xkbcommon-x11 de votre distribution")


# ──────────────────────────────────────────────
# GESTIONNAIRES DE FICHIERS ET TERMINAUX
# ──────────────────────────────────────────────

_FILE_MANAGERS_BY_DESKTOP = {
    "gnome": ["nautilus"], "budgie": ["nautilus"], "unity": ["nautilus"], "kde": ["dolphin"],
    "xfce": ["thunar"], "cinnamon": ["nemo"], "mate": ["caja"], "lxqt": ["pcmanfm-qt"], "lxde": ["pcmanfm"],
    "cosmic": ["cosmic-files"], "pantheon": ["io.elementary.files"], "deepin": ["dde-file-manager"],
}
_FILE_MANAGERS_GENERIC = ["nautilus", "dolphin", "thunar", "nemo", "caja", "pcmanfm-qt", "pcmanfm",
                          "cosmic-files", "krusader", "spacefm", "ranger-gui"]


def file_manager_commands(path: Path, env: Mapping[str, str] | None = None) -> list[list[str]]:
    """Commandes à essayer, dans l'ordre : standard freedesktop d'abord, puis le gestionnaire du bureau."""
    desktop = detect_desktop(env)
    names = [*_FILE_MANAGERS_BY_DESKTOP.get(desktop, []), *_FILE_MANAGERS_GENERIC]
    seen: set[str] = set()
    commands = [["xdg-open", str(path)], ["gio", "open", str(path)]]
    for name in names:
        if name not in seen:
            seen.add(name)
            commands.append([name, str(path)])
    return commands


# (programme, arguments avant le dossier ; None = le dossier est donné par `cwd` seulement)
_TERMINAL_FLAGS: dict[str, list[str] | None] = {
    "gnome-terminal": ["--working-directory={}"], "konsole": ["--workdir", "{}"],
    "xfce4-terminal": ["--working-directory={}"], "mate-terminal": ["--working-directory={}"],
    "tilix": ["--working-directory={}"], "terminator": ["--working-directory={}"],
    "lxterminal": ["--working-directory={}"], "qterminal": ["--workdir", "{}"],
    "kitty": ["--directory", "{}"], "alacritty": ["--working-directory", "{}"],
    "wezterm": ["start", "--cwd", "{}"], "foot": ["--working-directory={}"],
    "ptyxis": None, "kgx": None, "cosmic-term": None, "io.elementary.terminal": None,
    "deepin-terminal": None, "xterm": None, "urxvt": None, "st": None, "sakura": None, "bash": None,
}
_TERMINALS_BY_DESKTOP = {
    "gnome": ["ptyxis", "gnome-terminal", "kgx"], "budgie": ["gnome-terminal", "ptyxis"],
    "unity": ["gnome-terminal"], "kde": ["konsole"], "xfce": ["xfce4-terminal"],
    "cinnamon": ["gnome-terminal"], "mate": ["mate-terminal"], "lxqt": ["qterminal"],
    "lxde": ["lxterminal"], "cosmic": ["cosmic-term"], "pantheon": ["io.elementary.terminal"],
    "deepin": ["deepin-terminal"],
    "hyprland": ["kitty", "foot", "alacritty"], "sway": ["foot", "alacritty", "kitty"],
    "i3": ["alacritty", "kitty"],
}
_TERMINALS_GENERIC = ["gnome-terminal", "konsole", "ptyxis", "xfce4-terminal", "kitty", "alacritty", "wezterm",
                      "foot", "tilix", "terminator", "mate-terminal", "qterminal", "lxterminal", "kgx",
                      "cosmic-term", "urxvt", "st", "sakura", "xterm"]


def terminal_commands(path: Path, env: Mapping[str, str] | None = None) -> list[tuple[list[str], str | None]]:
    """(commande, cwd) à essayer dans l'ordre. Le dossier n'est JAMAIS interpolé dans une chaîne shell :
    soit argument distinct, soit répertoire de travail du processus."""
    env = os.environ if env is None else env
    desktop = detect_desktop(env)
    directory = str(path)
    commands: list[tuple[list[str], str | None]] = []

    def add_program(program: str) -> None:
        flags = _TERMINAL_FLAGS.get(program)
        if flags:
            commands.append(([program, *(f.replace("{}", directory) for f in flags)], None))
        else:
            commands.append(([program], directory))

    user_terminal = env.get("TERMINAL", "").strip()
    if user_terminal:
        try:
            parts = shlex.split(user_terminal)
        except ValueError:
            parts = []
        if parts:
            known = _TERMINAL_FLAGS.get(Path(parts[0]).name)
            commands.append(([*parts, *(f.replace("{}", directory) for f in known)], None) if known
                            else (parts, directory))
    commands.append((["xdg-terminal-exec"], directory))
    seen: set[str] = set()
    for program in [*_TERMINALS_BY_DESKTOP.get(desktop, []), *_TERMINALS_GENERIC]:
        if program not in seen:
            seen.add(program)
            add_program(program)
    commands.append((["x-terminal-emulator"], directory))
    commands.append((["bash"], directory))
    return commands


def summary(env: Mapping[str, str] | None = None) -> str:
    """Ligne de diagnostic : « Fedora Linux 43 (famille fedora) — GNOME / wayland »."""
    distro = detect_distro()
    return f"{distro['name']} (famille {distro['family']}) — {detect_desktop(env)} / {detect_session(env)}"
