"""
Voktora — core.system
Ouverture de l'explorateur, du terminal et d'applications externes.

Sécurité : le nom d'un projet peut venir d'une archive ZIP ou d'un dossier
importé, donc être contrôlé par un tiers. Aucun chemin n'est donc jamais
interpolé dans une chaîne interprétée par un shell : il est toujours passé
comme argument distinct (argv) ou comme répertoire de travail (`cwd`).
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from . import constants

# ──────────────────────────────────────────────
# SYSTÈME — Windows + Linux
# ──────────────────────────────────────────────

def open_explorer(path: Path) -> None:
    """Ouvre l'explorateur de fichiers au chemin donné (Windows + Linux)."""
    if constants.IS_WINDOWS:
        subprocess.Popen(["explorer", str(path)])
    elif constants.IS_LINUX:
        # Essayer plusieurs gestionnaires de fichiers courants
        for fm in ["xdg-open", "nautilus", "dolphin", "thunar", "nemo", "pcmanfm"]:
            try:
                subprocess.Popen([fm, str(path)])
                return
            except FileNotFoundError:
                continue
    else:
        # macOS
        subprocess.Popen(["open", str(path)])


def open_terminal(path: Path) -> None:
    """Ouvre un terminal au chemin donné (Windows + Linux)."""
    if constants.IS_WINDOWS:
        # Nouvelle console cmd démarrée DANS le dossier : pas de « cd /d "…" » à échapper.
        subprocess.Popen(["cmd", "/k"], cwd=str(path), creationflags=subprocess.CREATE_NEW_CONSOLE)
    elif constants.IS_LINUX:
        # Essayer plusieurs émulateurs de terminal courants ; le dossier est
        # transmis soit en argument dédié, soit via cwd (jamais dans un `cd '…'`).
        terminals = [
            (["gnome-terminal", f"--working-directory={path}"], None),
            (["konsole", "--workdir", str(path)], None),
            (["xterm"], str(path)),
            (["xfce4-terminal", f"--working-directory={path}"], None),
            (["tilix", f"--working-directory={path}"], None),
            (["bash"], str(path)),
        ]
        for cmd, cwd in terminals:
            try:
                subprocess.Popen(cmd, cwd=cwd)
                return
            except FileNotFoundError:
                continue
    else:
        subprocess.Popen(["open", "-a", "Terminal", str(path)])


def open_vscode(path: Path) -> None:
    """Ouvre VS Code au chemin donné."""
    try:
        subprocess.Popen(["code", str(path)])
    except FileNotFoundError as exc:
        raise RuntimeError(
            "VS Code (commande 'code') est introuvable dans le PATH.\n"
            "Installez VS Code et activez la commande 'code' dans votre PATH."
        ) from exc


def build_app_command(cmd: str, path: Path) -> list[str] | str:
    """Construit la commande d'une application « ouvrir avec » SANS passer par un shell.

    `cmd` peut contenir {path}. Sous POSIX, le modèle est découpé avec shlex puis
    {path} est substitué dans chaque argument : le chemin reste UN argument,
    quels que soient les caractères qu'il contient. Sous Windows (CreateProcess
    attend une ligne de commande), le chemin est protégé avec list2cmdline.
    """
    if constants.IS_WINDOWS:
        quoted = subprocess.list2cmdline([str(path)])
        return cmd.replace("{path}", quoted) if "{path}" in cmd else f"{cmd} {quoted}"
    argv = shlex.split(cmd)
    if any("{path}" in arg for arg in argv):
        return [arg.replace("{path}", str(path)) for arg in argv]
    return [*argv, str(path)]


def open_app_at_path(cmd: str, path: Path) -> None:
    """
    Ouvre une application personnalisée avec le chemin projet.
    La commande peut contenir {path} comme placeholder.
    Ex : cmd = "code {path}"  →  code /home/user/MonProjet
    """
    subprocess.Popen(build_app_command(cmd, path))


def run_project_builder(path: Path) -> None:
    if constants.IS_WINDOWS:
        try:
            cmd = [constants.PROJECT_BUILDER, f"--path={str(path)}"]
            subprocess.Popen(cmd, cwd=str(path))
        except (OSError, subprocess.SubprocessError):
            cmd = (f'start "ProjectsBuilder" cmd /k '
                   f'"cd /d "{path}" && "{constants.PROJECT_BUILDER}""')
            subprocess.Popen(cmd, shell=True, cwd=str(path))
    else:
        raise RuntimeError("Project Builder n'est disponible que sous Windows.")


def open_url_in_browser(url: str) -> None:
    import webbrowser
    webbrowser.open(url)


