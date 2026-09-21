"""
Voktora — core.drives
Disques disponibles et dossier racine des projets.
"""

from __future__ import annotations

import os
import string
from pathlib import Path

from . import config_store, constants

# ──────────────────────────────────────────────
# DISQUES — Windows + Linux
# ──────────────────────────────────────────────

def get_available_drives() -> list:
    """
    Retourne les emplacements de stockage disponibles.
    Windows : lettres de lecteurs amovibles/secondaires.
    Linux   : répertoires courants (/home/user, /media/..., etc.).
    """
    if constants.IS_WINDOWS:
        system_drive = os.environ.get("SYSTEMDRIVE", "C:").upper().rstrip("\\")
        drives = []
        for letter in string.ascii_uppercase:
            drive = f"{letter}:"
            if drive.upper() == system_drive.upper():
                continue
            try:
                if os.path.exists(drive + "\\"):
                    drives.append(drive)
            except OSError:
                pass
        return drives
    else:
        # Linux : on retourne le home + les points de montage courants
        locations = []
        home = Path.home()
        if home.exists():
            locations.append(str(home))
        for mount_base in [Path("/media"), Path("/mnt"), Path("/run/media")]:
            if mount_base.exists():
                try:
                    for user_dir in mount_base.iterdir():
                        if user_dir.is_dir():
                            for device in user_dir.iterdir():
                                if device.is_dir():
                                    locations.append(str(device))
                            # Aussi le dossier direct (ex: /mnt/usb)
                            if not list(user_dir.iterdir()):
                                pass
                            else:
                                locations.append(str(user_dir))
                except OSError:
                    pass
        # Dédupliquer et limiter
        seen = set()
        result = []
        for loc in locations:
            if loc not in seen:
                seen.add(loc)
                result.append(loc)
        return result[:8]  # Maximum 8 emplacements


# ──────────────────────────────────────────────
# CHEMIN CONTENEUR
# ──────────────────────────────────────────────

def get_projects_root(drive: str = "") -> Path:
    """Dossier dans lequel les nouveaux projets sont créés.

    Un dossier personnalisé (réglages de stockage) prime sur le disque choisi.
    """
    custom = config_store.get_storage_config().get("projects_root")
    if custom:
        return Path(custom)
    if constants.IS_WINDOWS:
        return Path(f"{drive}\\{constants.CONTAINER_NAME}\\{constants.PROJECTS_DIR}")
    base = Path(drive) if drive and Path(drive).is_absolute() else Path.home()
    return base / constants.CONTAINER_NAME / constants.PROJECTS_DIR
