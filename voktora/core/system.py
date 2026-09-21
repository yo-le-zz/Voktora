"""
Voktora — core.system
Fragment de core.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

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
        subprocess.Popen(
            f'start "Voktora Terminal" cmd /k "cd /d "{path}""',
            shell=True,
        )
    elif constants.IS_LINUX:
        # Essayer plusieurs émulateurs de terminal courants
        terminals = [
            ["gnome-terminal", f"--working-directory={path}"],
            ["konsole", "--workdir", str(path)],
            ["xterm", "-e", f"cd '{path}' && bash"],
            ["xfce4-terminal", f"--working-directory={path}"],
            ["tilix", f"--working-directory={path}"],
            ["bash", "-c", f"cd '{path}' && bash"],
        ]
        for cmd in terminals:
            try:
                subprocess.Popen(cmd)
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


def open_app_at_path(cmd: str, path: Path) -> None:
    """
    Ouvre une application personnalisée avec le chemin projet.
    La commande peut contenir {path} comme placeholder.
    Ex : cmd = "code {path}"  →  code /home/user/MonProjet
    """
    full_cmd = cmd.replace("{path}", str(path)) if "{path}" in cmd else f"{cmd} {path}"
    subprocess.Popen(full_cmd, shell=True)


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


