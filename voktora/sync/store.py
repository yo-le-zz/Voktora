"""
Voktora — sync.store
Magasin LOCAL de la synchronisation : expose à l'engine (et au serveur) les « espaces » de cette machine.

  cfg                 réglages et métadonnées, découpés en « feuilles » JSON (une valeur = un élément) ;
  p:<projet>          fichiers d'un projet ;
  x:plugin_settings   réglages des plugins.

Chaque élément a une empreinte SHA-256 : c'est ce que l'engine compare. Sécurité : chemins validés (pas de
« .. », pas de lien symbolique suivi, pas de sortie du dossier du projet), `.git/config` et `.git/hooks`
jamais synchronisés (ils peuvent exécuter des commandes), écritures atomiques, suppressions → corbeille.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import threading
import time
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath
from typing import NamedTuple, Protocol

import diskusage

from . import secure
from .settings import SyncSettings

PART_SUFFIX = ".voktora-sync-part"
TRASH_DAYS = 30
CFG = "cfg"
# Réglages jamais synchronisés : propres à la machine ou secrets.
APP_CONFIG_LOCAL_ONLY = {"window_geometry", "splitter_states", "github_client_id", "auth_method"}
SECRET_WORDS = ("token", "secret", "password", "passwd", "credential", "api_key", "apikey")
META_LOCAL_FIELDS = {"path", "drive", "name"}
GIT_NEVER = (".git/config", ".git/hooks", ".git/index.lock", ".git/gc.pid")


class Entry(NamedTuple):
    sha: str
    size: int
    mode: int = 0


class ConfigIO(Protocol):
    def load(self) -> dict: ...
    def save(self, cfg: dict) -> None: ...
    def projects_root(self) -> Path: ...


class SyncPathError(ValueError):
    """Chemin refusé (tentative de sortie du dossier, composant interdit…)."""


def clean_rel(rel: str) -> str:
    if not rel or "\\" in rel or "\0" in rel or rel.startswith("/") or (len(rel) > 1 and rel[1] == ":"):
        raise SyncPathError(f"Chemin refusé : {rel!r}")
    parts = PurePosixPath(rel).parts
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise SyncPathError(f"Chemin refusé : {rel!r}")
    return "/".join(parts)


def is_secret_key(key: str) -> bool:
    return any(w in key.lower() for w in SECRET_WORDS)


def _json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LocalStore:
    def __init__(self, settings: SyncSettings, config_io: ConfigIO, state_dir: Path,
                 extras: dict[str, Path] | None = None, trash_dir: Path | None = None):
        self.settings = settings
        self.config_io = config_io
        self.state_dir = Path(state_dir)
        self.extras = dict(extras or {})
        self.trash_dir = Path(trash_dir) if trash_dir else self.state_dir / "trash"
        self._cache: dict[str, list] | None = None
        self._cache_lock = threading.RLock()
        self._cache_dirty = False
        self._cache_saved = 0.0
        self._cfg: dict | None = None            # configuration en cours de modification (voir commit)

    # ── espaces ──────────────────────────────────────────────────────────────

    def projects(self) -> dict[str, Path]:
        out = {}
        for entry in self.config_io.load().get("projects", []):
            if isinstance(entry, dict) and entry.get("path"):
                out[str(entry.get("name") or Path(entry["path"]).name)] = Path(entry["path"])
        return out

    def projects_root_has(self, name: str) -> bool:
        return (self.config_io.projects_root() / name).is_dir()

    def spaces(self) -> list[str]:
        s = self.settings
        spaces = []
        if any(s.category(c) for c in ("config", "quick_actions", "categories", "projects_meta")):
            spaces.append(CFG)
        if s.category("project_files"):
            spaces += [f"p:{n}" for n in sorted(self.projects()) if s.project_selected(n)]
        if s.category("plugin_settings") and "plugin_settings" in self.extras:
            spaces.append("x:plugin_settings")
        return spaces

    def _root(self, space: str, create: bool = False) -> Path:
        if space.startswith("x:"):
            name = space[2:]
            if name not in self.extras:
                raise SyncPathError(f"Espace inconnu : {space}")
            return self.extras[name]
        if not space.startswith("p:"):
            raise SyncPathError(f"Espace inconnu : {space}")
        name = space[2:]
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise SyncPathError(f"Nom de projet refusé : {name!r}")
        known = self.projects().get(name)
        if known is not None:
            return known
        root = self.config_io.projects_root() / name
        if not create:
            if root.is_dir():            # dossier déjà reçu mais projet pas encore déclaré (synchro interrompue)
                return root
            raise SyncPathError(f"Projet inconnu : {name}")
        root.mkdir(parents=True, exist_ok=True)
        return root

    # ── manifestes ───────────────────────────────────────────────────────────

    def manifest(self, space: str, cancel=None, progress=None) -> dict[str, Entry]:
        """`progress(fichiers_lus, dossier_ou_fichier_courant)` est appelé régulièrement (≈ 2 fois par seconde)."""
        if space == CFG:
            return {rel: Entry(_sha(data), len(data)) for rel, data in self._leaves().items()}
        root = self._root(space)
        if not root.is_dir():
            return {}
        return self._scan(root, space.startswith("p:"), cancel, progress)

    def _scan(self, root: Path, is_project: bool, cancel, progress=None) -> dict[str, Entry]:
        s = self.settings
        last = [0.0]

        def tick(label: str) -> None:
            now = time.monotonic()
            if progress and now - last[0] >= 0.4:
                last[0] = now
                progress(len(result), label)

        limit = int(s["max_file_mb"]) * 1024 * 1024
        cache = self._load_cache()
        touched: set[str] = set()
        result: dict[str, Entry] = {}
        stack = [root]
        while stack:
            if cancel and cancel():
                raise InterruptedError
            current = stack.pop()
            tick(current.relative_to(root).as_posix() if current != root else ".")
            try:
                with os.scandir(current) as it:
                    listing = list(it)
            except OSError:
                continue
            for entry in listing:
                try:
                    if entry.is_symlink() or entry.name.endswith(PART_SUFFIX):
                        continue
                    rel = Path(entry.path).relative_to(root).as_posix()
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name == ".git" and current == root:
                            if is_project and s["include_git"]:
                                stack.append(Path(entry.path))
                            continue
                        if is_project and not s["include_regenerable"] \
                                and ".git" not in rel.split("/") and diskusage.classify_dir(str(current), entry.name):
                            continue
                        if rel in GIT_NEVER or any(rel.startswith(g + "/") for g in GIT_NEVER):
                            continue
                        stack.append(Path(entry.path))
                        continue
                    if rel in GIT_NEVER or any(rel.startswith(g + "/") for g in GIT_NEVER) or s.excluded(rel):
                        continue
                    st = entry.stat(follow_symlinks=False)
                    if st.st_size > limit:
                        continue
                    tick(rel)
                    touched.add(entry.path)
                    result[rel] = Entry(self._hash_file(Path(entry.path), st, cache, lambda r=rel: tick(r)),
                                        st.st_size, st.st_mode & 0o111)
                except (OSError, ValueError):
                    continue
        self._prune_cache(str(root) + os.sep, touched)
        self._save_cache()
        return result

    def _prune_cache(self, prefix: str, touched: set[str]) -> None:
        """Oublie les fichiers disparus de ce dossier (le cache ne grossit pas indéfiniment : 100+ projets)."""
        with self._cache_lock:
            stale = [k for k in self._cache or {} if k.startswith(prefix) and k not in touched]
            for key in stale:
                del self._cache[key]
            if stale:
                self._cache_dirty = True

    def _load_cache(self) -> dict[str, list]:
        if self._cache is None:
            try:
                self._cache = json.loads((self.state_dir / "hashcache.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._cache = {}
        return self._cache

    def _save_cache(self, force: bool = False) -> None:
        """Écriture différée (au plus toutes les 15 s, ou sur demande) : avec des centaines de milliers de fichiers,
        réécrire le cache après chaque projet coûterait plus cher que l'analyse elle-même."""
        if self._cache is None or not self._cache_dirty:
            return
        if not force and time.monotonic() - self._cache_saved < 15:
            return
        with self._cache_lock, contextlib.suppress(OSError):
            self.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.state_dir / "hashcache.json.tmp"
            tmp.write_text(json.dumps(self._cache), encoding="utf-8")
            os.replace(tmp, self.state_dir / "hashcache.json")
            self._cache_dirty = False
            self._cache_saved = time.monotonic()

    def flush_cache(self) -> None:
        self._save_cache(force=True)

    def _hash_file(self, path: Path, st: os.stat_result, cache: dict[str, list], beat=None) -> str:
        key = str(path)
        hit = cache.get(key)
        # mtime trop récent : le fichier peut encore changer dans la même fraction de seconde → pas de cache
        if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns and time.time_ns() - st.st_mtime_ns > 2_000_000_000:
            return hit[2]
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while chunk := handle.read(secure.CHUNK):
                digest.update(chunk)
                if beat:
                    beat()
        with self._cache_lock:
            cache[key] = [st.st_size, st.st_mtime_ns, digest.hexdigest()]
            self._cache_dirty = True
        return digest.hexdigest()

    # ── lecture / écriture ───────────────────────────────────────────────────

    def open_reader(self, space: str, rel: str) -> tuple[int, Iterator[bytes]]:
        rel = clean_rel(rel)
        if space == CFG:
            data = self._leaves().get(rel)
            if data is None:
                raise FileNotFoundError(rel)
            return len(data), iter([data])
        root = self._root(space)
        path = root.joinpath(*rel.split("/"))
        self._ensure_inside(root, path)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(rel)
        size = path.stat().st_size

        def chunks() -> Iterator[bytes]:
            with open(path, "rb") as handle:
                while chunk := handle.read(secure.CHUNK):
                    yield chunk
        return size, chunks()

    def write(self, space: str, rel: str, chunks: Iterable[bytes], mode: int = 0, mtime: float | None = None,
              expected_sha: str = "") -> None:
        rel = clean_rel(rel)
        if space == CFG:
            data = b"".join(chunks)
            if expected_sha and _sha(data) != expected_sha:
                raise SyncPathError(f"Empreinte inattendue pour {rel} (modifié pendant le transfert ?)")
            self._cfg_set(rel, json.loads(data.decode("utf-8")))
            return
        root = self._root(space, create=True)
        path = root.joinpath(*rel.split("/"))
        if rel in GIT_NEVER or any(rel.startswith(g + "/") for g in GIT_NEVER):
            raise SyncPathError(f"Fichier refusé : {rel}")
        self._ensure_inside(root, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_inside(root, path)
        tmp = path.with_name(path.name + PART_SUFFIX)
        try:
            digest = hashlib.sha256()
            with open(tmp, "wb") as handle:
                for chunk in chunks:
                    digest.update(chunk)
                    handle.write(chunk)
            if expected_sha and digest.hexdigest() != expected_sha:
                raise SyncPathError(f"Empreinte inattendue pour {rel} (modifié pendant le transfert ?)")
            if mode & 0o111:
                os.chmod(tmp, 0o755)
            if mtime:
                os.utime(tmp, (mtime, mtime))
            if path.is_symlink() or path.is_dir():
                raise SyncPathError(f"Cible invalide : {rel}")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def delete(self, space: str, rel: str) -> None:
        rel = clean_rel(rel)
        if space == CFG:
            self._cfg_set(rel, None, delete=True)
            return
        root = self._root(space)
        path = root.joinpath(*rel.split("/"))
        self._ensure_inside(root, path)
        if not path.exists() and not path.is_symlink():
            return
        dest = self.trash_dir / space.replace(":", "_") / time.strftime("%Y%m%d-%H%M%S") / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        parent = path.parent
        while parent != root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    def commit(self, space: str) -> None:
        """Termine l'écriture d'un espace (la configuration est enregistrée une seule fois)."""
        if space == CFG and self._cfg is not None:
            self.config_io.save(self._cfg)
            self._cfg = None

    def purge_trash(self, days: int = TRASH_DAYS) -> int:
        removed = 0
        limit = time.time() - days * 86400
        if self.trash_dir.is_dir():
            for stamp in self.trash_dir.glob("*/*"):
                with contextlib.suppress(OSError):
                    if stamp.stat().st_mtime < limit:
                        shutil.rmtree(stamp, ignore_errors=True)
                        removed += 1
        return removed

    @staticmethod
    def _ensure_inside(root: Path, path: Path) -> None:
        try:
            real_root = root.resolve()
            probe = path
            while not probe.exists() and probe != probe.parent:
                probe = probe.parent
            if not probe.resolve().is_relative_to(real_root):
                raise SyncPathError(f"Chemin hors du dossier : {path}")
        except OSError as exc:
            raise SyncPathError(str(exc)) from exc

    # ── configuration en feuilles ────────────────────────────────────────────

    def _leaves(self) -> dict[str, bytes]:
        cfg = self._cfg if self._cfg is not None else self.config_io.load()
        s = self.settings
        out: dict[str, bytes] = {}
        for key, value in (cfg.get("app_config") or {}).items():
            if key in APP_CONFIG_LOCAL_ONLY or is_secret_key(key):
                continue
            if key == "quick_apps":
                if not s.category("quick_actions"):
                    continue
            elif not s.category("config"):
                continue
            out[f"app_config/{key}"] = _json_bytes(value)
        if s.category("categories"):
            out["categories"] = _json_bytes(cfg.get("categories", []))
            out["custom_statuses"] = _json_bytes(cfg.get("custom_statuses", {}))
        if s.category("projects_meta"):
            for entry in cfg.get("projects", []):
                if not isinstance(entry, dict) or not entry.get("path"):
                    continue
                name = str(entry.get("name") or Path(entry["path"]).name)
                if not s.project_selected(name):
                    continue
                out[f"meta/{name}/name"] = _json_bytes(name)          # existence du projet, même sans autre champ
                for field, value in entry.items():
                    if field not in META_LOCAL_FIELDS and field != "name" and not is_secret_key(field):
                        out[f"meta/{name}/{field}"] = _json_bytes(value)
        return out

    def _cfg_set(self, rel: str, value, delete: bool = False) -> None:
        if self._cfg is None:
            self._cfg = self.config_io.load()
        cfg = self._cfg
        parts = rel.split("/")
        if parts[0] == "app_config" and len(parts) == 2:
            if parts[1] in APP_CONFIG_LOCAL_ONLY or is_secret_key(parts[1]):
                raise SyncPathError(f"Réglage refusé : {rel}")
            app = cfg.setdefault("app_config", {})
            if delete:
                app.pop(parts[1], None)
            else:
                app[parts[1]] = value
        elif rel in ("categories", "custom_statuses"):
            if not delete:
                cfg[rel] = value
        elif parts[0] == "meta" and len(parts) == 3:
            _, name, field = parts
            if (field in META_LOCAL_FIELDS and field != "name") or is_secret_key(field):
                raise SyncPathError(f"Champ refusé : {rel}")
            entry = next((e for e in cfg.setdefault("projects", [])
                          if isinstance(e, dict) and str(e.get("name") or Path(e.get("path", "")).name) == name), None)
            if entry is None:
                folder = self.config_io.projects_root() / name
                if delete or not folder.is_dir():
                    return                               # le dossier du projet n'est pas (encore) là
                entry = {"name": name, "path": str(folder)}
                cfg["projects"].append(entry)
            if field == "name":
                if delete and entry in cfg.get("projects", []) and not (self.projects_root_has(name)):
                    cfg["projects"].remove(entry)           # projet retiré de la liste sur l'autre PC
            elif delete:
                entry.pop(field, None)
            else:
                entry[field] = value
        else:
            raise SyncPathError(f"Élément de configuration refusé : {rel}")
