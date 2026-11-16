"""
Voktora — archiving (1.1.4) : archivage de projets.
Archiver = créer un ZIP vérifié (intégrité + SHA-256) dans `<données>/archives/`, marquer le projet « archivé » (il disparaît de la
liste principale) et, SEULEMENT si on le demande ET après vérification, supprimer le dossier d'origine. Restaurer = ré-extraire
(après vérification du SHA-256) et réafficher le projet. Rien n'est supprimé sans que l'archive ait été relue et validée.
"""

from __future__ import annotations

import hashlib
import shutil
import time
import zipfile
from pathlib import Path

import core


class ArchiveError(RuntimeError):
    pass


def archives_dir() -> Path:
    d = core.get_data_dir() / "archives"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _own_archive(value: str) -> Path:
    """Chemin d'archive tiré de la configuration : refusé s'il sort du dossier des archives (config modifiée ou synchronisée)."""
    path = Path(value or "")
    root = archives_dir().resolve()
    if not value or not path.resolve().is_relative_to(root):
        raise ArchiveError("Chemin d'archive hors du dossier des archives : refusé.")
    return path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_archive(zip_path: Path, sha256: str = "") -> None:
    if not zip_path.is_file():
        raise ArchiveError("Archive introuvable.")
    if sha256 and _sha256(zip_path) != sha256:
        raise ArchiveError("L'empreinte SHA-256 de l'archive ne correspond plus : archive modifiée ou corrompue.")
    try:
        with zipfile.ZipFile(zip_path) as z:
            bad = z.testzip()
    except zipfile.BadZipFile as exc:
        raise ArchiveError("Archive ZIP invalide.") from exc
    if bad:
        raise ArchiveError(f"Archive corrompue (fichier {bad}).")


def archive_project(path: Path | str, remove_folder: bool = False, on_progress=None) -> dict:
    folder = Path(path)
    entry = core.get_project(folder)
    if entry is None:
        raise ArchiveError("Projet inconnu.")
    if entry.get("archived"):
        raise ArchiveError("Ce projet est déjà archivé.")
    zip_path = core.export_to_zip(folder, archives_dir(), on_progress)
    try:
        verify_archive(zip_path)
    except ArchiveError:
        zip_path.unlink(missing_ok=True)
        raise
    digest = _sha256(zip_path)
    core.update_project(folder, archived=True, archive_path=str(zip_path), archive_sha256=digest, archived_at=int(time.time()),
                        archive_folder_removed=False)
    if remove_folder:
        verify_archive(zip_path, digest)                       # relecture juste avant la suppression
        shutil.rmtree(folder, ignore_errors=False)
        core.update_project(folder, archive_folder_removed=True)
    return core.get_project(folder) or {}


def list_archived() -> list[dict]:
    return [e for e in core.list_projects() if e.get("archived")]


def restore_project(path: Path | str, on_progress=None) -> Path:
    folder = Path(path)
    entry = core.get_project(folder)
    if entry is None or not entry.get("archived"):
        raise ArchiveError("Ce projet n'est pas archivé.")
    zip_path = _own_archive(entry.get("archive_path", ""))
    verify_archive(zip_path, entry.get("archive_sha256", ""))
    if entry.get("archive_folder_removed") or not folder.exists():
        from core import archive as arch
        if folder.exists():
            raise ArchiveError("Le dossier de destination existe déjà.")
        extracted = arch.extract_zip(zip_path, folder.parent, folder.name, on_progress)
        if Path(extracted) != folder:
            raise ArchiveError("Extraction inattendue.")
    core.update_project(folder, archived=False, archive_folder_removed=False)
    return folder


def delete_archive(path: Path | str) -> None:
    """Supprime l'archive ZIP ET la fiche du projet si son dossier n'existe plus (sinon le projet redevient normal)."""
    folder = Path(path)
    entry = core.get_project(folder) or {}
    if entry.get("archive_path"):
        _own_archive(entry["archive_path"]).unlink(missing_ok=True)
    if folder.exists():
        core.update_project(folder, archived=False, archive_path="", archive_sha256="", archive_folder_removed=False)
    else:
        core.forget_project(folder)
