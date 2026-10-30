"""
snapshots.py — Snapshot / Restore de projets Voktora
Capture l'état complet d'un projet (fichiers + métadonnées config)
dans un .snap (zip structuré) et permet de le restaurer.
"""

from __future__ import annotations

import json
import os
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

def create(project_path: Path, label: str = "",
           on_progress: core.ProgressCallback | None = None,
           cancel: core.CancelCheck | None = None) -> Path:
    """
    Crée un snapshot du projet dans data/snapshots/<project>/.
    Retourne le chemin du fichier .snap créé. Écrit dans un fichier temporaire puis
    renomme : un snapshot annulé ou interrompu ne laisse jamais d'archive tronquée.
    """
    archive = core.archive
    snap_dir = _snaps_dir(project_path)
    snap_dir.mkdir(parents=True, exist_ok=True)

    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    name  = f"{project_path.name}_{ts}{SNAP_EXT}"

    manifest = {
        "version":    1,
        "project":    project_path.name,
        "timestamp":  ts,
        "label":      label or ts,
        "project_path": str(project_path),
    }
    _count, total = archive._tree_size(project_path)
    tracker = archive.ProgressTracker(total, on_progress)

    def _write(zf: zipfile.ZipFile) -> None:
        zf.writestr(SNAP_MANIFEST, json.dumps(manifest, indent=2))
        for root, dirnames, filenames in os.walk(project_path):
            rel_root = Path(root).relative_to(project_path).as_posix()
            # Exclure les objets git lourds (comparaison par segments : fonctionne aussi sous Windows).
            if rel_root in (".git/objects", ".git/lfs"):
                dirnames[:] = []
                continue
            dirnames.sort()
            for filename in sorted(filenames):
                archive._check_cancel(cancel)
                full = Path(root) / filename
                if full.is_symlink():          # jamais de contenu extérieur au projet dans un snapshot
                    continue
                rel = full.relative_to(project_path).as_posix()
                arc = SNAP_DATA_DIR + rel
                try:
                    if rel == ".git/config":
                        # Jamais d'identifiants (ancien remote « https://user:token@… ») dans un snapshot.
                        data = core.strip_git_credentials(full.read_bytes())
                        zf.writestr(arc, data)
                        tracker.advance(len(data), rel)
                    else:
                        zinfo = zipfile.ZipInfo.from_file(full, arc)
                        stored = full.suffix.lower() in archive._ALREADY_COMPRESSED
                        zinfo.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
                        buffer = bytearray(archive._CHUNK)
                        view = memoryview(buffer)
                        with open(full, "rb") as src, \
                                zf.open(zinfo, "w", force_zip64=zinfo.file_size > 2**30) as dst:
                            while (read := src.readinto(buffer)):
                                dst.write(view[:read])
                                tracker.advance(read, rel)
                                archive._check_cancel(cancel)
                except OSError:
                    continue                   # fichier verrouillé ou disparu : on continue

    out = archive.write_zip_atomically(snap_dir / name, _write)
    tracker.finish(out.name)
    return out


# ── Restauration ──────────────────────────────────────────────────────────────

def restore(snap_path: Path, target_path: Path, overwrite: bool = False,
            on_progress: core.ProgressCallback | None = None,
            cancel: core.CancelCheck | None = None) -> Path:
    """
    Restaure un snapshot dans `target_path`.
    Si `target_path` existe et `overwrite` est False → lève FileExistsError.

    Sécurité : un snapshot est une entrée non fiable (il peut venir d'un projet partagé). Chaque
    nom de membre est validé (pas de « .. », pas de chemin absolu), les liens symboliques sont
    ignorés et l'extraction se fait dans un dossier temporaire : l'ancien contenu n'est remplacé
    qu'une fois le snapshot entièrement et correctement extrait.
    """
    archive = core.archive
    snap_path, target_path = Path(snap_path), Path(target_path)
    if target_path.exists() and not overwrite:
        raise FileExistsError(f"{target_path} existe déjà.")

    try:
        zf = zipfile.ZipFile(snap_path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise core.ArchiveError(f"Snapshot illisible : {exc}") from exc

    with zf:
        members = [m for m in zf.infolist()
                   if m.filename.startswith(SNAP_DATA_DIR) and len(m.filename) > len(SNAP_DATA_DIR)]
        total = sum(m.file_size for m in members if not m.is_dir())
        archive._ensure_free_space(target_path.parent, total)

        staging = archive._new_staging_dir(target_path.parent)
        tracker = archive.ProgressTracker(total, on_progress)
        try:
            staging_real = staging.resolve()
            for member in members:
                archive._check_cancel(cancel)
                parts = archive._member_parts(member.filename[len(SNAP_DATA_DIR):])
                if not parts or archive._is_symlink(member):
                    continue
                out = staging.joinpath(*parts)
                if not out.resolve().is_relative_to(staging_real):
                    raise core.ArchiveError(f"Chemin hors du dossier cible : {member.filename!r}")
                if member.is_dir():
                    out.mkdir(parents=True, exist_ok=True)
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                archive._extract_member(zf, member, out, tracker, cancel)
            _swap_in(staging, target_path)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    tracker.finish(target_path.name)
    return target_path


def _swap_in(staging: Path, target: Path) -> None:
    """Remplace `target` par `staging` en gardant l'ancien dossier jusqu'au succès du renommage."""
    if not target.exists():
        staging.rename(target)
        return
    backup = target.with_name(f"{target.name}.voktora-old")
    shutil.rmtree(backup, ignore_errors=True)
    target.rename(backup)
    try:
        staging.rename(target)
    except OSError:
        backup.rename(target)      # échec : on remet l'ancien contenu en place
        raise
    shutil.rmtree(backup, ignore_errors=True)


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

    La comparaison utilise la taille et le CRC32 déjà stockés dans chaque archive : aucun
    fichier n'est décompressé ni chargé en mémoire, même pour des snapshots de plusieurs Go.
    """
    def _files(snap: Path) -> dict[str, tuple[int, int]]:
        out = {}
        with zipfile.ZipFile(snap, "r") as zf:
            for m in zf.infolist():
                if m.filename.startswith(SNAP_DATA_DIR) and not m.is_dir():
                    out[m.filename[len(SNAP_DATA_DIR):]] = (m.file_size, m.CRC)
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
