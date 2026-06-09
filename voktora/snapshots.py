"""
snapshots.py — Snapshot / Restore de projets Voktora
Capture l'état complet d'un projet (fichiers + métadonnées config)
dans un .snap (zip structuré) et permet de le restaurer.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import core


SNAP_EXT      = ".snap"
SNAP_MANIFEST = "manifest.json"
SNAP_DATA_DIR = "files/"


@dataclass
class SnapInfo:
    path:      Path
    label:     str
    timestamp: str
    project:   str
    size_mb:   float


# ── Création ──────────────────────────────────────────────────────────────────

def create(project_path: Path, label: str = "") -> Path:
    """
    Crée un snapshot du projet dans data/snapshots/<project>/.
    Retourne le chemin du fichier .snap créé.
    """
    snap_dir = _snaps_dir(project_path)
    snap_dir.mkdir(parents=True, exist_ok=True)

    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    name  = f"{project_path.name}_{ts}{SNAP_EXT}"
    out   = snap_dir / name

    manifest = {
        "version":    1,
        "project":    project_path.name,
        "timestamp":  ts,
        "label":      label or ts,
        "project_path": str(project_path),
    }

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(SNAP_MANIFEST, json.dumps(manifest, indent=2))
        for f in project_path.rglob("*"):
            # Exclure .git internals lourds
            if ".git/objects" in str(f) or ".git/lfs" in str(f):
                continue
            if f.is_file():
                arc = SNAP_DATA_DIR + str(f.relative_to(project_path))
                try:
                    zf.write(f, arc)
                except (PermissionError, OSError):
                    pass

    return out


# ── Restauration ──────────────────────────────────────────────────────────────

def restore(snap_path: Path, target_path: Path,
            overwrite: bool = False) -> Path:
    """
    Restaure un snapshot dans `target_path`.
    Si `target_path` existe et `overwrite` est False → lève FileExistsError.
    """
    if target_path.exists() and not overwrite:
        raise FileExistsError(f"{target_path} existe déjà.")
    if target_path.exists():
        shutil.rmtree(target_path)
    target_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(snap_path, "r") as zf:
        for member in zf.infolist():
            if not member.filename.startswith(SNAP_DATA_DIR):
                continue
            rel = member.filename[len(SNAP_DATA_DIR):]
            if not rel:
                continue
            dest = target_path / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)

    return target_path


# ── Liste ─────────────────────────────────────────────────────────────────────

def list_snaps(project_path: Path) -> list[SnapInfo]:
    snap_dir = _snaps_dir(project_path)
    if not snap_dir.exists():
        return []
    snaps = []
    for f in sorted(snap_dir.glob(f"*{SNAP_EXT}"), reverse=True):
        try:
            with zipfile.ZipFile(f, "r") as zf:
                manifest = json.loads(zf.read(SNAP_MANIFEST))
        except Exception:
            manifest = {}
        snaps.append(SnapInfo(
            path      = f,
            label     = manifest.get("label", f.stem),
            timestamp = manifest.get("timestamp", ""),
            project   = manifest.get("project", project_path.name),
            size_mb   = round(f.stat().st_size / 1_048_576, 2),
        ))
    return snaps


def delete_snap(snap_path: Path) -> None:
    snap_path.unlink(missing_ok=True)


def diff_snaps(snap_a: Path, snap_b: Path) -> dict[str, str]:
    """
    Compare les fichiers entre deux snapshots.
    Retourne {"file.py": "added"|"removed"|"modified"}.
    """
    def _files(snap: Path) -> dict[str, bytes]:
        out = {}
        with zipfile.ZipFile(snap, "r") as zf:
            for m in zf.infolist():
                if m.filename.startswith(SNAP_DATA_DIR) and not m.is_dir():
                    rel = m.filename[len(SNAP_DATA_DIR):]
                    out[rel] = zf.read(m.filename)
        return out

    files_a = _files(snap_a)
    files_b = _files(snap_b)
    result  = {}
    for k in files_a:
        if k not in files_b:
            result[k] = "removed"
        elif files_a[k] != files_b[k]:
            result[k] = "modified"
    for k in files_b:
        if k not in files_a:
            result[k] = "added"
    return result


def _snaps_dir(project_path: Path) -> Path:
    return core.get_data_dir() / "snapshots" / project_path.name
