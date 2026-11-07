"""
snapshots.py — Sauvegardes complètes de projets Voktora (.snap)

Un snapshot est une vraie sauvegarde : tous les fichiers du projet, y compris l'historique `.git`,
rangés dans une archive zip (manifest.json + index.json + files/…). Seules les sorties régénérables
(node_modules, target, caches, compilation… — reconnues par `diskusage`) sont exclues par défaut ; elles sont
listées dans le manifeste, et on peut les inclure.

  • versions numérotées par projet (v1, v2…), note, date, nombre de fichiers, branche/commit git ;
  • empreinte SHA-256 de chaque fichier (index.json) → vérification d'intégrité ;
  • restauration complète (ailleurs ou sur place avec snapshot de sécurité automatique) ou fichier par fichier ;
  • comparaison intelligente : ajoutés / supprimés / modifiés / RENOMMÉS, entre deux snapshots ou entre un
    snapshot et l'état actuel du projet, avec diff texte d'un fichier ;
  • barre de progression et annulation partout (`on_progress`, `cancel`).

Sécurité : jamais d'identifiants dans `.git/config`, liens symboliques ignorés, noms de membres validés
(zip-slip), extraction dans un dossier temporaire puis échange atomique.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import core
import diskusage

SNAP_EXT = ".snap"
SNAP_MANIFEST = "manifest.json"
SNAP_INDEX = "index.json"
SNAP_DATA_DIR = "files/"
FORMAT_VERSION = 2
MAX_TEXT_DIFF_BYTES = 512 * 1024

KIND_MANUAL, KIND_AUTO, KIND_SAFETY = "manual", "auto", "pre-restore"


@dataclass
class SnapInfo:
    path: Path
    label: str
    timestamp: str
    project: str
    size_mb: float
    version: int = 0
    note: str = ""
    kind: str = KIND_MANUAL
    files: int = 0
    bytes: int = 0
    git_branch: str = ""
    git_commit: str = ""
    includes_git: bool = True
    includes_regenerable: bool = True      # anciens snapshots : tout était inclus sauf .git/objects
    excluded: list[dict] = field(default_factory=list)
    format: int = 1

    @property
    def title(self) -> str:
        return f"v{self.version} — {self.label}" if self.version else self.label


@dataclass
class FileChange:
    path: str
    status: str                  # added | removed | modified | renamed
    old_path: str = ""           # renamed : ancien chemin
    size_a: int = 0
    size_b: int = 0


@dataclass
class Comparison:
    changes: list[FileChange] = field(default_factory=list)
    unchanged: int = 0

    def count(self, status: str) -> int:
        return sum(1 for c in self.changes if c.status == status)

    @property
    def bytes_delta(self) -> int:
        return sum(c.size_b - c.size_a for c in self.changes)

    def summary(self) -> str:
        parts = [f"{self.count(s)} {label}" for s, label in
                 (("added", "ajouté(s)"), ("removed", "supprimé(s)"), ("modified", "modifié(s)"),
                  ("renamed", "renommé(s)")) if self.count(s)]
        return ", ".join(parts + [f"{self.unchanged} identique(s)"]) if parts else \
            f"Aucune différence ({self.unchanged} fichier(s) identique(s))."

    def as_dict(self) -> dict[str, str]:
        return {c.path: c.status for c in self.changes}


# ── Parcours du projet ─────────────────────────────────────────────────────────

@dataclass
class _Entry:
    rel: str
    full: Path
    size: int


def collect(project: Path, include_git: bool = True, include_regenerable: bool = False,
            cancel: Callable[[], bool] | None = None) -> tuple[list[_Entry], list[dict]]:
    """(fichiers à sauvegarder, dossiers exclus avec taille). Liens symboliques ignorés."""
    entries: list[_Entry] = []
    excluded: list[dict] = []
    stack = [project]
    while stack:
        if cancel and cancel():
            raise core.OperationCancelled()
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                listing = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for entry in listing:
            try:
                if entry.is_symlink():
                    continue
                rel = Path(entry.path).relative_to(project).as_posix()
                if entry.is_dir(follow_symlinks=False):
                    if entry.name == ".git" and current == project:
                        if include_git:
                            stack.append(Path(entry.path))
                        else:
                            excluded.append({"path": rel, "category": diskusage.VCS,
                                             "bytes": diskusage.dir_size(Path(entry.path))[0]})
                        continue
                    rule = None if include_regenerable or ".git" in Path(rel).parts \
                        else diskusage.classify_dir(str(current), entry.name)
                    if rule is not None:
                        excluded.append({"path": rel, "category": rule.category,
                                         "bytes": diskusage.dir_size(Path(entry.path))[0]})
                    else:
                        stack.append(Path(entry.path))
                else:
                    entries.append(_Entry(rel, Path(entry.path), entry.stat(follow_symlinks=False).st_size))
            except OSError:
                continue
    entries.sort(key=lambda e: e.rel)
    return entries, sorted(excluded, key=lambda e: e["path"])


def git_head(project: Path) -> tuple[str, str]:
    """(branche, commit) lus dans .git sans lancer git. Chaînes vides si inconnu."""
    git = project / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return "", ""
    if not head.startswith("ref:"):
        return "(détaché)", head[:40]
    ref = head.split(None, 1)[1].strip()
    branch = ref.removeprefix("refs/heads/")
    try:
        return branch, (git / ref).read_text(encoding="utf-8").strip()[:40]
    except OSError:
        pass
    try:
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return branch, line.split()[0][:40]
    except OSError:
        pass
    return branch, ""


def _project_meta(project: Path) -> dict:
    """Métadonnées Voktora du projet (catégorie, note, icône…), sans aucun secret."""
    try:
        cfg = core._load_config()
        entry = core._find_entry(cfg, project) or {}
    except Exception:       # noqa: BLE001 - la sauvegarde ne doit jamais échouer à cause de la configuration
        return {}
    banned = ("token", "secret", "password", "key", "credential")
    return {k: v for k, v in entry.items()
            if isinstance(v, str | int | float | bool | list | dict) and not any(b in k.lower() for b in banned)}


# ── Création ──────────────────────────────────────────────────────────────────

def create(project_path: Path, label: str = "",
           on_progress: core.ProgressCallback | None = None,
           cancel: core.CancelCheck | None = None, *,
           note: str = "", include_git: bool = True, include_regenerable: bool = False,
           kind: str = KIND_MANUAL, keep: int = 0) -> Path:
    """
    Sauvegarde complète du projet dans data/snapshots/<projet>/. Écrit dans un fichier temporaire puis
    renomme : un snapshot annulé ou interrompu ne laisse jamais d'archive tronquée.
    `keep` > 0 : supprime ensuite les plus anciens pour n'en garder que `keep` (jamais celui qu'on vient de créer).
    """
    project_path = Path(project_path)
    archive = core.archive
    snap_dir = _snaps_dir(project_path)
    snap_dir.mkdir(parents=True, exist_ok=True)

    entries, excluded = collect(project_path, include_git, include_regenerable, cancel)
    total = sum(e.size for e in entries)
    archive._ensure_free_space(snap_dir, total)           # noqa: SLF001
    tracker = archive.ProgressTracker(total, on_progress)

    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")
    version = next_version(project_path)
    branch, commit = git_head(project_path)
    index: dict[str, dict] = {}

    def _write(zf: zipfile.ZipFile) -> None:
        for item in entries:
            archive._check_cancel(cancel)                 # noqa: SLF001
            arc = SNAP_DATA_DIR + item.rel
            digest = hashlib.sha256()
            try:
                if item.rel == ".git/config":             # jamais d'identifiants dans une sauvegarde
                    data = core.strip_git_credentials(item.full.read_bytes())
                    zf.writestr(arc, data)
                    digest.update(data)
                    size = len(data)
                    tracker.advance(item.size, item.rel)
                else:
                    zinfo = zipfile.ZipInfo.from_file(item.full, arc)
                    stored = item.full.suffix.lower() in archive._ALREADY_COMPRESSED   # noqa: SLF001
                    zinfo.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
                    buffer = bytearray(archive._CHUNK)    # noqa: SLF001
                    view = memoryview(buffer)
                    size = 0
                    with open(item.full, "rb") as src, \
                            zf.open(zinfo, "w", force_zip64=item.size > 2**30) as dst:
                        while read := src.readinto(buffer):
                            dst.write(view[:read])
                            digest.update(view[:read])
                            size += read
                            tracker.advance(read, item.rel)
                            archive._check_cancel(cancel)  # noqa: SLF001
            except OSError:
                continue                                   # fichier verrouillé ou disparu : on continue
            index[item.rel] = {"size": size, "sha256": digest.hexdigest()}
        manifest = {
            "format": FORMAT_VERSION, "app": core.constants.APP_VERSION,
            "project": project_path.name, "project_path": str(project_path),
            "version": version, "label": label or f"v{version}", "note": note, "kind": kind,
            "timestamp": ts, "created": now.isoformat(timespec="seconds"),
            "files": len(index), "bytes": sum(v["size"] for v in index.values()),
            "git": {"branch": branch, "commit": commit},
            "includes_git": include_git, "includes_regenerable": include_regenerable, "excluded": excluded,
            "project_meta": _project_meta(project_path),
        }
        zf.writestr(SNAP_INDEX, json.dumps(index, separators=(",", ":")))
        zf.writestr(SNAP_MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False))

    out = archive.write_zip_atomically(snap_dir / f"{project_path.name}_{ts}_v{version}{SNAP_EXT}", _write)
    tracker.finish(out.name)
    if keep > 0:
        prune(project_path, keep, protect=out)
    return out


def next_version(project_path: Path) -> int:
    return max((s.version for s in list_snaps(project_path)), default=0) + 1


def prune(project_path: Path, keep: int, protect: Path | None = None) -> list[Path]:
    """Garde les `keep` snapshots les plus récents ; retourne ceux qui ont été supprimés."""
    if keep <= 0:
        return []
    snaps = sorted(list_snaps(project_path), key=lambda s: (s.version, s.timestamp), reverse=True)
    removed = []
    for snap in snaps[keep:]:
        if protect is not None and snap.path == protect:
            continue
        delete_snap(snap.path)
        removed.append(snap.path)
    return removed


# ── Lecture ───────────────────────────────────────────────────────────────────

def read_manifest(snap: Path) -> dict:
    try:
        with zipfile.ZipFile(snap, "r") as zf:
            data = json.loads(zf.read(SNAP_MANIFEST))
        return data if isinstance(data, dict) else {}
    except Exception:       # noqa: BLE001 - snapshot illisible : on le liste quand même
        return {}


def list_snaps(project_path: Path) -> list[SnapInfo]:
    snap_dir = _snaps_dir(Path(project_path))
    if not snap_dir.exists():
        return []
    snaps = []
    for f in snap_dir.glob(f"*{SNAP_EXT}"):
        m = read_manifest(f)
        git = m.get("git") if isinstance(m.get("git"), dict) else {}
        snaps.append(SnapInfo(
            path=f, label=str(m.get("label", f.stem)), timestamp=str(m.get("timestamp", "")),
            project=str(m.get("project", Path(project_path).name)), size_mb=round(f.stat().st_size / 1_048_576, 2),
            version=int(m.get("version", 0) or 0) if int(m.get("format", 1) or 1) >= 2 else 0, note=str(m.get("note", "")), kind=str(m.get("kind", KIND_MANUAL)),
            files=int(m.get("files", 0) or 0), bytes=int(m.get("bytes", 0) or 0),
            git_branch=str(git.get("branch", "")), git_commit=str(git.get("commit", "")),
            includes_git=bool(m.get("includes_git", False)),
            includes_regenerable=bool(m.get("includes_regenerable", True)),
            excluded=list(m.get("excluded", [])), format=int(m.get("format", 1) or 1),
        ))
    snaps.sort(key=lambda s: (s.timestamp, s.version), reverse=True)
    return snaps


def delete_snap(snap_path: Path) -> None:
    Path(snap_path).unlink(missing_ok=True)


def verify(snap: Path, on_progress: core.ProgressCallback | None = None,
           cancel: core.CancelCheck | None = None) -> list[str]:
    """Contrôle l'intégrité : CRC de chaque membre et SHA-256 de l'index. Liste des problèmes (vide = intègre)."""
    problems: list[str] = []
    try:
        zf = zipfile.ZipFile(snap, "r")
    except (zipfile.BadZipFile, OSError, zlib.error) as exc:
        return [f"archive illisible : {exc}"]
    with zf:
        try:
            index = json.loads(zf.read(SNAP_INDEX))
        except (KeyError, json.JSONDecodeError, zipfile.BadZipFile, zlib.error, OSError, RuntimeError):
            index = {}
        members = [m for m in zf.infolist() if m.filename.startswith(SNAP_DATA_DIR) and not m.is_dir()]
        tracker = core.archive.ProgressTracker(sum(m.file_size for m in members), on_progress)
        for member in members:
            core.archive._check_cancel(cancel)                      # noqa: SLF001
            rel = member.filename[len(SNAP_DATA_DIR):]
            digest = hashlib.sha256()
            try:
                with zf.open(member) as handle:
                    while chunk := handle.read(1 << 20):
                        digest.update(chunk)
                        tracker.advance(len(chunk), rel)
            except (zipfile.BadZipFile, zlib.error, OSError, RuntimeError, EOFError) as exc:
                problems.append(f"{rel} : corrompu ({exc})")
                continue
            expected = index.get(rel, {}).get("sha256")
            if expected and expected != digest.hexdigest():
                problems.append(f"{rel} : empreinte différente de celle enregistrée")
        for rel in index:
            if SNAP_DATA_DIR + rel not in zf.namelist():
                problems.append(f"{rel} : manquant dans l'archive")
    tracker.finish(Path(snap).name)
    return problems


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


def restore_in_place(snap_path: Path, project_path: Path, safety: bool = True,
                     on_progress: core.ProgressCallback | None = None,
                     cancel: core.CancelCheck | None = None) -> Path | None:
    """Remplace le projet par le snapshot. Crée d'abord un snapshot « avant restauration » (annulation possible).
    Retourne le snapshot de sécurité (ou None). Les sorties régénérables du projet actuel sont conservées."""
    project_path = Path(project_path)
    safety_snap = None
    if safety and project_path.exists():
        safety_snap = create(project_path, "Avant restauration", None, cancel, kind=KIND_SAFETY,
                             note=f"Créé automatiquement avant de restaurer {Path(snap_path).name}")
    restore(snap_path, project_path, overwrite=True, on_progress=on_progress, cancel=cancel)
    return safety_snap


def restore_files(snap_path: Path, project_path: Path, rel_paths: list[str],
                  cancel: core.CancelCheck | None = None) -> list[str]:
    """Restaure seulement ces fichiers (écrase les versions actuelles). Retourne ceux qui ont été restaurés."""
    archive = core.archive
    project_path = Path(project_path)
    wanted = {p.replace("\\", "/").lstrip("/") for p in rel_paths}
    restored = []
    with zipfile.ZipFile(snap_path, "r") as zf:
        root_real = project_path.resolve()
        for member in zf.infolist():
            if not member.filename.startswith(SNAP_DATA_DIR) or member.is_dir():
                continue
            rel = member.filename[len(SNAP_DATA_DIR):]
            if rel not in wanted or archive._is_symlink(member):
                continue
            parts = archive._member_parts(rel)
            if not parts:
                continue
            out = project_path.joinpath(*parts)
            if not out.resolve().is_relative_to(root_real):
                raise core.ArchiveError(f"Chemin hors du projet : {rel!r}")
            archive._check_cancel(cancel)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(out.name + ".voktora-part")
            with zf.open(member) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            os.replace(tmp, out)
            restored.append(rel)
    return sorted(restored)


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


# ── Comparaison intelligente ──────────────────────────────────────────────────

def _snap_files(snap: Path) -> dict[str, tuple[int, int]]:
    out = {}
    with zipfile.ZipFile(snap, "r") as zf:
        for m in zf.infolist():
            if m.filename.startswith(SNAP_DATA_DIR) and not m.is_dir():
                out[m.filename[len(SNAP_DATA_DIR):]] = (m.file_size, m.CRC)
    return out


def _crc32(path: Path) -> int:
    value = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            value = zlib.crc32(chunk, value)
    return value & 0xFFFFFFFF


def compare(snap_a: Path, snap_b: Path | None = None, project_path: Path | None = None, *,
            detect_renames: bool = True, cancel: core.CancelCheck | None = None) -> Comparison:
    """
    Compare `snap_a` avec `snap_b` ou, si absent, avec l'état ACTUEL de `project_path`.
    Utilise taille + CRC32 déjà présents dans l'archive : rien n'est décompressé. Pour l'état actuel, le CRC d'un
    fichier n'est calculé que si sa taille correspond (les autres sont forcément différents). `.git` est ignoré
    dans la comparaison avec l'état actuel (ses fichiers internes changent à chaque commande git).
    """
    files_a = _snap_files(snap_a)
    if snap_b is not None:
        files_b = _snap_files(snap_b)
        live: dict[str, Path] = {}
    else:
        if project_path is None:
            raise ValueError("snap_b ou project_path est requis.")
        entries, _ = collect(Path(project_path), include_git=False, include_regenerable=True, cancel=cancel)
        live = {e.rel: e.full for e in entries}
        files_b = {e.rel: (e.size, -1) for e in entries}
        files_a = {k: v for k, v in files_a.items() if not k.startswith(".git/")}
        regen = _regenerable_prefixes(snap_a)
        files_b = {k: v for k, v in files_b.items() if not any(k == p or k.startswith(p + "/") for p in regen)}

    def same(rel: str) -> bool:
        size_a, crc_a = files_a[rel]
        size_b, crc_b = files_b[rel]
        if size_a != size_b:
            return False
        if crc_b == -1:
            crc_b = _crc32(live[rel])
            files_b[rel] = (size_b, crc_b)
        return crc_a == crc_b

    result = Comparison()
    modified, removed, added = [], [], []
    for rel in sorted(files_a):
        if cancel and cancel():
            raise core.OperationCancelled()
        if rel not in files_b:
            removed.append(rel)
        elif same(rel):
            result.unchanged += 1
        else:
            modified.append(rel)
    added = sorted(k for k in files_b if k not in files_a)

    renamed: list[FileChange] = []
    if detect_renames and removed and added:
        by_sig: dict[tuple[int, int], list[str]] = {}
        for rel in removed:
            by_sig.setdefault(files_a[rel], []).append(rel)
        for rel in list(added):
            size, crc = files_b[rel]
            candidates = by_sig.get((size, crc if crc != -1 else _crc32(live[rel])))
            if crc == -1 and size not in {s for s, _ in by_sig}:
                continue
            if candidates:
                old = candidates.pop(0)
                renamed.append(FileChange(rel, "renamed", old, files_a[old][0], size))
                removed.remove(old)
                added.remove(rel)
    result.changes = (
        [FileChange(r, "removed", size_a=files_a[r][0]) for r in removed]
        + [FileChange(a, "added", size_b=files_b[a][0]) for a in added]
        + [FileChange(m, "modified", size_a=files_a[m][0], size_b=files_b[m][0]) for m in modified]
        + renamed)
    result.changes.sort(key=lambda c: c.path)
    return result


def _regenerable_prefixes(snap: Path) -> list[str]:
    """Dossiers exclus du snapshot : on ne les compare pas avec l'état actuel (ils n'y sont pas sauvegardés)."""
    return [e["path"] for e in read_manifest(snap).get("excluded", []) if isinstance(e, dict) and e.get("path")]


def diff_snaps(snap_a: Path, snap_b: Path) -> dict[str, str]:
    """{"fichier": "added"|"removed"|"modified"} entre deux snapshots (sans détection de renommage)."""
    return compare(snap_a, snap_b, detect_renames=False).as_dict()


def file_diff(snap_a: Path, rel: str, snap_b: Path | None = None, project_path: Path | None = None,
              old_rel: str = "") -> str:
    """Diff texte unifié d'UN fichier entre `snap_a` et `snap_b` (ou l'état actuel). Gère binaires et gros fichiers."""
    def read_snap(snap: Path, name: str) -> bytes | None:
        try:
            with zipfile.ZipFile(snap, "r") as zf:
                info = zf.getinfo(SNAP_DATA_DIR + name)
                if info.file_size > MAX_TEXT_DIFF_BYTES:
                    return b"\0TOO_BIG"
                return zf.read(info)
        except KeyError:
            return None

    def read_live(name: str) -> bytes | None:
        path = Path(project_path or ".") / name
        if not path.is_file() or path.is_symlink():
            return None
        if path.stat().st_size > MAX_TEXT_DIFF_BYTES:
            return b"\0TOO_BIG"
        return path.read_bytes()

    before = read_snap(snap_a, old_rel or rel)
    after = read_snap(snap_b, rel) if snap_b is not None else read_live(rel)
    for blob in (before, after):
        if blob is not None and blob.startswith(b"\0TOO_BIG"):
            return "(fichier trop volumineux pour un diff texte)"
        if blob is not None and b"\0" in blob[:8192]:
            return "(fichier binaire — comparaison par empreinte uniquement)"
    old = (before or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
    new = (after or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
    lines = list(difflib.unified_diff(old, new, f"a/{old_rel or rel}", f"b/{rel}", n=3))
    return "".join(lines) or "(contenu identique)"


def _snaps_dir(project_path: Path) -> Path:
    return core.get_data_dir() / "snapshots" / Path(project_path).name
