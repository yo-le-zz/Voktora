"""
Voktora — core.config_store
Lecture / écriture / migration de config.json.

Schéma 9 : les anciennes listes « instances » et « intents » sont fusionnées
dans une seule liste « projects » ; les catégories deviennent des objets
{name, emoji, color} gérés par l'utilisateur.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from . import constants, paths

_config_cache: dict | None = None


def invalidate_cache() -> None:
    """Force le prochain appel à _load_config() à relire config.json depuis le disque."""
    global _config_cache
    _config_cache = None

# ──────────────────────────────────────────────
# NORMALISATION DES ENTRÉES (projets, catégories)
# ──────────────────────────────────────────────

def _path_basename(raw_path: str) -> str:
    """Dernier segment d'un chemin, quel que soit le séparateur (Windows ou POSIX).

    Un chemin exporté depuis Windows doit rester lisible sous Linux, où pathlib
    ne reconnaît pas l'antislash comme séparateur.
    """
    return raw_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def normalize_entry(entry: dict) -> bool:
    """Complète une entrée de projet avec les champs par défaut manquants.

    Retourne True si l'entrée a été modifiée. Source unique des valeurs par
    défaut : création, import et clone n'ont plus à les dupliquer.
    """
    changed = False
    defaults: list[tuple[str, object]] = [
        ("note", ""),
        ("status", constants.DEFAULT_PROJECT_STATUS),
        ("color", None),
        ("emoji", None),
        ("category", None),
        ("language", None),
        ("tags", []),
        ("github_repo", None),
        ("github_branch", "main"),
        ("github_branches", [entry.get("github_branch") or "main"]),
        ("github_token", ""),
        ("github_token_protected", False),
    ]
    for key, default in defaults:
        if key not in entry:
            entry[key] = default
            changed = True
    if entry.get("tags") is None:
        entry["tags"] = []
        changed = True
    return changed


def normalize_categories(raw: object, used_names: list[str] | tuple[str, ...] = ()) -> list[dict]:
    """Convertit la liste de catégories en objets {name, emoji, color}.

    Accepte l'ancien format (liste de chaînes) comme le nouveau, dédoublonne
    sans tenir compte de la casse et ajoute les catégories référencées par des
    projets (`used_names`) mais absentes de la liste — pour qu'aucune catégorie
    déjà attribuée ne disparaisse lors de la migration.
    """
    result: list[dict] = []
    seen: set[str] = set()

    def _add(name: object, emoji: object = "", color: object = "") -> None:
        if not isinstance(name, str):
            return
        name = name.strip()
        if not name or name.lower() in seen:
            return
        seen.add(name.lower())
        result.append({
            "name": name[: constants.MAX_CATEGORY_NAME_LENGTH],
            "emoji": emoji if isinstance(emoji, str) else "",
            "color": color if isinstance(color, str) else "",
        })

    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            _add(item)
        elif isinstance(item, dict):
            _add(item.get("name"), item.get("emoji", ""), item.get("color", ""))
    for name in used_names:
        _add(name)
    return result


def _fold_legacy_kinds(cfg: dict) -> bool:
    """Fusionne les anciennes listes « instances » / « intents » dans « projects ».

    Idempotent : sans clé héritée, ne fait rien. Les instances passent avant les
    intents, donc leurs champs GitHub priment en cas de doublon de chemin.
    """
    legacy_keys = [key for key in ("instances", "intents") if key in cfg]
    if not legacy_keys:
        return False
    projects = cfg.setdefault("projects", [])
    known = {e.get("path") for e in projects if isinstance(e, dict)}
    for key in legacy_keys:
        for entry in cfg.pop(key) or []:
            if not isinstance(entry, dict) or not entry.get("path") or entry["path"] in known:
                continue
            known.add(entry["path"])
            entry.setdefault("name", _path_basename(entry["path"]))
            projects.append(entry)
    return True


def _migrate_storage(cfg: dict) -> bool:
    """Remplace les racines instances/intents par une racine unique « projects_root »."""
    storage = cfg.get("storage")
    if not isinstance(storage, dict):
        storage = cfg["storage"] = {}
    changed = False
    if "instances_root" in storage or "intents_root" in storage:
        instances_root = storage.pop("instances_root", None)
        intents_root = storage.pop("intents_root", None)
        if not storage.get("projects_root"):
            storage["projects_root"] = instances_root or intents_root or None
        changed = True
    if "projects_root" not in storage:
        storage["projects_root"] = None
        changed = True
    return changed


# ──────────────────────────────────────────────

def _migrate_config(cfg: dict) -> tuple:
    changed = False

    if "_schema_version" not in cfg or cfg["_schema_version"] < 2:
        cfg.setdefault("storage", {"projects_root": None})
        cfg["_schema_version"] = 2
        changed = True

    if cfg.get("_schema_version", 0) < 3:
        cfg.setdefault("github_account", {
            "login": None, "name": None, "avatar_url": None,
            "token_encrypted": None, "token_protected": False,
        })
        cfg["_schema_version"] = 3
        changed = True

    # Schémas 4 à 8 : les champs des entrées sont désormais garantis par
    # normalize_entry() (appelé plus bas), on ne conserve que les étapes qui
    # touchent le reste de la configuration.
    if cfg.get("_schema_version", 0) < 4:
        cfg["_schema_version"] = 4

    if cfg.get("_schema_version", 0) < 5:
        cfg["_schema_version"] = 5
        changed = True

    if cfg.get("_schema_version", 0) < 6:
        app_cfg = cfg.setdefault("app_config", {})
        for key, val in [("auto_save", False), ("auto_save_notes", False),
                          ("note_auto_save_interval", 30)]:
            if key not in app_cfg:
                app_cfg[key] = val
                changed = True
        cfg["_schema_version"] = 6

    if cfg.get("_schema_version", 0) < 7:
        # v1.0.1 : support GitHub App
        app_cfg = cfg.setdefault("app_config", {})
        if "auth_method" not in app_cfg:
            # Le compte reste en OAuth par défaut à cette étape du schéma —
            # l'utilisateur est invité à migrer vers GitHub App via l'UI s'il
            # le souhaite.
            app_cfg["auth_method"] = constants.AUTH_METHOD_OAUTH
            changed = True
        gh_acct = cfg.setdefault("github_account", {})
        for key, val in [
            ("github_app_id", ""),
            ("github_app_private_key", ""),
            ("github_app_installation_id", ""),
            ("github_app_token_cache", ""),
            ("github_app_token_expires_at", 0.0),
        ]:
            if key not in gh_acct:
                gh_acct[key] = val
                changed = True
        cfg["_schema_version"] = 7

    if cfg.get("_schema_version", 0) < 8:
        # v1.0.1 : vault support
        cfg.setdefault("vault", {})
        cfg["_schema_version"] = 8

    if cfg.get("_schema_version", 0) < 9:
        # v1.0.3 : instances + intents → projets, racines de stockage unifiées
        cfg["_schema_version"] = 9
        changed = True

    # Ces deux fusions sont idempotentes et volontairement HORS du bloc de
    # version : elles rattrapent aussi une config déjà en schéma 9 dans
    # laquelle un import (Meridian, mpack, ancien fichier) a réintroduit des
    # clés « instances » / « intents ».
    if _fold_legacy_kinds(cfg):
        changed = True
    if _migrate_storage(cfg):
        changed = True

    # Garanties clés obligatoires
    cfg.setdefault("projects", [])
    cfg.setdefault("github_account", {
        "login": None, "name": None, "avatar_url": None,
        "token_encrypted": None, "token_protected": False,
    })
    cfg.setdefault("custom_statuses", {})
    cfg.setdefault("app_config", {
        "theme": "default",
        "auto_encrypt": False,
        "auto_save": False,
        "auto_save_notes": False,
        "note_auto_save_interval": 30,
        "window_geometry": None,
        "splitter_states": {},
        # v1.0.1 : nouveaux champs
        "hide_github_not_connected": False,
        "quick_apps": [],          # [{"name": "VS Code", "cmd": "code", "icon": "💙"}, ...]
        "cache_mode": "memory",    # "memory" ou "disk"
        "cache_size_limit_mb": 256,
    })

    # Garantir les nouveaux champs dans app_config
    app_cfg = cfg["app_config"]
    for key, val in [
        ("hide_github_not_connected", False), ("quick_apps", []),
        ("cache_mode", "memory"), ("cache_size_limit_mb", 256),
        ("auth_method", constants.AUTH_METHOD_OAUTH), ("github_client_id", ""),
    ]:
        if key not in app_cfg:
            app_cfg[key] = val
            changed = True

    # Entrées de projets : champs par défaut + noms de catégories utilisés
    used_categories: list[str] = []
    for entry in cfg["projects"]:
        if normalize_entry(entry):
            changed = True
        if isinstance(entry.get("category"), str) and entry["category"].strip():
            used_categories.append(entry["category"].strip())

    categories = normalize_categories(cfg.get("categories", []), used_categories)
    if categories != cfg.get("categories"):
        cfg["categories"] = categories
        changed = True

    return cfg, changed


def _get_default_config() -> dict:
    return {
        "_schema_version": constants.CONFIG_SCHEMA_VERSION,
        "projects": [],
        "storage": {"projects_root": None},
        "github_account": {
            "login": None, "name": None, "avatar_url": None,
            "token_encrypted": None, "token_protected": False,
        },
        "categories": [],
        "custom_statuses": {},
        "app_config": {
            "theme": "default",
            "auto_encrypt": False,
            "auto_save": False,
            "auto_save_notes": False,
            "note_auto_save_interval": 30,
            "window_geometry": None,
            "splitter_states": {},
            "hide_github_not_connected": False,
            "quick_apps": [],
            "cache_mode": "memory",
            "cache_size_limit_mb": 256,
            "auth_method": constants.AUTH_METHOD_OAUTH,
            "github_client_id": "",
        },
        "vault": {},
    }


def _safe_winerror(exc: OSError) -> int | None:
    """Retourne winerror si disponible (Windows), None sinon."""
    return getattr(exc, 'winerror', None)


def _load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    paths.ensure_app_dirs()
    cfg_path = paths.get_config_path()

    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            if _safe_winerror(exc) == 2:
                cfg = _get_default_config()
            else:
                raise constants.ConfigCorruptedError(f"config.json illisible : {exc}") from exc
        if not isinstance(cfg, dict):
            raise constants.ConfigCorruptedError("config.json illisible : la racine n'est pas un objet JSON.")
    else:
        cfg = _get_default_config()

    # Sauvegarde de sécurité AVANT la première migration vers les projets :
    # la fusion instances/intents est à sens unique.
    raw_version = cfg.get("_schema_version", 0)
    if cfg_path.exists() and isinstance(raw_version, int) and raw_version < 9:
        _backup_before_projects_migration(cfg_path)

    legacy_files, legacy_log = _absorb_legacy_files(cfg_path.parent, cfg)

    cfg, changed = _migrate_config(cfg)
    if changed or legacy_files:
        try:
            _save_config(cfg)
        except OSError:
            # Sauvegarde impossible : on garde les anciens fichiers intacts,
            # ils seront réabsorbés au prochain lancement.
            legacy_files, legacy_log = [], []
    _retire_legacy_files(cfg_path.parent, legacy_files, legacy_log)

    _config_cache = cfg
    return cfg


def _backup_before_projects_migration(cfg_path: Path) -> None:
    """Copie config.json vers config.pre-v9.json (une seule fois)."""
    backup = cfg_path.with_name("config.pre-v9.json")
    if backup.exists():
        return
    try:
        shutil.copy2(cfg_path, backup)
    except OSError:
        pass  # sauvegarde best-effort : ne doit jamais empêcher le démarrage


# Anciens fichiers de configuration (avant config.json unique). Un fichier
# n'est absorbé que s'il ressemble vraiment à une config Voktora : les noms
# « settings.json » / « projects.json » sont génériques et peuvent appartenir
# à un tout autre programme dans le dossier parent.
_LEGACY_FILENAMES = ("voktora_config.json", "instances.json",
                     "intents.json", "projects.json", "settings.json")
_LEGACY_KEYS = ("instances", "intents", "projects", "storage", "github_account")


def _absorb_legacy_files(data_dir: Path, cfg: dict) -> tuple[list[Path], list[str]]:
    """Fusionne dans `cfg` les anciens fichiers de config reconnus.

    Ne supprime rien : retourne (fichiers absorbés, lignes de journal). La
    suppression n'a lieu qu'après écriture réussie de config.json (voir
    _retire_legacy_files), pour ne jamais perdre de données.
    """
    absorbed: list[Path] = []
    log: list[str] = []
    seen: set[Path] = set()
    for search_dir in (data_dir.parent, data_dir):
        if not search_dir.exists():
            continue
        for filename in _LEGACY_FILENAMES:
            legacy_file = search_dir / filename
            if legacy_file in seen or legacy_file == paths.get_config_path() or not legacy_file.is_file():
                continue
            seen.add(legacy_file)
            try:
                with open(legacy_file, encoding="utf-8") as f:
                    legacy = json.load(f)
            except (OSError, ValueError):
                continue  # illisible : pas à nous de le traiter
            if not isinstance(legacy, dict) or not any(key in legacy for key in _LEGACY_KEYS):
                continue
            try:
                _merge_legacy_config(cfg, legacy)
            except Exception as exc:
                log.append(f"❌ {legacy_file.name} → erreur: {exc}")
                continue
            absorbed.append(legacy_file)
            log.append(f"✅ {legacy_file.name} → config.json")
    return absorbed, log


def _merge_legacy_config(cfg: dict, legacy: dict) -> None:
    """Ajoute à `cfg` les projets et réglages d'un ancien fichier (sans doublon de chemin)."""
    known = {e.get("path") for key in ("instances", "intents", "projects") for e in cfg.get(key, [])
             if isinstance(e, dict)}
    for key in ("instances", "intents", "projects"):
        for entry in legacy.get(key) or []:
            if isinstance(entry, dict) and entry.get("path") and entry["path"] not in known:
                known.add(entry["path"])
                cfg.setdefault(key, []).append(entry)

    legacy_storage = legacy.get("storage")
    if isinstance(legacy_storage, dict):
        storage = cfg.setdefault("storage", {})
        current = storage.get("projects_root") or storage.get("instances_root")
        if not current:
            storage.update(legacy_storage)

    legacy_account = legacy.get("github_account")
    if (isinstance(legacy_account, dict) and legacy_account.get("login")
            and not (cfg.get("github_account") or {}).get("login")):
        cfg["github_account"] = legacy_account


def _retire_legacy_files(data_dir: Path, files: list[Path], log: list[str]) -> None:
    """Sauvegarde puis supprime les anciens fichiers absorbés, et écrit le journal."""
    for legacy_file in files:
        try:
            shutil.copy2(legacy_file, legacy_file.with_suffix(".json.legacy"))
            legacy_file.unlink()
        except OSError as exc:
            log.append(f"❌ {legacy_file.name} → suppression impossible: {exc}")
    if not log:
        return
    try:
        with open(data_dir / "migration.log", "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"\n=== Migration du {timestamp} ===\n")
            for line in log:
                f.write(f"{line}\n")
    except OSError:
        pass


def show_migration_summary() -> list:
    data_dir = paths.get_data_dir()
    log_file = data_dir / "migration.log"
    if not log_file.exists():
        return []
    try:
        with open(log_file, encoding="utf-8") as f:
            content = f.read()
        sessions = content.split("=== Migration du ")
        if len(sessions) <= 1:
            return []
        last_session = sessions[-1]
        lines = last_session.split('\n')
        return [ln.strip() for ln in lines if ln.strip() and (ln.strip().startswith('✅') or ln.strip().startswith('❌'))]
    except Exception:
        return []


def clear_migration_log() -> None:
    try:
        log_file = paths.get_data_dir() / "migration.log"
        if log_file.exists():
            log_file.unlink()
    except Exception:
        pass


def _save_config(cfg: dict) -> None:
    global _config_cache
    cfg_path = paths.get_config_path()
    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        if _safe_winerror(e) == 2:
            return
        raise

    tmp_path = cfg_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        if os.name == "posix":
            # config.json peut contenir des tokens : lisible par le seul propriétaire.
            os.chmod(tmp_path, 0o600)
        tmp_path.replace(cfg_path)
    except OSError as e:
        tmp_path.unlink(missing_ok=True)
        if _safe_winerror(e) == 2:
            return
        raise
    _config_cache = cfg


def _find_entry(cfg: dict, path: Path | str) -> dict | None:
    """Retrouve l'entrée d'un projet par son chemin."""
    target = str(path)
    for entry in cfg.get("projects", []):
        if entry["path"] == target:
            return entry
    return None


def _update_entry(cfg: dict, path: Path | str, **fields) -> bool:
    entry = _find_entry(cfg, path)
    if entry is None:
        return False
    entry.update(fields)
    return True


# ──────────────────────────────────────────────
# STOCKAGE PERSONNALISÉ
# ──────────────────────────────────────────────

def extract_external_projects(data: dict) -> list[dict]:
    """Projets d'une config externe (Meridian, ancienne ou récente Voktora), tous formats confondus."""
    staging = {key: list(data.get(key) or []) for key in ("projects", "instances", "intents")
               if isinstance(data.get(key), list)}
    _fold_legacy_kinds(staging)
    return [e for e in staging.get("projects", []) if isinstance(e, dict) and e.get("path")]


def merge_external_config(data: dict) -> dict[str, int]:
    """Fusionne une config externe dans la config courante, sans rien écraser.

    Les projets déjà connus (même chemin) sont ignorés, les catégories sont
    réunies (sans tenir compte de la casse), les statuts personnalisés et la
    racine de stockage ne sont repris que s'ils n'existent pas déjà.
    Retourne {"projects": n, "categories": n, "statuses": n} (éléments ajoutés).
    """
    import copy

    cfg = _load_config()
    known = {e["path"] for e in cfg["projects"]}
    added_projects = 0
    incoming = copy.deepcopy(extract_external_projects(data))
    for entry in incoming:
        if entry["path"] in known:
            continue
        entry.setdefault("name", _path_basename(entry["path"]))
        normalize_entry(entry)
        cfg["projects"].append(entry)
        known.add(entry["path"])
        added_projects += 1

    before = {c["name"].lower() for c in cfg["categories"]}
    used = [e["category"] for e in cfg["projects"] if e.get("category")]
    merged = normalize_categories(cfg["categories"] + normalize_categories(data.get("categories") or []), used)
    added_categories = sum(1 for c in merged if c["name"].lower() not in before)
    cfg["categories"] = merged

    added_statuses = 0
    incoming_statuses = data.get("custom_statuses")
    if isinstance(incoming_statuses, dict):
        current = cfg.setdefault("custom_statuses", {})
        for key, value in incoming_statuses.items():
            if key not in current:
                current[key] = value
                added_statuses += 1

    storage = data.get("storage")
    if isinstance(storage, dict) and not cfg["storage"].get("projects_root"):
        cfg["storage"]["projects_root"] = (
            storage.get("projects_root") or storage.get("instances_root") or storage.get("intents_root") or None)

    _save_config(cfg)
    return {"projects": added_projects, "categories": added_categories, "statuses": added_statuses}


def get_app_config() -> dict:
    return _load_config().get("app_config", {})


def set_app_config(config: dict) -> None:
    cfg = _load_config()
    cfg["app_config"] = config
    _save_config(cfg)


def get_storage_config() -> dict:
    return _load_config().get("storage", {"projects_root": None})


def set_storage_config(projects_root) -> None:
    cfg = _load_config()
    cfg["storage"] = {"projects_root": str(projects_root) if projects_root else None}
    _save_config(cfg)


def get_cache_config() -> dict:
    """Retourne la config du cache (mode + limite de taille)."""
    app_cfg = get_app_config()
    return {
        "mode":         app_cfg.get("cache_mode", "memory"),
        "size_limit_mb": app_cfg.get("cache_size_limit_mb", 256),
    }


def set_cache_config(mode: str, size_limit_mb: int) -> None:
    """Sauvegarde la config du cache."""
    cfg = _load_config()
    cfg["app_config"]["cache_mode"] = mode
    cfg["app_config"]["cache_size_limit_mb"] = size_limit_mb
    _save_config(cfg)


def get_ollama_config() -> dict:
    """Retourne la config Ollama (hôte + modèle par défaut)."""
    app_cfg = get_app_config()
    return {
        "host":  app_cfg.get("ollama_host", "http://localhost:11434"),
        "model": app_cfg.get("ollama_model", ""),
    }


def set_ollama_config(host: str, model: str) -> None:
    """Sauvegarde la config Ollama (hôte + modèle par défaut)."""
    cfg = _load_config()
    cfg["app_config"]["ollama_host"] = host
    cfg["app_config"]["ollama_model"] = model
    _save_config(cfg)


def get_quick_apps() -> list:
    """Retourne la liste des apps de la barre rapide."""
    return get_app_config().get("quick_apps", [])


def set_quick_apps(apps: list) -> None:
    """Sauvegarde la liste des apps de la barre rapide."""
    cfg = _load_config()
    cfg["app_config"]["quick_apps"] = apps
    _save_config(cfg)


def get_project_language(path: Path) -> str:
    cfg = _load_config()
    entry = _find_entry(cfg, path)
    return (entry.get("language") if entry else None) or ""


def set_project_language(path: Path, language: str) -> None:
    cfg = _load_config()
    _update_entry(cfg, path, language=language or None)
    _save_config(cfg)


# Dossiers ignorés lors de la détection du langage : dépendances et artefacts
# de build, qui fausseraient le décompte et ralentiraient énormément le scan.
_LANG_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    "target", "build", "dist", ".idea", ".vscode", ".tox", ".mypy_cache",
})
_LANG_MAX_FILES = 20_000  # plafond de fichiers examinés (gros monorepos)


def guess_project_language(path: Path) -> str:
    if not path.exists() or not path.is_dir():
        return "Inconnu"
    ext_map = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".cs": "C#", ".java": "Java", ".go": "Go", ".php": "PHP",
        ".rb": "Ruby", ".sh": "Shell", ".ps1": "PowerShell", ".rs": "Rust",
        ".dart": "Dart", ".kt": "Kotlin", ".swift": "Swift",
        ".cpp": "C++", ".c": "C", ".html": "HTML", ".css": "CSS", ".json": "JSON",
    }
    counts: dict = {}
    scanned = 0
    for _root, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in _LANG_SKIP_DIRS]
        for filename in filenames:
            lang = ext_map.get(os.path.splitext(filename)[1].lower())
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
        scanned += len(filenames)
        if scanned >= _LANG_MAX_FILES:
            break
    if not counts:
        return "Indéfini"
    return max(counts.items(), key=lambda pair: pair[1])[0]
