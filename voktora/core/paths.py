"""
Voktora — core.paths
Fragment de core.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

from . import constants


@functools.cache
def get_app_dir() -> Path:
    try:
        _ = __compiled__
        return Path(sys.executable).parent
    except NameError:
        return Path(__file__).resolve().parent.parent


@functools.cache
def get_data_dir() -> Path:
    # Sur Linux, si l'app est installée dans /opt ou /usr (non accessible en écriture),
    # on utilise le répertoire XDG standard : ~/.local/share/voktora/
    if constants.IS_LINUX:
        app_dir = get_app_dir()
        # Installé système (/opt/*, /usr/*)  → données dans ~/.local/share/voktora
        if str(app_dir).startswith("/opt/") or str(app_dir).startswith("/usr/"):
            xdg_data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            d = xdg_data / "voktora"
            d.mkdir(parents=True, exist_ok=True)
            return d

    # Windows ou Linux dev (dossier local) → data/ à côté de l'exe
    d = get_app_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@functools.cache
def get_backups_dir() -> Path:
    b = get_data_dir() / constants.BACKUPS_DIRNAME
    b.mkdir(parents=True, exist_ok=True)
    return b


@functools.cache
def get_config_path() -> Path:
    return get_data_dir() / constants.CONFIG_FILENAME


def ensure_app_dirs() -> None:
    """Crée tous les dossiers nécessaires au démarrage (Windows + Linux)."""
    dirs = [get_data_dir(), get_backups_dir()]
    # Les thèmes sont dans le dossier de l'app (lecture seule sur Linux installé)
    # On ne tente pas de les créer si c'est /opt/
    themes_dir = get_app_dir() / "themes"
    if not (constants.IS_LINUX and (str(get_app_dir()).startswith("/opt/") or
                          str(get_app_dir()).startswith("/usr/"))):
        dirs.append(themes_dir)
    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


# ──────────────────────────────────────────────
# VALIDATION DES NOMS
# ──────────────────────────────────────────────

def validate_name(name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Le nom ne peut pas être vide.")
    if len(name) > constants.MAX_NAME_LENGTH:
        raise ValueError(f"Le nom est trop long ({len(name)} caractères, maximum {constants.MAX_NAME_LENGTH}).")
    if constants._NAME_FORBIDDEN_RE.search(name):
        raise ValueError(f"Le nom « {name} » contient des caractères non autorisés.")


# ──────────────────────────────────────────────
# CONFIG GLOBALE
