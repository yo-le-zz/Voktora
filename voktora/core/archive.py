"""
Voktora — core.archive
Opérations longues sur les fichiers : extraction / création de ZIP, copie et
déplacement de dossiers.

Toutes ces fonctions sont pensées pour tourner dans un thread de travail :
  • `on_progress(fait, total, courant)` reçoit des OCTETS (fait / total) et le
    nom du fichier en cours ; elle peut être appelée très souvent, c'est à
    l'appelant (worker Qt) de limiter la cadence d'affichage ;
  • `cancel()` est interrogée régulièrement ; si elle renvoie True,
    l'opération s'arrête, nettoie ses fichiers temporaires et lève
    constants.OperationCancelled. Le dossier source n'est jamais touché avant
    qu'une copie complète n'ait réussi.

Sécurité : une archive est une entrée non fiable. Chaque nom de membre est
validé (pas de chemin absolu, pas de « .. », pas de lecteur Windows), les liens
symboliques sont ignorés, l'espace disque est vérifié avant extraction et un
membre qui dépasse la taille annoncée dans son en-tête fait échouer l'import.
"""

from __future__ import annotations

import contextlib
import errno
import os
import re
import shutil
import tempfile
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import constants, paths

ProgressCallback = Callable[[int, int, str], None]
CancelCheck = Callable[[], bool]

MAX_ZIP_ENTRIES = 1_000_000        # garde-fou contre les archives absurdes
_MIN_FREE_MARGIN = 64 * 1024 * 1024  # marge d'espace disque conservée
_CHUNK = 1024 * 1024
_STAGING_PREFIX = ".voktora-tmp-"
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
# Credentials éventuellement présents dans une URL de remote (https://user:token@host/…)
_URL_CREDENTIALS_RE = re.compile(rb"(https?://)[^/@\s]+@")


# ──────────────────────────────────────────────
# OUTILS COMMUNS
# ──────────────────────────────────────────────

class ProgressTracker:
    """Accumule les octets traités et notifie `on_progress`."""

    def __init__(self, total: int, callback: ProgressCallback | None):
        self.total = max(total, 0)
        self.done = 0
        self._callback = callback

    def advance(self, nbytes: int, current: str = "") -> None:
        self.done += nbytes
        if self._callback:
            self._callback(min(self.done, self.total) if self.total else self.done, self.total, current)

    def finish(self, current: str = "") -> None:
        if self._callback:
            self._callback(self.total, self.total, current)


def _check_cancel(cancel: CancelCheck | None) -> None:
    if cancel is not None and cancel():
        raise constants.OperationCancelled("Opération annulée.")


def _new_staging_dir(parent: Path) -> Path:
    """Dossier temporaire caché dans `parent` (même volume → renommage atomique final)."""
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=parent))


def _ensure_free_space(where: Path, needed: int) -> None:
    probe = where
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if needed + _MIN_FREE_MARGIN > free:
        raise constants.ArchiveError(
            f"Espace disque insuffisant : {needed // (1024 * 1024)} Mo nécessaires, "
            f"{free // (1024 * 1024)} Mo disponibles."
        )


def _tree_size(folder: Path) -> tuple[int, int]:
    """(nombre de fichiers, taille totale en octets) d'un dossier, liens non suivis."""
    count = total = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            full = os.path.join(root, name)
            with contextlib.suppress(OSError):
                if not os.path.islink(full):
                    total += os.path.getsize(full)
                count += 1
    return count, total


def strip_git_credentials(data: bytes) -> bytes:
    """Retire les identifiants intégrés aux URL http(s) (contenu de .git/config)."""
    return _URL_CREDENTIALS_RE.sub(rb"\1", data)


# ──────────────────────────────────────────────
# ZIP — inspection et extraction
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class ZipSummary:
    """Résumé d'une archive, lu depuis son répertoire central (sans décompresser)."""
    root_name: str | None      # dossier racine unique de l'archive, sinon None
    suggested_name: str        # nom de projet proposé
    file_count: int
    total_bytes: int
    skipped_links: int         # liens symboliques ignorés


def _member_parts(name: str) -> tuple[str, ...]:
    """Décompose un nom de membre en segments sûrs ; lève ArchiveError sinon."""
    normalized = name.replace("\\", "/")
    if not normalized.strip("/"):
        return ()
    if normalized.startswith("/") or _WINDOWS_DRIVE_RE.match(normalized):
        raise constants.ArchiveError(f"Chemin absolu interdit dans l'archive : {name!r}")
    parts = tuple(p for p in PurePosixPath(normalized).parts if p not in ("", "."))
    if any(p == ".." for p in parts) or any("\x00" in p for p in parts):
        raise constants.ArchiveError(f"Chemin dangereux dans l'archive : {name!r}")
    return parts


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def inspect_zip(zip_path: Path) -> ZipSummary:
    """Analyse une archive et valide tous ses noms de membres."""
    zip_path = Path(zip_path)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise constants.ArchiveError(f"Archive ZIP invalide ou corrompue : {zip_path.name}") from exc
    except OSError as exc:
        raise constants.ArchiveError(f"Impossible de lire l'archive : {exc}") from exc

    if len(infos) > MAX_ZIP_ENTRIES:
        raise constants.ArchiveError(f"Archive trop volumineuse ({len(infos)} entrées).")

    top_levels: set[str] = set()
    has_root_file = False
    file_count = total = skipped = 0
    for info in infos:
        parts = _member_parts(info.filename)
        if not parts:
            continue
        top_levels.add(parts[0])
        is_dir = info.is_dir()
        if len(parts) == 1 and not is_dir:
            has_root_file = True
        if is_dir:
            continue
        if _is_symlink(info):
            skipped += 1
            continue
        file_count += 1
        total += info.file_size

    root_name = next(iter(top_levels)) if len(top_levels) == 1 and not has_root_file else None
    return ZipSummary(
        root_name=root_name,
        suggested_name=root_name or zip_path.stem,
        file_count=file_count,
        total_bytes=total,
        skipped_links=skipped,
    )


def extract_zip(zip_path: Path, dest_root: Path, name: str | None = None,
                on_progress: ProgressCallback | None = None,
                cancel: CancelCheck | None = None) -> Path:
    """Extrait une archive dans `dest_root/<name>` et retourne ce dossier.

    L'extraction se fait dans un dossier temporaire puis est renommée d'un coup :
    le projet n'apparaît qu'entier, et une annulation ou une erreur ne laisse
    aucun demi-dossier. Si l'archive contient un dossier racine unique, son
    contenu devient directement celui du projet.
    """
    zip_path, dest_root = Path(zip_path), Path(dest_root)
    summary = inspect_zip(zip_path)
    project_name = (name or summary.suggested_name).strip()
    paths.validate_name(project_name)

    target = dest_root / project_name
    if target.exists():
        raise FileExistsError(f"Un projet nommé « {project_name} » existe déjà ({target}).")
    _ensure_free_space(dest_root, summary.total_bytes)

    staging = _new_staging_dir(dest_root)
    tracker = ProgressTracker(summary.total_bytes, on_progress)
    try:
        staging_real = staging.resolve()
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                _check_cancel(cancel)
                parts = _member_parts(info.filename)
                if summary.root_name:
                    parts = parts[1:]
                if not parts or _is_symlink(info):
                    continue
                out = staging.joinpath(*parts)
                # Défense en profondeur : après résolution, rester dans le staging.
                if not out.resolve().is_relative_to(staging_real):
                    raise constants.ArchiveError(f"Chemin hors du dossier cible : {info.filename!r}")
                if info.is_dir():
                    out.mkdir(parents=True, exist_ok=True)
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                _extract_member(zf, info, out, tracker, cancel)
        tracker.finish(project_name)
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def _extract_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, out: Path,
                    tracker: ProgressTracker, cancel: CancelCheck | None) -> None:
    written = 0
    try:
        with zf.open(info) as src, open(out, "wb") as dst:
            while chunk := src.read(_CHUNK):
                written += len(chunk)
                # Un en-tête qui ment sur la taille est le signe d'une archive piégée.
                if written > info.file_size:
                    raise constants.ArchiveError(
                        f"Taille incohérente pour « {info.filename} » (archive piégée ?).")
                dst.write(chunk)
                tracker.advance(len(chunk), info.filename)
                _check_cancel(cancel)
    except (zipfile.BadZipFile, zlib.error, NotImplementedError) as exc:
        raise constants.ArchiveError(f"Archive corrompue ou non prise en charge ({info.filename}) : {exc}") from exc
    except RuntimeError as exc:  # zipfile signale ainsi un membre chiffré
        raise constants.ArchiveError(f"Membre illisible « {info.filename} » (archive chiffrée ?) : {exc}") from exc


# ──────────────────────────────────────────────
# COPIE / DÉPLACEMENT DE DOSSIERS
# ──────────────────────────────────────────────

def _copy_file(src: Path, dst: Path, tracker: ProgressTracker, cancel: CancelCheck | None) -> None:
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        while chunk := fsrc.read(_CHUNK):
            fdst.write(chunk)
            tracker.advance(len(chunk), src.name)
            _check_cancel(cancel)
    with contextlib.suppress(OSError):
        shutil.copystat(src, dst)


def _copy_into(src: Path, dst: Path, tracker: ProgressTracker, cancel: CancelCheck | None) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for root, dirnames, filenames in os.walk(src):
        rel = Path(root).relative_to(src)
        for dirname in dirnames:
            (dst / rel / dirname).mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            _check_cancel(cancel)
            source_file, target_file = Path(root) / filename, dst / rel / filename
            if source_file.is_symlink():
                # Le lien est recopié tel quel (comme le ferait `cp -a`), sans suivre sa cible.
                with contextlib.suppress(OSError, NotImplementedError):
                    os.symlink(os.readlink(source_file), target_file)
                continue
            _copy_file(source_file, target_file, tracker, cancel)


def _validate_transfer(src: Path, dst: Path) -> None:
    if not src.is_dir():
        raise NotADirectoryError(f"Introuvable ou n'est pas un dossier : {src}")
    if dst.exists():
        raise FileExistsError(f"La destination existe déjà : {dst}")
    src_real, dst_real = src.resolve(), dst.resolve()
    if dst_real == src_real or dst_real.is_relative_to(src_real):
        raise ValueError("La destination ne peut pas se trouver à l'intérieur du dossier source.")


def copy_tree(src: Path, dst: Path, on_progress: ProgressCallback | None = None,
              cancel: CancelCheck | None = None) -> Path:
    """Copie `src` vers `dst` (qui ne doit pas exister) de façon atomique."""
    src, dst = Path(src), Path(dst)
    _validate_transfer(src, dst)
    count, total = _tree_size(src)
    _ensure_free_space(dst.parent, total)

    staging = _new_staging_dir(dst.parent)
    tracker = ProgressTracker(total, on_progress)
    try:
        _copy_into(src, staging, tracker, cancel)
        tracker.finish(dst.name)
        staging.rename(dst)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return dst


def _refuse_dangerous_move(src: Path) -> None:
    """Interdit de déplacer une racine de disque ou un ancêtre du dossier personnel."""
    real = src.resolve()
    home = Path.home().resolve()
    if real == real.parent or real == home or real in home.parents:
        raise ValueError(
            f"Déplacement refusé : « {src} » est un dossier système ou personnel. "
            "Choisissez « Copier » ou « Ajouter sur place »."
        )


def move_tree(src: Path, dst: Path, on_progress: ProgressCallback | None = None,
              cancel: CancelCheck | None = None) -> Path:
    """Déplace `src` vers `dst`.

    Sur un même volume, c'est un simple renommage (instantané, atomique).
    Entre deux volumes, le dossier est copié en entier, puis la source n'est
    supprimée qu'une fois la copie terminée : une annulation ou une erreur en
    cours de route laisse la source intacte.
    """
    src, dst = Path(src), Path(dst)
    _validate_transfer(src, dst)
    _refuse_dangerous_move(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        copy_tree(src, dst, on_progress, cancel)
        _remove_source(src)
        return dst
    if on_progress:
        on_progress(1, 1, dst.name)
    return dst


def _remove_source(src: Path) -> None:
    """Supprime le dossier source après une copie réussie (point de non-retour)."""
    failures: list[str] = []

    def _on_error(_func, path, exc) -> None:
        failures.append(f"{path} ({exc})")

    shutil.rmtree(src, onexc=_on_error)
    if failures:
        raise constants.ArchiveError(
            "Le dossier a bien été copié, mais la source n'a pas pu être entièrement supprimée :\n"
            + "\n".join(failures[:5])
        )


# ──────────────────────────────────────────────
# SUPPRESSION
# ──────────────────────────────────────────────

def delete_tree(folder: Path, on_progress: ProgressCallback | None = None,
                cancel: CancelCheck | None = None) -> None:
    """Supprime un dossier avec progression (en nombre de fichiers).

    Contrairement à `shutil.rmtree(ignore_errors=True)`, les échecs ne sont pas
    avalés : ils sont regroupés dans une ArchiveError, pour que l'appelant ne
    « oublie » pas un projet dont le dossier est en réalité toujours là.
    """
    folder = Path(folder)
    if not folder.exists():
        return
    if folder.is_symlink():
        folder.unlink()
        return
    total = sum(len(files) for _r, _d, files in os.walk(folder)) or 1
    tracker = ProgressTracker(total, on_progress)
    failures: list[str] = []
    for root, dirnames, filenames in os.walk(folder, topdown=False):
        for name in filenames:
            _check_cancel(cancel)
            target = Path(root) / name
            try:
                target.unlink()
            except OSError:
                try:  # fichier en lecture seule (Windows) : lever l'attribut et réessayer
                    target.chmod(0o600)
                    target.unlink()
                except OSError as exc:
                    failures.append(f"{target} ({exc.strerror or exc})")
            tracker.advance(1, name)
        for name in dirnames:
            sub = Path(root) / name
            try:
                sub.unlink() if sub.is_symlink() else sub.rmdir()
            except OSError:
                pass  # non vide si un fichier a résisté : déjà signalé plus haut
    try:
        folder.rmdir()
    except OSError as exc:
        failures.append(f"{folder} ({exc.strerror or exc})")
    tracker.finish(folder.name)
    if failures:
        raise constants.ArchiveError(
            f"{len(failures)} élément(s) n'ont pas pu être supprimés :\n" + "\n".join(failures[:5]))


# ──────────────────────────────────────────────
# ZIP — création
# ──────────────────────────────────────────────

def add_tree_to_zip(zf: zipfile.ZipFile, folder: Path, arc_prefix: str,
                    tracker: ProgressTracker, cancel: CancelCheck | None = None) -> None:
    """Ajoute `folder` à l'archive sous `arc_prefix/`.

    Les liens symboliques ne sont pas suivis (on n'embarque jamais de contenu
    extérieur au projet) et les identifiants éventuellement présents dans
    `.git/config` sont retirés de la copie archivée.
    """
    for root, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        for filename in sorted(filenames):
            _check_cancel(cancel)
            full = Path(root) / filename
            if full.is_symlink():
                continue
            rel = full.relative_to(folder).as_posix()
            arcname = f"{arc_prefix}/{rel}"
            try:
                zinfo = zipfile.ZipInfo.from_file(full, arcname)
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                if rel == ".git/config":
                    zf.writestr(zinfo, strip_git_credentials(full.read_bytes()))
                    tracker.advance(zinfo.file_size, arcname)
                    continue
                with open(full, "rb") as src, zf.open(zinfo, "w", force_zip64=zinfo.file_size > 2**30) as dst:
                    while chunk := src.read(_CHUNK):
                        dst.write(chunk)
                        tracker.advance(len(chunk), arcname)
                        _check_cancel(cancel)
            except OSError:
                # Fichier verrouillé ou disparu pendant l'export : on continue
                # plutôt que d'abandonner toute l'archive.
                continue


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Impossible de trouver un nom libre pour {path}")


def write_zip_atomically(zip_path: Path, writer: Callable[[zipfile.ZipFile], None]) -> Path:
    """Écrit une archive dans un fichier `.part` puis le renomme si tout a réussi."""
    zip_path = _unique_path(Path(zip_path))
    part = zip_path.with_name(zip_path.name + ".part")
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as zf:
            writer(zf)
        part.replace(zip_path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return zip_path


def export_folder_to_zip(folder: Path, output_dir: Path | None = None,
                         on_progress: ProgressCallback | None = None,
                         cancel: CancelCheck | None = None) -> Path:
    """Compresse un dossier de projet dans `<output_dir>/<nom>_<horodatage>.zip`."""
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"Introuvable ou n'est pas un dossier : {folder}")
    output_dir = Path(output_dir) if output_dir else paths.get_backups_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _count, total = _tree_size(folder)
    tracker = ProgressTracker(total, on_progress)

    def _write(zf: zipfile.ZipFile) -> None:
        add_tree_to_zip(zf, folder, folder.name, tracker, cancel)

    result = write_zip_atomically(output_dir / f"{folder.name}_{timestamp}.zip", _write)
    tracker.finish(result.name)
    return result
