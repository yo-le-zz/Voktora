"""
Voktora — plugins.market
Marketplace de plugins : lecture de l'index, installation vérifiée, mise à jour, désinstallation.

Fonctionnement (voir doc/PLUGINS.md et marketplace/README.md) :
  • le dépôt GitHub contient `marketplace/index.json` + `marketplace/plugins/<id>/…` ;
  • on contribue par Pull Request (fork → PR) ; le mainteneur relit, fusionne, et la CI régénère l'index ;
  • l'application télécharge l'index puis, à l'installation, CHAQUE fichier du plugin, et refuse tout
    fichier dont l'empreinte SHA-256 diffère de celle de l'index ;
  • rien n'est exécuté avant que l'utilisateur ait vu les permissions et confirmé.

Deux niveaux (« tier ») :
  • officiel   — dossier `marketplace/plugins/<id>/`, écrit par le mainteneur ;
  • communauté — le contributeur fait son propre fork/dépôt, que la PR ajoute comme SOUS-MODULE Git
    (`marketplace/community/<id>`) épinglé sur un commit précis. L'index contient ce commit, et
    l'application télécharge les fichiers à CETTE révision exacte (raw.githubusercontent.com/<dépôt>/<commit>/…).
    Si le code du dépôt du contributeur change, rien ne change chez les utilisateurs : une NOUVELLE Pull
    Request (nouveau commit épinglé, nouvelle relecture) est nécessaire, même pour un plugin déjà accepté.

Limites de sécurité appliquées : HTTPS obligatoire, taille bornée, noms de fichiers relatifs et
filtrés (pas de « .. », de chemin absolu ni de lien), extensions autorisées uniquement.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import core

from . import audit, lock, runtime
from . import manifest as manifest_mod

DEFAULT_URL = "https://raw.githubusercontent.com/yo-le-zz/Voktora/main/marketplace"
INDEX_NAME = "index.json"
SCHEMA = 1

ALLOWED_SUFFIXES = frozenset({".py", ".json", ".md", ".txt", ".qss", ".svg", ".png", ".css"})
MAX_FILES = 40
MAX_FILE_BYTES = 512 * 1024
MAX_PLUGIN_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 1024 * 1024
TIMEOUT = 15.0
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REPO_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]{1,39})/([A-Za-z0-9_.-]{1,100})$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TIER_OFFICIAL, TIER_COMMUNITY = "official", "community"
RAW_HOST = "https://raw.githubusercontent.com"
REVOKE_CHECK_SECONDS = 24 * 3600
_PATH_PART_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")

ProgressCallback = Callable[[int, int, str], None]


class MarketError(RuntimeError):
    """Erreur de marketplace affichable telle quelle à l'utilisateur."""


@dataclass
class MarketEntry:
    id: str
    name: str
    version: str
    author: str
    description: str = ""
    api: int = manifest_mod.API_VERSION
    permissions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    homepage: str = ""
    path: str = ""                                   # dossier relatif à la base (plugins/<id>)
    files: dict[str, str] = field(default_factory=dict)    # nom -> sha256
    min_voktora: str = ""
    tier: str = TIER_OFFICIAL
    repo: str = ""                                   # communauté : https://github.com/<auteur>/<dépôt>
    commit: str = ""                                 # communauté : SHA complet du commit épinglé

    @property
    def community(self) -> bool:
        return self.tier == TIER_COMMUNITY

    @property
    def short_commit(self) -> str:
        return self.commit[:7]

    @property
    def compatible(self) -> bool:
        return self.api <= manifest_mod.API_VERSION and (
            not self.min_voktora
            or manifest_mod.version_tuple(core.APP_VERSION) >= manifest_mod.version_tuple(self.min_voktora))


# ── Réseau (point d'entrée unique, remplaçable en test) ──────────────────────────

def _fetch(url: str, timeout: float = TIMEOUT, limit: int = MAX_FILE_BYTES) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise MarketError("Seules les adresses https:// sont acceptées pour le marketplace.")
    request = urllib.request.Request(url, headers={"User-Agent": f"Voktora/{core.APP_VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:      # noqa: S310 - https vérifié
            if not response.geturl().startswith("https://"):
                raise MarketError("Redirection vers un site non sécurisé refusée.")
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise MarketError(f"Le serveur a répondu {exc.code} pour {parsed.path}.") from exc
    except urllib.error.URLError as exc:
        raise MarketError(f"Connexion impossible : {getattr(exc, 'reason', exc)}") from exc
    except TimeoutError as exc:
        raise MarketError("Délai dépassé.") from exc
    if len(data) > limit:
        raise MarketError(f"Fichier trop volumineux (> {limit // 1024} Ko) : {parsed.path}")
    return data


def base_url() -> str:
    return (runtime.market_url() or DEFAULT_URL).rstrip("/")


# ── Validation de l'index ────────────────────────────────────────────────────────

def safe_relative(name: str) -> str:
    """Valide un nom de fichier de plugin (relatif, sans « .. », extension autorisée)."""
    if not isinstance(name, str) or not name or len(name) > 100 or "\\" in name or name.startswith("/"):
        raise MarketError(f"Nom de fichier refusé : {name!r}")
    pure = PurePosixPath(name)
    if any(part in ("", ".", "..") or not _PATH_PART_RE.match(part) for part in pure.parts):
        raise MarketError(f"Nom de fichier refusé : {name!r}")
    if pure.suffix.lower() not in ALLOWED_SUFFIXES:
        raise MarketError(f"Type de fichier non autorisé dans un plugin : {name}")
    return str(pure)


def parse_entry(raw: object) -> MarketEntry:
    manifest, errors = manifest_mod.validate(raw)
    if manifest is None or not isinstance(raw, dict):
        raise MarketError("Entrée d'index invalide : " + " ".join(errors))
    files = raw.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise MarketError(f"{manifest.id} : liste de fichiers absente ou trop longue.")
    clean: dict[str, str] = {}
    for name, digest in files.items():
        if not isinstance(digest, str) or not _SHA_RE.match(digest):
            raise MarketError(f"{manifest.id} : empreinte SHA-256 invalide pour {name}.")
        clean[safe_relative(name)] = digest
    if manifest_mod.MANIFEST_NAME not in clean or manifest.entry not in clean:
        raise MarketError(f"{manifest.id} : {manifest_mod.MANIFEST_NAME} et {manifest.entry} sont obligatoires.")
    tier = raw.get("tier", TIER_OFFICIAL)
    repo = commit = ""
    if tier == TIER_COMMUNITY:
        repo, commit = str(raw.get("repo", "")), str(raw.get("commit", ""))
        if not _REPO_RE.match(repo) or not _COMMIT_RE.match(commit):
            raise MarketError(f"{manifest.id} : dépôt GitHub ou commit épinglé invalide.")
        folder = ""
    elif tier == TIER_OFFICIAL:
        folder = raw.get("path") or f"plugins/{manifest.id}"
        if folder != f"plugins/{manifest.id}":
            raise MarketError(f"{manifest.id} : le dossier doit être plugins/{manifest.id}.")
    else:
        raise MarketError(f"{manifest.id} : niveau « {tier} » inconnu.")
    return MarketEntry(
        id=manifest.id, name=manifest.name, version=manifest.version, author=manifest.author,
        description=manifest.description, api=manifest.api, permissions=list(manifest.permissions),
        tags=list(manifest.tags), homepage=manifest.homepage, path=folder, files=clean,
        min_voktora=manifest.min_voktora, tier=tier, repo=repo, commit=commit,
    )


def parse_index(data: bytes) -> list[MarketEntry]:
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketError(f"Index du marketplace illisible : {exc}") from exc
    if not isinstance(document, dict) or document.get("schema") != SCHEMA or not isinstance(document.get("plugins"), list):
        raise MarketError("Index du marketplace dans un format inconnu (mettez Voktora à jour ?).")
    entries: list[MarketEntry] = []
    seen: set[str] = set()
    for raw in document["plugins"]:
        try:
            entry = parse_entry(raw)
        except MarketError:
            continue                         # une entrée cassée ne bloque pas les autres
        if entry.id not in seen:
            seen.add(entry.id)
            entries.append(entry)
    return sorted(entries, key=lambda e: e.name.lower())


def parse_revoked(data: bytes) -> list[dict]:
    """Liste de retraits : [{"id", "reason", "commit"?}]. `commit` absent = toutes les versions."""
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    items = document.get("revoked", []) if isinstance(document, dict) else []
    result = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and manifest_mod.ID_RE.match(item["id"]):
            commit = item.get("commit", "")
            result.append({"id": item["id"], "reason": str(item.get("reason", ""))[:300],
                           "commit": commit if isinstance(commit, str) and _COMMIT_RE.match(commit) else ""})
    return result


def file_url(entry: MarketEntry, base: str, name: str) -> str:
    """Adresse d'un fichier du plugin. Communauté : commit exact (immuable), sinon dossier de l'index."""
    if entry.community:
        match = _REPO_RE.match(entry.repo)
        if not match or not _COMMIT_RE.match(entry.commit):
            raise MarketError(f"{entry.id} : source invalide.")
        return f"{RAW_HOST}/{match.group(1)}/{match.group(2)}/{entry.commit}/{name}"
    return f"{base}/{entry.path}/{name}"


def permission_changes(old: list[str], new: list[str]) -> list[str]:
    """Permissions ajoutées par une mise à jour (à mettre en évidence avant de confirmer)."""
    return sorted(set(new) - set(old))


def installed_permissions(plugin_id: str) -> list[str] | None:
    info = runtime.find(plugin_id)
    if info is not None:
        return list(info.permissions)
    try:
        return list(manifest_mod.load(runtime.plugins_dir() / plugin_id).permissions)
    except (manifest_mod.ManifestError, OSError):
        return None


def _revoked_path() -> Path:
    return runtime.revoked_path()


def _save_revoked(data: bytes) -> None:
    with contextlib.suppress(OSError):
        _revoked_path().parent.mkdir(parents=True, exist_ok=True)
        _revoked_path().write_text(json.dumps(parse_revoked(data), ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_revocations(force: bool = False) -> bool:
    """Télécharge la liste de retraits (au plus 1 fois / 24 h). Réseau seulement : peut tourner dans un thread.
    Retourne True si la liste a été mise à jour. Silencieux hors ligne."""
    import time
    if not force:
        with contextlib.suppress(OSError):
            if time.time() - _revoked_path().stat().st_mtime < REVOKE_CHECK_SECONDS:
                return False
    try:
        _save_revoked(_fetch(f"{base_url()}/{INDEX_NAME}", limit=MAX_INDEX_BYTES))
    except MarketError:
        return False
    return True


def check_revocations(force: bool = False) -> list[str]:
    """refresh_revocations puis déchargement des plugins retirés (à appeler depuis le thread de l'interface)."""
    refresh_revocations(force)
    return runtime.enforce_revocations()


def _cache_path() -> Path:
    return runtime.plugins_dir().parent / "plugins_data" / "_market_cache.json"


def fetch_index(base: str | None = None, use_cache_on_error: bool = True) -> tuple[list[MarketEntry], bool]:
    """Retourne (entrées, depuis_le_cache). Hors ligne, la dernière copie connue est utilisée."""
    base = (base or base_url()).rstrip("/")
    try:
        data = _fetch(f"{base}/{INDEX_NAME}", limit=MAX_INDEX_BYTES)
        entries = parse_index(data)
    except MarketError:
        if not use_cache_on_error:
            raise
        try:
            return parse_index(_cache_path().read_bytes()), True
        except (OSError, MarketError):
            raise
    with contextlib.suppress(OSError):
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        _cache_path().write_bytes(data)
    _save_revoked(data)
    return entries, False


# ── Installation ──────────────────────────────────────────────────────────────────

def installed_version(plugin_id: str) -> str | None:
    info = runtime.find(plugin_id)
    if info is not None:
        return info.version
    folder = runtime.plugins_dir() / plugin_id
    if (folder / manifest_mod.MANIFEST_NAME).is_file():
        with contextlib.suppress(manifest_mod.ManifestError):
            return manifest_mod.load(folder).version
    return None


def status(entry: MarketEntry) -> str:
    """'new' (non installé), 'update' (mise à jour disponible) ou 'installed'."""
    current = installed_version(entry.id)
    if current is None:
        return "new"
    return "update" if manifest_mod.is_newer(entry.version, current) else "installed"


def _verify_manifest_matches(entry: MarketEntry, files: dict[str, bytes]) -> None:
    try:
        data = json.loads(files[manifest_mod.MANIFEST_NAME].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketError(f"{entry.id} : plugin.json illisible ({exc}).") from exc
    manifest, errors = manifest_mod.validate(data)
    if manifest is None:
        raise MarketError(f"{entry.id} : " + " ".join(errors))
    if (manifest.id, manifest.version, manifest.permissions) != (entry.id, entry.version, sorted(entry.permissions)):
        raise MarketError(f"{entry.id} : le manifeste ne correspond pas à l'index (id, version ou permissions).")


def _write_plugin(plugin_id: str, files: dict[str, bytes], source: dict,
                  audit_permissions: list[str] | None = None) -> Path:
    """Écrit le plugin dans un dossier temporaire puis le substitue à l'ancien (quasi atomique)."""
    root = runtime.plugins_dir()
    root.mkdir(parents=True, exist_ok=True)
    target = root / plugin_id
    staging = Path(tempfile.mkdtemp(prefix=f".installing-{plugin_id}-", dir=root))
    try:
        for name, content in files.items():
            destination = (staging / name).resolve()
            if not destination.is_relative_to(staging.resolve()):
                raise MarketError(f"Chemin refusé : {name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        if audit_permissions is not None:
            errors, _warnings = audit.scan_folder(staging, audit_permissions)
            if errors:
                raise MarketError("Analyse de sécurité : " + " ; ".join(errors[:5]))
            source = {**source, "origin": "market", "files": lock.hash_tree(staging)}
        lock.write_lock(staging, source)
        backup = None
        if target.exists():
            backup = root / f".replaced-{plugin_id}"
            shutil.rmtree(backup, ignore_errors=True)
            target.rename(backup)
        try:
            staging.rename(target)
        except OSError:
            if backup is not None:
                backup.rename(target)             # on remet l'ancienne version
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        return target
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def install(entry: MarketEntry, base: str | None = None, on_progress: ProgressCallback | None = None) -> Path:
    """Télécharge, vérifie (SHA-256 de chaque fichier) puis installe. Ne charge PAS le plugin."""
    if not entry.compatible:
        raise MarketError(f"{entry.name} nécessite une version plus récente de Voktora (API {entry.api}).")
    base = (base or base_url()).rstrip("/")
    files: dict[str, bytes] = {}
    total = len(entry.files)
    size = 0
    for index, (name, digest) in enumerate(sorted(entry.files.items()), start=1):
        if on_progress:
            on_progress(index - 1, total, name)
        content = _fetch(file_url(entry, base, name), limit=MAX_FILE_BYTES)
        size += len(content)
        if size > MAX_PLUGIN_BYTES:
            raise MarketError(f"{entry.name} dépasse {MAX_PLUGIN_BYTES // 1024} Ko : installation refusée.")
        if hashlib.sha256(content).hexdigest() != digest:
            raise MarketError(
                f"Empreinte incorrecte pour {name} : fichier modifié ou index périmé. Installation annulée.")
        files[name] = content
    _verify_manifest_matches(entry, files)
    if on_progress:
        on_progress(total, total, "")
    source = {"market": base, "version": entry.version, "tier": entry.tier}
    if entry.community:
        source |= {"repo": entry.repo, "commit": entry.commit}
    return _write_plugin(entry.id, files, source, audit_permissions=list(entry.permissions))


def install_from_path(source: Path) -> tuple[str, Path]:
    """Installe un plugin local : dossier (avec plugin.json) ou archive .zip. Retourne (id, dossier)."""
    source = Path(source)
    files: dict[str, bytes] = {}
    if source.is_dir():
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise MarketError(f"Lien symbolique refusé : {path.name}")
            if path.is_file() and not any(part.startswith(".") for part in path.relative_to(source).parts):
                files[safe_relative(path.relative_to(source).as_posix())] = path.read_bytes()
    elif source.suffix.lower() == ".zip" and source.is_file():
        try:
            with zipfile.ZipFile(source) as archive:
                infos = [i for i in archive.infolist() if not i.is_dir()]
                prefix = ""
                names = [i.filename for i in infos]
                if names and all(n.startswith(names[0].split("/")[0] + "/") for n in names) \
                        and manifest_mod.MANIFEST_NAME not in names:
                    prefix = names[0].split("/")[0] + "/"
                for item in infos:
                    if (item.external_attr >> 28) == 0xA:                 # lien symbolique
                        raise MarketError(f"Lien symbolique refusé : {item.filename}")
                    if item.file_size > MAX_FILE_BYTES:
                        raise MarketError(f"Fichier trop volumineux dans l'archive : {item.filename}")
                    name = safe_relative(item.filename[len(prefix):])
                    files[name] = archive.read(item)
        except zipfile.BadZipFile as exc:
            raise MarketError("Archive .zip invalide.") from exc
    else:
        raise MarketError("Choisissez un dossier de plugin ou une archive .zip.")

    if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_PLUGIN_BYTES:
        raise MarketError("Plugin trop volumineux.")
    if manifest_mod.MANIFEST_NAME not in files:
        raise MarketError(f"{manifest_mod.MANIFEST_NAME} manquant à la racine du plugin.")
    try:
        data = json.loads(files[manifest_mod.MANIFEST_NAME].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketError(f"plugin.json illisible : {exc}") from exc
    manifest, errors = manifest_mod.validate(data)
    if manifest is None:
        raise MarketError(" ".join(errors))
    if manifest.entry not in files:
        raise MarketError(f"Fichier d'entrée « {manifest.entry} » absent.")
    return manifest.id, _write_plugin(manifest.id, files, {"origin": "local", "local": str(source), "version": manifest.version})


def read_local_manifest(source: Path) -> manifest_mod.Manifest:
    """Manifeste d'un dossier/zip local, pour montrer les permissions AVANT d'installer."""
    source = Path(source)
    try:
        if source.is_dir():
            return manifest_mod.load(source)
        with zipfile.ZipFile(source) as archive:
            names = [n for n in archive.namelist() if n.endswith(manifest_mod.MANIFEST_NAME)]
            if not names:
                raise MarketError(f"{manifest_mod.MANIFEST_NAME} introuvable dans l'archive.")
            names.sort(key=len)
            manifest, errors = manifest_mod.validate(json.loads(archive.read(names[0]).decode("utf-8")))
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, manifest_mod.ManifestError) as exc:
        raise MarketError(str(exc)) from exc
    if manifest is None:
        raise MarketError(" ".join(errors))
    return manifest


def uninstall(plugin_id: str, purge_data: bool = False) -> bool:
    """Supprime le dossier du plugin (et ses données si demandé). Retourne False s'il n'existait pas."""
    if not manifest_mod.ID_RE.match(plugin_id):
        raise MarketError("Identifiant de plugin invalide.")
    runtime.forget(plugin_id)
    root = runtime.plugins_dir().resolve()
    folder = (root / plugin_id).resolve()
    if not folder.is_relative_to(root) or folder == root:
        raise MarketError("Chemin refusé.")
    existed = folder.exists()
    if folder.is_dir() and not folder.is_symlink():
        shutil.rmtree(folder)
    elif folder.exists():
        folder.unlink()
    if purge_data:
        shutil.rmtree(core.get_data_dir() / "plugins_data" / plugin_id, ignore_errors=True)
    return existed
