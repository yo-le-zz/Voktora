"""
Voktora — sync.configpack (1.1.4)
« Push config » : paquet de configuration complet, versionné et hachée (« révision de configuration »), son aperçu des
différences, son application atomique avec sauvegarde et retour arrière, et la règle de blocage de la synchronisation
quand les configurations divergent. Logique sans Qt ni réseau (disque seulement, via `ConfigEnv`).

Contenu du paquet (JSON) :
  sections.app_config      réglages portables (jamais les réglages propres au PC, les secrets, les clés d'API, ni les
                           chemins absolus de cette machine : listés dans `excluded`) ;
  sections.categories / custom_statuses ;
  sections.hooks           hooks.json (⚠ commandes : appliquées seulement sur accord explicite) ;
  sections.plugins         plugins du marketplace (id, version, origine) + options ; le CODE des plugins n'est jamais
                           copié : le pair les réinstalle depuis le marketplace (vérification SHA-256 par market.install).
                           Les plugins hors marketplace sont seulement listés (`local`) ;
  files                    thèmes personnalisés, thèmes/icônes/styles installés via les boutiques (données seulement),
                           profils, modèles, raccourcis — contenu vérifié (chemins, tailles, SHA-256, contenu actif refusé).
Jamais : coffre, jetons, mots de passe, compte GitHub. Les sauvegardes locales restent dans le dossier de données (0600).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .store import APP_CONFIG_LOCAL_ONLY, _merge_ai, _strip_ai_keys, is_secret_key

FORMAT, VERSION = "voktora-config", 1
MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_FILES = 2 * 1024 * 1024, 12 * 1024 * 1024, 600
SHOP_KINDS = ("themes", "icons", "styles")
FLAT_DIRS = ("themes", "profiles", "templates")           # dossiers de fichiers .json
FLAT_FILES = ("shortcuts.json",)
_NAME_RE = re.compile(r"^[\w][\w .+()-]{0,99}\.json$")
_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
_PLUGIN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_WIN_PATH = re.compile(r"^[A-Za-z]:[\\/]")
BACKUPS_KEPT = 10


class PackError(ValueError):
    """Paquet de configuration invalide ou dangereux (message affichable)."""


class ConfigIOLike(Protocol):
    def load(self) -> dict: ...
    def save(self, cfg: dict) -> None: ...


@dataclass
class ConfigEnv:
    data_dir: Path
    io: ConfigIOLike

    @property
    def plugins_dir(self) -> Path:
        return Path(self.data_dir) / "plugins"


# ── petits outils ────────────────────────────────────────────────────────────

def _canon(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_local_path(value) -> bool:
    return isinstance(value, str) and (value.startswith(("/", "~/", "\\\\")) or bool(_WIN_PATH.match(value)))


def _volatile(key: str) -> bool:
    return key.startswith("last_") or key.endswith("_seen")


def _scrub(value):
    """Copie sans aucune clé secrète ni volatile, récursivement."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if not is_secret_key(str(k)) and not _volatile(str(k))}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _contains_secret(value) -> str:
    if isinstance(value, dict):
        for k, v in value.items():
            if is_secret_key(str(k)):
                return str(k)
            found = _contains_secret(v)
            if found:
                return found
    elif isinstance(value, list):
        for v in value:
            found = _contains_secret(v)
            if found:
                return found
    return ""


def portable_app_config(app: dict) -> tuple[dict, list[str]]:
    """(réglages portables, clés exclues car propres à ce PC : chemins absolus)."""
    out: dict = {}
    excluded: list[str] = []
    for key, value in (app or {}).items():
        if key in APP_CONFIG_LOCAL_ONLY or is_secret_key(key) or _volatile(key):
            continue
        if _is_local_path(value):
            excluded.append(key)
            continue
        if key == "ai":
            value = _strip_ai_keys(value)
        out[key] = _scrub(value)
    return out, sorted(excluded)


def merge_app_config(current: dict, incoming: dict) -> dict:
    """Réglages locaux conservés (propres au PC, secrets, volatils, chemins) + réglages reçus ; ce qui est portable ici et
    absent du paquet est supprimé (alignement exact)."""
    out: dict = {}
    for key, value in (current or {}).items():
        if key in APP_CONFIG_LOCAL_ONLY or is_secret_key(key) or _volatile(key) or _is_local_path(value):
            out[key] = value
    for key, value in (incoming or {}).items():
        if key in APP_CONFIG_LOCAL_ONLY or is_secret_key(key) or _volatile(key):
            continue
        if key == "ai":
            out[key] = _merge_ai((current or {}).get("ai"), value)
        elif key == "plugins" and isinstance(value, dict):
            local_plugins = (current or {}).get("plugins")
            keep = {k: v for k, v in (local_plugins or {}).items() if _volatile(k)} if isinstance(local_plugins, dict) else {}
            out[key] = {**value, **keep}
        else:
            out[key] = value
    return out


# ── construction du paquet ───────────────────────────────────────────────────

def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _clean_hooks(raw) -> dict:
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for name, entries in raw.items():
        if not isinstance(entries, list) or not re.match(r"^[a-z_]{1,40}$", str(name)):
            continue
        clean = []
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("cmd"), str) and e.get("type") in ("shell", "python"):
                clean.append({k: _scrub(v) for k, v in e.items() if k in ("type", "cmd", "label", "enabled")
                              and not is_secret_key(k)})
        out[str(name)] = clean
    return out


def _plugins_section(env: ConfigEnv) -> dict:
    market: dict[str, dict] = {}
    local: list[str] = []
    options: dict[str, dict] = {}
    root = env.plugins_dir
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        if not folder.is_dir() or folder.name.startswith(".") or not _PLUGIN_ID_RE.match(folder.name):
            continue
        lock = _read_json(folder / ".source.json")
        if isinstance(lock, dict) and lock.get("origin") == "market":
            entry = {"version": str(lock.get("version", "")), "tier": str(lock.get("tier", "official"))}
            if lock.get("repo"):
                entry |= {"repo": str(lock["repo"]), "commit": str(lock.get("commit", ""))}
            market[folder.name] = entry
            opts = _read_json(Path(env.data_dir) / "plugins_data" / folder.name / "settings.json")
            if isinstance(opts, dict) and opts:
                options[folder.name] = _scrub(opts)
        else:
            local.append(folder.name)
    return {"market": market, "local": local, "options": options}


def _collect_files(env: ConfigEnv) -> dict[str, bytes]:
    base = Path(env.data_dir)
    found: dict[str, bytes] = {}

    def take(rel: str, path: Path) -> None:
        with contextlib.suppress(OSError):
            if path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_FILE_BYTES:
                found[rel] = path.read_bytes()

    for folder in FLAT_DIRS:
        d = base / folder
        for p in sorted(d.glob("*.json")) if d.is_dir() else []:
            if _NAME_RE.match(p.name):
                take(f"{folder}/{p.name}", p)
    for name in FLAT_FILES:
        take(name, base / name)
    for kind in SHOP_KINDS:
        d = base / "shops" / kind
        for item in sorted(d.iterdir()) if d.is_dir() else []:
            if not item.is_dir() or item.name.endswith(".new") or not _ID_RE.match(item.name):
                continue
            for p in sorted(item.rglob("*")):
                take(f"shops/{kind}/{item.name}/{p.relative_to(item).as_posix()}", p)
    return found


def compute_rev(sections: dict, file_shas: dict[str, str]) -> str:
    """Révision de configuration : hachage du contenu portable (options des plugins et plugins locaux exclus : ils bougent
    sans cesse ou ne sont pas transférables)."""
    plugins = sections.get("plugins", {}).get("market", {})
    material = {"app_config": sections.get("app_config", {}), "categories": sections.get("categories", []),
                "custom_statuses": sections.get("custom_statuses", {}), "hooks": sections.get("hooks", {}),
                "plugins": plugins, "files": dict(sorted(file_shas.items()))}
    return _sha(_canon(material))


def build_pack(env: ConfigEnv, device_id: str = "", device_name: str = "", app_version: str = "",
               now: float | None = None) -> dict:
    cfg = env.io.load()
    app, excluded = portable_app_config(cfg.get("app_config") or {})
    hooks = _clean_hooks(_read_json(Path(env.data_dir) / "hooks.json"))
    sections = {"app_config": app, "categories": _scrub(cfg.get("categories", [])),
                "custom_statuses": _scrub(cfg.get("custom_statuses", {})), "hooks": hooks,
                "plugins": _plugins_section(env)}
    raw = _collect_files(env)
    total = 0
    files: dict[str, dict] = {}
    for rel, data in raw.items():
        total += len(data)
        if total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES:
            raise PackError("Configuration trop volumineuse pour un push (thèmes/icônes > 12 Mo ou > 600 fichiers).")
        files[rel] = {"sha": _sha(data), "size": len(data), "data": base64.b64encode(data).decode()}
    rev = compute_rev(sections, {k: v["sha"] for k, v in files.items()})
    return {"format": FORMAT, "version": VERSION, "app_version": app_version, "created": time.time() if now is None else now,
            "device": device_id, "device_name": device_name, "rev": rev, "excluded": excluded,
            "sections": sections, "files": files}


def local_rev(env: ConfigEnv) -> str:
    return build_pack(env)["rev"]


# ── vérification d'un paquet reçu ────────────────────────────────────────────

def _check_file(rel: str, data: bytes) -> None:
    parts = rel.split("/")
    if rel in FLAT_FILES or len(parts) == 2 and parts[0] in FLAT_DIRS and _NAME_RE.match(parts[1]):
        pass
    elif len(parts) >= 4 and parts[0] == "shops" and parts[1] in SHOP_KINDS and _ID_RE.match(parts[2]) \
            and all(p and p not in (".", "..") and not p.startswith(".") for p in parts[3:]):
        kind, name = parts[1], "/".join(parts[3:])
        try:
            import shops
            if name != "item.json":
                shops.safe_name(kind, name)
            shops.check_content(kind, name, data)
        except ImportError:                                       # pragma: no cover — hors application
            raise PackError(f"{rel} : contrôle de contenu indisponible.") from None
        except Exception as exc:
            raise PackError(f"{rel} : {exc}") from exc
        return
    else:
        raise PackError(f"Chemin refusé dans le paquet : {rel!r}")
    try:
        json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PackError(f"{rel} : JSON invalide.") from exc


def verify_pack(pack) -> dict:
    """Valide un paquet (reçu du réseau = non fiable). Retourne le paquet ; lève PackError."""
    if not isinstance(pack, dict) or pack.get("format") != FORMAT:
        raise PackError("Ce n'est pas un paquet de configuration Voktora.")
    try:
        version = int(pack.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version < 1 or version > VERSION:
        raise PackError("Paquet créé par une version plus récente de Voktora : mettez à jour ce PC.")
    sections, files = pack.get("sections"), pack.get("files")
    if not isinstance(sections, dict) or not isinstance(files, dict):
        raise PackError("Paquet incomplet.")
    for key, kind in (("app_config", dict), ("categories", list), ("custom_statuses", dict), ("hooks", dict), ("plugins", dict)):
        if not isinstance(sections.get(key), kind):
            raise PackError(f"Section « {key} » invalide.")
    secret = _contains_secret({k: v for k, v in sections.items()})
    if secret:
        raise PackError(f"Paquet refusé : il contient un champ secret ({secret}).")
    for key in sections["app_config"]:
        if key in APP_CONFIG_LOCAL_ONLY:
            raise PackError(f"Réglage propre au PC refusé : {key}")
    plug = sections["plugins"]
    for pid, info in (plug.get("market") or {}).items():
        if not _PLUGIN_ID_RE.match(str(pid)) or not isinstance(info, dict):
            raise PackError(f"Plugin invalide : {pid!r}")
    for pid in (plug.get("options") or {}):
        if not _PLUGIN_ID_RE.match(str(pid)):
            raise PackError(f"Options de plugin invalides : {pid!r}")
    if len(files) > MAX_FILES:
        raise PackError("Trop de fichiers dans le paquet.")
    total = 0
    shas: dict[str, str] = {}
    for rel, meta in files.items():
        if not isinstance(meta, dict) or not isinstance(meta.get("data"), str):
            raise PackError(f"Fichier invalide : {rel!r}")
        try:
            data = base64.b64decode(meta["data"], validate=True)
        except ValueError as exc:
            raise PackError(f"{rel} : contenu illisible.") from exc
        total += len(data)
        if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise PackError("Paquet trop volumineux.")
        if _sha(data) != meta.get("sha"):
            raise PackError(f"{rel} : empreinte incorrecte (paquet altéré).")
        _check_file(str(rel), data)
        shas[str(rel)] = meta["sha"]
    if compute_rev(sections, shas) != pack.get("rev"):
        raise PackError("La révision ne correspond pas au contenu (paquet altéré ou incompatible).")
    return pack


def pack_files(pack: dict) -> dict[str, bytes]:
    return {rel: base64.b64decode(meta["data"]) for rel, meta in pack["files"].items()}


# ── aperçu des différences ───────────────────────────────────────────────────

ADD, CHANGE, REMOVE = "add", "change", "remove"
KIND_LABEL = {ADD: "ajout", CHANGE: "modification", REMOVE: "suppression"}


@dataclass
class DiffEntry:
    section: str
    key: str
    kind: str
    detail: str = ""
    sensitive: bool = False


@dataclass
class ConfigDiff:
    entries: list[DiffEntry] = field(default_factory=list)
    plugins_to_install: list[dict] = field(default_factory=list)
    plugins_unmanaged: list[str] = field(default_factory=list)     # présents seulement ici / hors marketplace : conservés
    excluded: list[str] = field(default_factory=list)

    def count(self, kind: str) -> int:
        return sum(1 for e in self.entries if e.kind == kind)

    @property
    def empty(self) -> bool:
        return not self.entries and not self.plugins_to_install

    @property
    def has_hooks(self) -> bool:
        return any(e.section == "hooks" for e in self.entries)

    def summary(self) -> str:
        if self.empty:
            return "Aucune différence : configuration identique."
        parts = [f"{self.count(k)} {label}(s)" for k, label in KIND_LABEL.items() if self.count(k)]
        if self.plugins_to_install:
            parts.append(f"{len(self.plugins_to_install)} plugin(s) à installer")
        return ", ".join(parts)

    def lines(self) -> list[str]:
        out = [f"{KIND_LABEL[e.kind]} : {e.section}/{e.key}" + (f"  ({e.detail})" if e.detail else "")
               + ("  ⚠ exécute des commandes" if e.sensitive else "") for e in self.entries]
        out += [f"à installer depuis le marketplace : {p['id']} {p.get('version', '')}" for p in self.plugins_to_install]
        out += [f"conservé (hors marketplace ou absent du paquet) : {p}" for p in self.plugins_unmanaged]
        return out


def _file_groups(files: dict[str, str]) -> dict[str, dict[str, str]]:
    groups: dict[str, dict[str, str]] = {}
    for rel, sha in files.items():
        parts = rel.split("/")
        key = "/".join(parts[:3]) if parts[0] == "shops" and len(parts) >= 4 else rel
        groups.setdefault(key, {})[rel] = sha
    return groups


def diff_packs(current: dict, incoming: dict) -> ConfigDiff:
    """Ce qui changerait sur ce PC (`current` = paquet local) si `incoming` était appliqué."""
    out = ConfigDiff(excluded=list(incoming.get("excluded", [])))
    cs, ns = current["sections"], incoming["sections"]

    def compare(section: str, old: dict, new: dict, sensitive: bool = False) -> None:
        for key in sorted(set(old) | set(new)):
            if key not in old:
                out.entries.append(DiffEntry(section, key, ADD, sensitive=sensitive))
            elif key not in new:
                out.entries.append(DiffEntry(section, key, REMOVE, sensitive=sensitive))
            elif old[key] != new[key]:
                out.entries.append(DiffEntry(section, key, CHANGE, sensitive=sensitive))

    compare("réglages", cs["app_config"], ns["app_config"])
    if cs["categories"] != ns["categories"]:
        out.entries.append(DiffEntry("catégories", "liste", CHANGE))
    compare("statuts", cs["custom_statuses"], ns["custom_statuses"])
    compare("hooks", {k: v for k, v in cs["hooks"].items() if v}, {k: v for k, v in ns["hooks"].items() if v}, True)
    cm, nm = cs["plugins"].get("market", {}), ns["plugins"].get("market", {})
    for pid, info in sorted(nm.items()):
        if pid not in cm:
            out.entries.append(DiffEntry("plugins", pid, ADD, f"version {info.get('version', '?')}"))
            out.plugins_to_install.append({"id": pid, **info})
        elif cm[pid].get("version") != info.get("version"):
            out.entries.append(DiffEntry("plugins", pid, CHANGE, f"{cm[pid].get('version')} → {info.get('version')}"))
            out.plugins_to_install.append({"id": pid, **info})
    out.plugins_unmanaged = sorted((set(cm) - set(nm)) | set(cs["plugins"].get("local", [])))
    cf = _file_groups({k: v["sha"] for k, v in current["files"].items()})
    nf = _file_groups({k: v["sha"] for k, v in incoming["files"].items()})
    for key in sorted(set(cf) | set(nf)):
        if key not in cf:
            out.entries.append(DiffEntry("fichiers", key, ADD))
        elif key not in nf:
            out.entries.append(DiffEntry("fichiers", key, REMOVE))
        elif cf[key] != nf[key]:
            out.entries.append(DiffEntry("fichiers", key, CHANGE))
    return out


# ── application atomique ─────────────────────────────────────────────────────

@dataclass
class ApplyOptions:
    allow_hooks: bool = False
    delete_missing: bool = True
    install_plugins: bool = False
    installer: Callable[[str, dict], tuple[bool, str]] | None = None
    backups_dir: Path | None = None


@dataclass
class ApplyResult:
    ok: bool = False
    changes: int = 0
    backup: str = ""
    skipped: list[str] = field(default_factory=list)
    plugin_results: dict[str, str] = field(default_factory=dict)
    error: str = ""
    rolled_back: bool = False
    new_rev: str = ""


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cfg-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _save_sections(io, sections: dict) -> None:
    saver = getattr(io, "save_sections", None)
    if saver:
        saver(sections)
        return
    cfg = io.load()
    cfg.update(sections)
    io.save(cfg)


def _snapshot(env: ConfigEnv, backups_dir: Path, pack_rev: str, extra: list[str]) -> tuple[Path, list[str]]:
    base = Path(env.data_dir)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = backups_dir / f"{stamp}-{pack_rev[:8]}"
    n = 1
    while dest.exists():
        n += 1
        dest = backups_dir / f"{stamp}-{pack_rev[:8]}-{n}"
    dest.mkdir(parents=True, mode=0o700)
    targets = ["hooks.json", *FLAT_FILES, *FLAT_DIRS, "shops", *extra]
    existed: list[str] = []
    for rel in targets:
        src = base / rel
        if src.is_dir():
            shutil.copytree(src, dest / "files" / rel, symlinks=False)
            existed.append(rel)
        elif src.is_file():
            (dest / "files" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / "files" / rel)
            existed.append(rel)
    cfg = env.io.load()
    parts = {k: cfg.get(k) for k in ("app_config", "categories", "custom_statuses")}
    fd = os.open(dest / "config-sections.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"targets": targets, "existed": existed, "sections": parts}, handle, ensure_ascii=False)
    kept = sorted(p for p in backups_dir.iterdir() if p.is_dir())
    for old in kept[:-BACKUPS_KEPT]:
        shutil.rmtree(old, ignore_errors=True)
    return dest, targets


def restore_backup(env: ConfigEnv, backup: Path) -> None:
    """Retour arrière : fichiers puis réglages tels qu'ils étaient avant l'application."""
    meta = json.loads((backup / "config-sections.json").read_text(encoding="utf-8"))
    base = Path(env.data_dir)
    for rel in meta["targets"]:
        _remove(base / rel)
        if rel in meta["existed"]:
            src = backup / "files" / rel
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, base / rel)
            else:
                shutil.copy2(src, base / rel)
    sections = {k: v for k, v in meta["sections"].items() if v is not None}
    _save_sections(env.io, sections)


def apply_pack(env: ConfigEnv, pack: dict, options: ApplyOptions | None = None) -> ApplyResult:
    """Applique `pack` (déjà reçu). Sauvegarde d'abord ; en cas d'erreur, tout est remis comme avant."""
    opts = options or ApplyOptions()
    result = ApplyResult()
    try:
        verify_pack(pack)
    except PackError as exc:
        result.error = str(exc)
        return result
    base = Path(env.data_dir)
    current = build_pack(env)
    diff = diff_packs(current, pack)
    sections, incoming_files = pack["sections"], pack_files(pack)
    option_ids = [pid for pid in (sections["plugins"].get("options") or {})]
    extra = [f"plugins_data/{pid}/settings.json" for pid in option_ids]
    backups = opts.backups_dir or (base / "sync" / "config-backups")
    backups.mkdir(parents=True, exist_ok=True)
    try:
        backup, _ = _snapshot(env, backups, pack["rev"], extra)
    except OSError as exc:
        result.error = f"Sauvegarde impossible, rien n'a été modifié ({exc})."
        return result
    result.backup = str(backup)
    try:
        # 1. fichiers (thèmes, icônes, styles, profils, modèles, raccourcis)
        local_files = {k: v["sha"] for k, v in current["files"].items()}
        for rel, data in incoming_files.items():
            if local_files.get(rel) != _sha(data):
                _write_atomic(base / rel, data)
                result.changes += 1
        if opts.delete_missing:
            for rel in sorted(set(local_files) - set(incoming_files)):
                _remove(base / rel)
                result.changes += 1
                parent = (base / rel).parent
                while parent != base and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
        # 2. hooks (commandes : seulement sur accord explicite)
        if sections["hooks"] != current["sections"]["hooks"]:
            if opts.allow_hooks:
                _write_atomic(base / "hooks.json", json.dumps(sections["hooks"], indent=2, ensure_ascii=False).encode())
                result.changes += 1
            else:
                result.skipped.append("hooks (commandes) : non appliqués, accord explicite nécessaire")
        # 3. options des plugins (les secrets déjà présents ici sont conservés)
        for pid, opt in (sections["plugins"].get("options") or {}).items():
            path = base / "plugins_data" / pid / "settings.json"
            old = _read_json(path)
            keep = {k: v for k, v in old.items() if is_secret_key(k)} if isinstance(old, dict) else {}
            _write_atomic(path, json.dumps({**opt, **keep}, ensure_ascii=False, indent=2).encode())
        # 4. réglages (en dernier : si l'écriture échoue, tout le reste est annulé)
        cfg = env.io.load()
        app = merge_app_config(cfg.get("app_config") or {}, sections["app_config"])
        shops_cfg = app.get("shops")
        if isinstance(shops_cfg, dict):
            pack_icons = {r.split("/")[2] for r in incoming_files if r.startswith("shops/icons/")}
            if shops_cfg.get("icon_pack") and shops_cfg["icon_pack"] not in pack_icons:
                shops_cfg["icon_pack"] = ""
        if app != cfg.get("app_config") or cfg.get("categories") != sections["categories"] \
                or cfg.get("custom_statuses") != sections["custom_statuses"]:
            _save_sections(env.io, {"app_config": app, "categories": sections["categories"],
                                    "custom_statuses": sections["custom_statuses"]})
            result.changes += 1
    except Exception as exc:  # noqa: BLE001 — tout échec = retour arrière complet
        result.error = f"{type(exc).__name__}: {exc}"
        try:
            restore_backup(env, backup)
            result.rolled_back = True
        except Exception as exc2:  # noqa: BLE001
            result.error += f" — retour arrière incomplet ({exc2}) : sauvegarde dans {backup}"
        return result
    # 5. plugins : réinstallés depuis le marketplace (hors transaction : réseau)
    for item in diff.plugins_to_install:
        if not (opts.install_plugins and opts.installer):
            result.skipped.append(f"plugin {item['id']} : installation non demandée")
            continue
        try:
            ok, msg = opts.installer(item["id"], item)
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, str(exc)
        result.plugin_results[item["id"]] = ("installé" if ok else f"échec : {msg}") if not ok or not msg else msg
        if not ok:
            result.skipped.append(f"plugin {item['id']} : {msg}")
    result.ok = True
    result.new_rev = local_rev(env)
    return result


# ── règle de blocage ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RevInfo:
    rev: str = ""
    applied_rev: str = ""            # dernière configuration du groupe appliquée ici
    applied_local_rev: str = ""      # révision locale juste après cette application

    @classmethod
    def from_dict(cls, d) -> RevInfo | None:
        if not isinstance(d, dict) or not d.get("rev"):
            return None
        return cls(str(d["rev"]), str(d.get("applied_rev", "")), str(d.get("applied_local_rev", "")))

    def aligned_with(self, target: str) -> bool:
        """Alignée : identique, ou appliquée telle quelle (réserves connues : hooks refusés, plugin non installé) et
        inchangée depuis."""
        return self.rev == target or (bool(self.applied_rev) and self.applied_rev == target and self.rev == self.applied_local_rev)


@dataclass(frozen=True)
class ConfigRef:
    rev: str
    seq: int = 0
    by: str = ""
    by_name: str = ""
    ts: float = 0.0

    def to_dict(self) -> dict:
        return {"rev": self.rev, "seq": self.seq, "by": self.by, "by_name": self.by_name, "ts": self.ts}

    @classmethod
    def from_dict(cls, d) -> ConfigRef | None:
        if not isinstance(d, dict) or not d.get("rev"):
            return None
        try:
            return cls(str(d["rev"]), int(d.get("seq", 0)), str(d.get("by", "")), str(d.get("by_name", "")),
                       float(d.get("ts", 0)))
        except (TypeError, ValueError):
            return None


def newest_ref(a: ConfigRef | None, b: ConfigRef | None) -> ConfigRef | None:
    if a is None or b is None:
        return a or b
    if a.seq != b.seq:
        return a if a.seq > b.seq else b
    return a if (a.by, a.rev) <= (b.by, b.rev) else b


@dataclass(frozen=True)
class GateResult:
    ok: bool
    code: str                        # ok | disabled | unverifiable | local-diverged | peer-diverged
    message: str = ""
    actions: tuple[str, ...] = ()    # actions proposées : push, apply


MSG_DIVERGED = "Configuration différente : poussez la vôtre (Push config) ou appliquez celle du groupe."


def evaluate_gate(*, enabled: bool, directed: bool, my_id: str, peer_id: str, leader_id: str,
                  local: RevInfo, remote: RevInfo | None, ref: ConfigRef | None, peer_name: str = "l'autre PC") -> GateResult:
    """Un PC ne synchronise que si sa configuration est alignée sur celle de référence du groupe.
    Référence : égalitaire = dernière configuration poussée (`ref`) ; dirigé = celle du chef."""
    if not enabled:
        return GateResult(True, "disabled")
    if remote is None:
        return GateResult(True, "unverifiable", f"{peer_name} utilise une version sans « Push config » : alignement non vérifiable.")
    target = ""
    if directed and leader_id:
        if leader_id == my_id:
            target = local.rev
        elif leader_id == peer_id:
            target = remote.rev
        elif ref:
            target = ref.rev
    elif ref:
        target = ref.rev
    if not target:
        if local.rev == remote.rev:
            return GateResult(True, "ok")
        return GateResult(False, "local-diverged", MSG_DIVERGED + " (aucune référence de groupe n'existe encore)", ("push", "apply"))
    if not local.aligned_with(target):
        if directed and leader_id and leader_id != my_id:
            return GateResult(False, "local-diverged",
                              "Configuration différente de celle du chef : appliquez celle du chef (ou demandez-lui d'adopter la vôtre).",
                              ("apply", "push"))
        return GateResult(False, "local-diverged", MSG_DIVERGED, ("push", "apply"))
    if not remote.aligned_with(target):
        return GateResult(False, "peer-diverged",
                          f"Configuration différente sur « {peer_name} » : poussez la vôtre (Push config) pour l'aligner.", ("push",))
    return GateResult(True, "ok")
