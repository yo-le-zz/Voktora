"""
Voktora — Project Instance Manager
Voktora v1.0.1
core.py : Logique métier — config, instances, intents, Git, chiffrement AES-256 (Fernet+PBKDF2), auth GitHub
Version : 1.0.1  —  Windows + Linux compatible
"""

import os
import re
import sys
import json
import shutil
import string
import zipfile
import hashlib
import base64
import secrets
import subprocess
import functools
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Callable
from dataclasses import dataclass, field

# ──────────────────────────────────────────────
# CONSTANTES
# ──────────────────────────────────────────────

APP_NAME              = "Voktora"
APP_VERSION           = "1.0.1"
CONTAINER_NAME        = "Voktora"
INSTANCES_DIR         = "Instances"
INTENTS_DIR           = "Intents"
PROJECT_BUILDER       = r"D:\my programme\Project_builder\ProjectsBuilder.exe"

PBKDF2_ITERATIONS     = 480_000   # NIST recommandation 2023
SALT_BYTES            = 32
AES_KEY_BYTES         = 32        # AES-256

CONFIG_FILENAME       = "config.json"
BACKUPS_DIRNAME       = "backups"

MAX_NAME_LENGTH       = 128
_NAME_FORBIDDEN_RE    = re.compile(r'[\\/:*?"<>|\x00-\x1f]|^\.|\.{2,}')

CONFIG_SCHEMA_VERSION = 6

# ── Compatibilité Windows / Linux ──
IS_WINDOWS = sys.platform == "win32"
IS_LINUX   = sys.platform.startswith("linux")

# Flag Windows pour éviter l'ouverture de fenêtre console lors des subprocess
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0


# ──────────────────────────────────────────────
# STATUTS DE PROJETS
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class ProjectStatus:
    id: str
    name: str
    color: str
    emoji: str

PROJECT_STATUSES = {
    "finished":    ProjectStatus("finished",    "Fini",               "#4CAF50", "✅"),
    "improve":     ProjectStatus("improve",     "À améliorer",        "#FF9800", "🔧"),
    "started":     ProjectStatus("started",     "Commencé récemment", "#03A9F4", "🆕"),
    "progress":    ProjectStatus("progress",    "En cours",           "#2196F3", "🔄"),
    "abandoned":   ProjectStatus("abandoned",   "Abandonné",          "#F44336", "❌"),
}

DEFAULT_PROJECT_STATUS = "started"

def get_all_project_statuses() -> dict:
    cfg = _load_config()
    all_statuses = dict(PROJECT_STATUSES)
    custom_statuses = cfg.get("custom_statuses", {})
    for status_id, status_data in custom_statuses.items():
        all_statuses[status_id] = ProjectStatus(
            id=status_id,
            name=status_data["name"],
            color=status_data["color"],
            emoji=status_data["emoji"]
        )
    return all_statuses

def get_project_status_by_id(status_id: str):
    return get_all_project_statuses().get(status_id)


# ──────────────────────────────────────────────
# AUTH GITHUB — OAuth App (Device Flow) + GitHub App
# ──────────────────────────────────────────────

# OAuth App (Device Flow) — rétrocompat
GITHUB_CLIENT_ID       = ""
GITHUB_DEVICE_AUTH_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL       = "https://github.com/login/oauth/access_token"
GITHUB_API_USER_URL    = "https://api.github.com/user"
GITHUB_SCOPES          = "repo"

# GitHub App — endpoints
GITHUB_APP_TOKEN_URL   = "https://api.github.com/app/installations/{installation_id}/access_tokens"
GITHUB_APP_INSTALL_URL = "https://api.github.com/app/installations"
GITHUB_API_BASE        = "https://api.github.com"

# auth_method : "oauth" | "github_app"
AUTH_METHOD_OAUTH      = "oauth"
AUTH_METHOD_GITHUB_APP = "github_app"

_SESSION_VAULT:   dict = {}
_GITHUB_SESSION:  dict | None = None
_config_cache:    dict | None = None


# ──────────────────────────────────────────────
# CHEMIN DE L'APPLICATION (Nuitka + dev)
# ──────────────────────────────────────────────

@functools.cache
def get_app_dir() -> Path:
    try:
        _ = __compiled__
        return Path(sys.executable).parent
    except NameError:
        return Path(__file__).resolve().parent.parent


@functools.cache
def get_data_dir() -> Path:
    # Sur Linux, si l'app est installée dans /opt ou /usr (non accessible en écriture),
    # on utilise le répertoire XDG standard : ~/.local/share/voktora/
    if IS_LINUX:
        app_dir = get_app_dir()
        # Installé système (/opt/*, /usr/*)  → données dans ~/.local/share/voktora
        if str(app_dir).startswith("/opt/") or str(app_dir).startswith("/usr/"):
            xdg_data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            d = xdg_data / "voktora"
            d.mkdir(parents=True, exist_ok=True)
            return d

    # Windows ou Linux dev (dossier local) → data/ à côté de l'exe
    d = get_app_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@functools.cache
def get_backups_dir() -> Path:
    b = get_data_dir() / BACKUPS_DIRNAME
    b.mkdir(parents=True, exist_ok=True)
    return b


@functools.cache
def get_config_path() -> Path:
    return get_data_dir() / CONFIG_FILENAME


def ensure_app_dirs() -> None:
    """Crée tous les dossiers nécessaires au démarrage (Windows + Linux)."""
    dirs = [get_data_dir(), get_backups_dir()]
    # Les thèmes sont dans le dossier de l'app (lecture seule sur Linux installé)
    # On ne tente pas de les créer si c'est /opt/
    themes_dir = get_app_dir() / "themes"
    if not (IS_LINUX and (str(get_app_dir()).startswith("/opt/") or
                          str(get_app_dir()).startswith("/usr/"))):
        dirs.append(themes_dir)
    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


# ──────────────────────────────────────────────
# VALIDATION DES NOMS
# ──────────────────────────────────────────────

def validate_name(name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Le nom ne peut pas être vide.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"Le nom est trop long ({len(name)} caractères, maximum {MAX_NAME_LENGTH}).")
    if _NAME_FORBIDDEN_RE.search(name):
        raise ValueError(f"Le nom « {name} » contient des caractères non autorisés.")


# ──────────────────────────────────────────────
# CONFIG GLOBALE
# ──────────────────────────────────────────────

def _migrate_config(cfg: dict) -> tuple:
    changed = False

    if "_schema_version" not in cfg or cfg["_schema_version"] < 2:
        cfg.setdefault("storage", {"instances_root": None, "intents_root": None})
        cfg["_schema_version"] = 2
        changed = True

    if cfg.get("_schema_version", 0) < 3:
        cfg.setdefault("github_account", {
            "login": None, "name": None, "avatar_url": None,
            "token_encrypted": None, "token_protected": False,
        })
        cfg["_schema_version"] = 3
        changed = True

    if cfg.get("_schema_version", 0) < 4:
        for entry in cfg.get("instances", []):
            for field_name, default in [("status", DEFAULT_PROJECT_STATUS), ("color", None),
                                         ("emoji", None), ("category", None), ("language", None)]:
                if field_name not in entry:
                    entry[field_name] = default
                    changed = True
        for entry in cfg.get("intents", []):
            for field_name, default in [("color", None), ("emoji", None),
                                         ("category", None), ("language", None)]:
                if field_name not in entry:
                    entry[field_name] = default
                    changed = True
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
            # Si un client_id OAuth est déjà configuré → on reste en oauth
            # L'utilisateur sera invité à migrer via l'UI
            existing_client_id = app_cfg.get("github_client_id", "")
            app_cfg["auth_method"] = AUTH_METHOD_OAUTH if existing_client_id else AUTH_METHOD_OAUTH
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

    # Garanties clés obligatoires
    cfg.setdefault("instances", [])
    cfg.setdefault("intents", [])
    cfg.setdefault("storage", {"instances_root": None, "intents_root": None})
    cfg.setdefault("github_account", {
        "login": None, "name": None, "avatar_url": None,
        "token_encrypted": None, "token_protected": False,
    })
    cfg.setdefault("categories", [])
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
        ("auth_method", AUTH_METHOD_OAUTH), ("github_client_id", ""),
    ]:
        if key not in app_cfg:
            app_cfg[key] = val
            changed = True

    # Migration entrées instances
    for entry in cfg["instances"]:
        for field_name, default in [
            ("github_branches", [entry.get("github_branch") or "main"]),
            ("github_token_protected", False), ("note", ""),
            ("status", DEFAULT_PROJECT_STATUS), ("color", None),
            ("emoji", None), ("category", None), ("language", None),
        ]:
            if field_name not in entry:
                entry[field_name] = default
                changed = True

    for entry in cfg["intents"]:
        for field_name, default in [
            ("note", ""), ("color", None), ("emoji", None),
            ("category", None), ("language", None),
        ]:
            if field_name not in entry:
                entry[field_name] = default
                changed = True

    return cfg, changed


def _get_default_config() -> dict:
    return {
        "_schema_version": CONFIG_SCHEMA_VERSION,
        "instances": [],
        "intents": [],
        "storage": {"instances_root": None, "intents_root": None},
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
            "auth_method": AUTH_METHOD_OAUTH,
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

    ensure_app_dirs()
    cfg_path = get_config_path()

    _migrate_legacy_configs(cfg_path.parent)

    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            if _safe_winerror(exc) == 2:
                cfg = _get_default_config()
            else:
                raise ConfigCorruptedError(f"config.json illisible : {exc}")
    else:
        cfg = _get_default_config()

    cfg, changed = _migrate_config(cfg)
    if changed:
        try:
            _save_config(cfg)
        except OSError:
            pass

    _config_cache = cfg
    return cfg


def _migrate_legacy_configs(data_dir: Path) -> None:
    migrations_made = []
    legacy_patterns = ["voktora_config.json", "instances.json",
                       "intents.json", "projects.json", "settings.json"]
    search_dirs = [data_dir.parent, data_dir]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for pattern in legacy_patterns:
            legacy_file = search_dir / pattern
            if legacy_file == get_config_path():
                continue
            if legacy_file.exists():
                try:
                    with open(legacy_file, encoding="utf-8") as f:
                        legacy_cfg = json.load(f)
                    _merge_legacy_config(legacy_cfg, legacy_file.name, migrations_made)
                    backup_path = legacy_file.with_suffix(".json.legacy")
                    shutil.copy2(legacy_file, backup_path)
                    legacy_file.unlink()
                    migrations_made.append(f"✅ {legacy_file.name} → config.json")
                except Exception as e:
                    migrations_made.append(f"❌ {legacy_file.name} → erreur: {e}")

    if migrations_made:
        try:
            log_file = data_dir / "migration.log"
            with open(log_file, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"\n=== Migration du {timestamp} ===\n")
                for line in migrations_made:
                    f.write(f"{line}\n")
        except Exception:
            pass


def show_migration_summary() -> list:
    data_dir = get_data_dir()
    log_file = data_dir / "migration.log"
    if not log_file.exists():
        return []
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        sessions = content.split("=== Migration du ")
        if len(sessions) <= 1:
            return []
        last_session = sessions[-1]
        lines = last_session.split('\n')
        return [l.strip() for l in lines if l.strip() and (l.strip().startswith('✅') or l.strip().startswith('❌'))]
    except Exception:
        return []


def clear_migration_log() -> None:
    try:
        log_file = get_data_dir() / "migration.log"
        if log_file.exists():
            log_file.unlink()
    except Exception:
        pass


def _merge_legacy_config(legacy_cfg: dict, filename: str, migrations_made: list) -> None:
    try:
        current_cfg = _load_config() if get_config_path().exists() else _get_default_config()
        if filename == "instances.json":
            if "instances" in legacy_cfg:
                current_cfg["instances"].extend(legacy_cfg["instances"])
        elif filename == "intents.json":
            if "intents" in legacy_cfg:
                current_cfg["intents"].extend(legacy_cfg["intents"])
        elif filename in ["voktora_config.json", "projects.json", "settings.json"]:
            for key in ["instances", "intents", "storage", "github_account"]:
                if key in legacy_cfg:
                    if key in ["instances", "intents"]:
                        existing_paths = {item["path"] for item in current_cfg.get(key, [])}
                        for item in legacy_cfg[key]:
                            if item.get("path") not in existing_paths:
                                current_cfg.setdefault(key, []).append(item)
                    else:
                        current_cfg[key] = legacy_cfg[key]
        _save_config(current_cfg)
    except Exception as e:
        migrations_made.append(f"❌ Erreur fusion {filename}: {e}")


def _save_config(cfg: dict) -> None:
    global _config_cache
    cfg_path = get_config_path()
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
        tmp_path.replace(cfg_path)
    except OSError as e:
        tmp_path.unlink(missing_ok=True)
        if _safe_winerror(e) == 2:
            return
        raise
    _config_cache = cfg


def _find_entry(cfg: dict, key: str, path: Path) -> dict | None:
    target = str(path)
    for entry in cfg.get(key, []):
        if entry["path"] == target:
            return entry
    return None


def _update_entry(cfg: dict, key: str, path: Path, **fields) -> bool:
    entry = _find_entry(cfg, key, path)
    if entry is None:
        return False
    entry.update(fields)
    return True


# ──────────────────────────────────────────────
# STOCKAGE PERSONNALISÉ
# ──────────────────────────────────────────────

def get_app_config() -> dict:
    return _load_config().get("app_config", {})


def set_app_config(config: dict) -> None:
    cfg = _load_config()
    cfg["app_config"] = config
    _save_config(cfg)


def get_storage_config() -> dict:
    return _load_config().get("storage", {"instances_root": None, "intents_root": None})


def set_storage_config(instances_root, intents_root) -> None:
    cfg = _load_config()
    cfg["storage"] = {
        "instances_root": str(instances_root) if instances_root else None,
        "intents_root":   str(intents_root)   if intents_root   else None,
    }
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


def get_quick_apps() -> list:
    """Retourne la liste des apps de la barre rapide."""
    return get_app_config().get("quick_apps", [])


def set_quick_apps(apps: list) -> None:
    """Sauvegarde la liste des apps de la barre rapide."""
    cfg = _load_config()
    cfg["app_config"]["quick_apps"] = apps
    _save_config(cfg)


def get_instance_language(path: Path) -> str:
    cfg = _load_config()
    entry = _find_entry(cfg, "instances", path)
    return (entry.get("language") if entry else None) or ""


def set_instance_language(path: Path, language: str) -> None:
    cfg = _load_config()
    _update_entry(cfg, "instances", path, language=language or None)
    _save_config(cfg)


def get_intent_language(path: Path) -> str:
    cfg = _load_config()
    entry = _find_entry(cfg, "intents", path)
    return (entry.get("language") if entry else None) or ""


def set_intent_language(path: Path, language: str) -> None:
    cfg = _load_config()
    _update_entry(cfg, "intents", path, language=language or None)
    _save_config(cfg)


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
    for entry in path.rglob("*"):
        if entry.is_file():
            lang = ext_map.get(entry.suffix.lower())
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return "Indéfini"
    return max(counts.items(), key=lambda pair: pair[1])[0]


# ──────────────────────────────────────────────
# DISQUES — Windows + Linux
# ──────────────────────────────────────────────

def get_available_drives() -> list:
    """
    Retourne les emplacements de stockage disponibles.
    Windows : lettres de lecteurs amovibles/secondaires.
    Linux   : répertoires courants (/home/user, /media/..., etc.).
    """
    if IS_WINDOWS:
        system_drive = os.environ.get("SystemDrive", "C:").upper().rstrip("\\")
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
# CHEMINS CONTENEURS
# ──────────────────────────────────────────────

def get_instances_root(drive: str = "") -> Path:
    custom = get_storage_config().get("instances_root")
    if custom:
        return Path(custom)
    if IS_WINDOWS:
        return Path(f"{drive}\\{CONTAINER_NAME}\\{INSTANCES_DIR}")
    else:
        base = Path(drive) if drive and Path(drive).is_absolute() else Path.home()
        return base / CONTAINER_NAME / INSTANCES_DIR


def get_intents_root(drive: str = "") -> Path:
    custom = get_storage_config().get("intents_root")
    if custom:
        return Path(custom)
    if IS_WINDOWS:
        return Path(f"{drive}\\{CONTAINER_NAME}\\{INTENTS_DIR}")
    else:
        base = Path(drive) if drive and Path(drive).is_absolute() else Path.home()
        return base / CONTAINER_NAME / INTENTS_DIR


# ──────────────────────────────────────────────
# OAUTH GITHUB — Device Flow
# ──────────────────────────────────────────────

@dataclass
class DeviceFlowPending:
    device_code:      str
    user_code:        str
    verification_uri: str
    expires_in:       int
    interval:         int


def get_github_client_id() -> str:
    cfg = _load_config()
    return cfg.get("app_config", {}).get("github_client_id", "") or GITHUB_CLIENT_ID


def set_github_client_id(client_id: str) -> None:
    cfg = _load_config()
    cfg.setdefault("app_config", {})["github_client_id"] = client_id
    _save_config(cfg)


def is_github_client_id_configured() -> bool:
    return bool(get_github_client_id())


# ──────────────────────────────────────────────────────────────────────────────
# AUTH METHOD
# ──────────────────────────────────────────────────────────────────────────────

def get_auth_method() -> str:
    """Retourne 'oauth' ou 'github_app'."""
    return _load_config().get("app_config", {}).get("auth_method", AUTH_METHOD_OAUTH)


def set_auth_method(method: str) -> None:
    cfg = _load_config()
    cfg.setdefault("app_config", {})["auth_method"] = method
    _save_config(cfg)


def is_using_github_app() -> bool:
    return get_auth_method() == AUTH_METHOD_GITHUB_APP


# ──────────────────────────────────────────────────────────────────────────────
# GITHUB APP — Configuration
# ──────────────────────────────────────────────────────────────────────────────

def get_github_app_config() -> dict:
    """
    Retourne {app_id, private_key, installation_id} depuis la config chiffrée.
    private_key peut être chiffré (token_encrypt) si token_protected=True.
    """
    cfg = _load_config()
    acct = cfg.get("github_account", {})
    return {
        "app_id":          acct.get("github_app_id", ""),
        "private_key":     acct.get("github_app_private_key", ""),
        "installation_id": acct.get("github_app_installation_id", ""),
    }


def set_github_app_config(app_id: str, private_key_pem: str,
                           installation_id: str, password: str = "") -> None:
    """
    Sauvegarde la config GitHub App.
    La clé privée est optionnellement chiffrée avec token_encrypt.
    """
    cfg = _load_config()
    acct = cfg.setdefault("github_account", {})

    if password:
        stored_key = token_encrypt(private_key_pem, password)
        acct["token_protected"] = True
    else:
        stored_key = private_key_pem
        acct["token_protected"] = False

    acct["github_app_id"]              = app_id
    acct["github_app_private_key"]     = stored_key
    acct["github_app_installation_id"] = installation_id
    # Invalider le cache de token
    acct["github_app_token_cache"]      = ""
    acct["github_app_token_expires_at"] = 0.0
    # Méthode d'auth
    cfg.setdefault("app_config", {})["auth_method"] = AUTH_METHOD_GITHUB_APP
    _save_config(cfg)


def clear_github_app_config() -> None:
    cfg = _load_config()
    acct = cfg.setdefault("github_account", {})
    for key in ("github_app_id", "github_app_private_key",
                "github_app_installation_id", "github_app_token_cache",
                "github_app_token_expires_at"):
        acct[key] = "" if isinstance(acct.get(key), str) else 0.0
    cfg.setdefault("app_config", {})["auth_method"] = AUTH_METHOD_OAUTH
    _save_config(cfg)


def get_github_app_installation_id() -> str:
    return _load_config().get("github_account", {}).get("github_app_installation_id", "")


def is_github_app_configured() -> bool:
    cfg = get_github_app_config()
    return bool(cfg["app_id"] and cfg["private_key"] and cfg["installation_id"])


# ──────────────────────────────────────────────────────────────────────────────
# GITHUB APP — JWT + Installation Token
# ──────────────────────────────────────────────────────────────────────────────

def _build_jwt(app_id: str, private_key_pem: str) -> str:
    """
    Génère un JWT signé RS256 valable 10 minutes.
    Utilise uniquement la stdlib + la clé PEM brute (via rsa/cryptography si dispo,
    sinon subprocess openssl comme fallback).
    """
    import base64
    import struct
    import hashlib
    import hmac as _hmac

    now = int(time.time())
    header  = {"alg": "RS256", "typ": "JWT"}
    payload = {"iat": now - 60, "exp": now + 540, "iss": app_id}

    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    msg = f"{h}.{p}".encode()

    # Essayer cryptography d'abord (disponible si PySide6 l'a tiré en dep)
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as _padding
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode(), password=None
        )
        sig = private_key.sign(msg, _padding.PKCS1v15(), hashes.SHA256())
        return f"{h}.{p}.{_b64url(sig)}"
    except ImportError:
        pass

    # Fallback : openssl CLI (présent partout où git est présent)
    import tempfile as _tmp
    with _tmp.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as kf:
        kf.write(private_key_pem)
        kf_path = kf.name
    try:
        import subprocess as _sp
        result = _sp.run(
            ["openssl", "dgst", "-sha256", "-sign", kf_path],
            input=msg, capture_output=True, check=True,
        )
        sig = result.stdout
        return f"{h}.{p}.{_b64url(sig)}"
    finally:
        try:
            Path(kf_path).unlink()
        except Exception:
            pass


def _get_installation_token_cached(app_id: str, private_key_pem: str,
                                    installation_id: str) -> str:
    """
    Retourne un installation token valide (durée max 1h).
    Met en cache dans la config pour éviter de recréer un JWT à chaque appel.
    """
    cfg  = _load_config()
    acct = cfg.setdefault("github_account", {})

    cached     = acct.get("github_app_token_cache", "")
    expires_at = float(acct.get("github_app_token_expires_at", 0))

    # Valide si expire dans plus de 5 min
    if cached and time.time() < expires_at - 300:
        return cached

    # Générer nouveau JWT et demander un installation token
    jwt_token = _build_jwt(app_id, private_key_pem)

    url = GITHUB_APP_TOKEN_URL.format(installation_id=installation_id)
    req = urllib.request.Request(
        url, data=b"{}",
        headers={
            "Authorization":        f"Bearer {jwt_token}",
            "Accept":               "application/vnd.github+json",
            "Content-Type":         "application/json",
            "User-Agent":           f"{APP_NAME}/{APP_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise OAuthError(f"GitHub App token error ({e.code}): {body}") from e
    except Exception as exc:
        raise OAuthError(f"Réseau : {exc}") from exc

    token      = data.get("token", "")
    expires_str = data.get("expires_at", "")  # ISO 8601

    # Parser la date d'expiration
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
        expires_ts = dt.timestamp()
    except Exception:
        expires_ts = time.time() + 3300  # fallback 55 min

    acct["github_app_token_cache"]      = token
    acct["github_app_token_expires_at"] = expires_ts
    _save_config(cfg)

    return token


def get_github_app_token(password: str = "") -> str:
    """
    Retourne un installation token prêt à l'emploi.
    Déchiffre la clé privée si elle est protégée par mot de passe.
    """
    cfg_app = get_github_app_config()
    if not all([cfg_app["app_id"], cfg_app["private_key"], cfg_app["installation_id"]]):
        raise OAuthError("GitHub App non configurée (app_id / clé privée / installation_id manquants).")

    raw_key = cfg_app["private_key"]
    cfg     = _load_config()
    acct    = cfg.get("github_account", {})
    if acct.get("token_protected"):
        if not password:
            raise OAuthError("Ce compte GitHub App est protégé par mot de passe.")
        raw_key = token_decrypt(raw_key, password)
        if not raw_key:
            raise OAuthError("Mot de passe incorrect pour déchiffrer la clé privée.")

    return _get_installation_token_cached(
        cfg_app["app_id"], raw_key, cfg_app["installation_id"]
    )


def fetch_github_app_user(token: str) -> dict:
    """
    Avec un installation token on ne peut pas /user, on utilise /app/installations.
    Retourne un pseudo-profil avec le nom de l'app.
    """
    req = urllib.request.Request(
        GITHUB_API_BASE + "/installation/repositories",
        headers={
            "Authorization":        f"Bearer {token}",
            "Accept":               "application/vnd.github+json",
            "User-Agent":           f"{APP_NAME}/{APP_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        repo_count = data.get("total_count", 0)
        return {
            "login":      "github-app",
            "name":       f"GitHub App ({repo_count} repos)",
            "avatar_url": "",
            "type":       "github_app",
        }
    except Exception:
        return {"login": "github-app", "name": "GitHub App", "avatar_url": "", "type": "github_app"}


def fetch_github_app_installations(app_id: str, private_key_pem: str) -> list[dict]:
    """
    Retourne la liste des installations de la GitHub App (compte perso + orgs).
    Chaque entrée : {"installation_id", "account_login", "account_type", "repos"}.
    Lève OAuthError si l'App ID ou la clé privée sont incorrects.
    """
    jwt_token = _build_jwt(app_id, private_key_pem)
    req = urllib.request.Request(
        GITHUB_APP_INSTALL_URL,
        headers={
            "Authorization":        f"Bearer {jwt_token}",
            "Accept":               "application/vnd.github+json",
            "User-Agent":           f"{APP_NAME}/{APP_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise OAuthError(
            f"Erreur {e.code} lors du fetch des installations.\n"
            f"→ Vérifiez l'App ID et la clé privée.\nDétail: {body}"
        ) from e
    except Exception as exc:
        raise OAuthError(f"Réseau : {exc}") from exc

    result = []
    for inst in (data if isinstance(data, list) else []):
        acct = inst.get("account", {})
        result.append({
            "installation_id": str(inst.get("id", "")),
            "account_login":   acct.get("login", "?"),
            "account_type":    acct.get("type", "?"),
            "repos":           inst.get("repositories_count", "?"),
        })
    return result


# ──────────────────────────────────────────────────────────────────────────────
# EFFECTIVE TOKEN — unifié OAuth + GitHub App
# ──────────────────────────────────────────────────────────────────────────────

def get_effective_token_unified(path: Path | None = None, password: str = "") -> str:
    """
    Retourne le meilleur token disponible selon la méthode d'auth configurée :
      1. Token spécifique à l'instance (priorité max)
      2. GitHub App installation token (si auth_method == github_app)
      3. OAuth token de session
    """
    # 1. Token par instance
    if path:
        tok = get_instance_token(path)
        if tok:
            return tok

    # 2. GitHub App
    if is_using_github_app() and is_github_app_configured():
        try:
            return get_github_app_token(password)
        except OAuthError:
            pass  # fallback OAuth si disponible

    # 3. OAuth session
    session = get_github_session()
    if session and session.get("token"):
        return session["token"]

    return ""


def load_github_app_session() -> bool:
    """
    Charge une session GitHub App depuis la config (si configurée).
    Équivalent de load_github_account_session() pour GitHub App.
    """
    global _GITHUB_SESSION
    if not is_github_app_configured():
        return False
    try:
        token     = get_github_app_token()
        user_info = fetch_github_app_user(token)
        _GITHUB_SESSION = {
            "login":      user_info.get("login", "github-app"),
            "name":       user_info.get("name", "GitHub App"),
            "token":      token,
            "avatar_url": "",
            "auth_type":  AUTH_METHOD_GITHUB_APP,
        }
        return True
    except Exception:
        return False


def start_device_flow() -> DeviceFlowPending:
    client_id = get_github_client_id()
    if not client_id:
        raise OAuthError("Aucun Client ID GitHub configuré.")
    data = urllib.parse.urlencode({"client_id": client_id, "scope": GITHUB_SCOPES}).encode("ascii")
    req = urllib.request.Request(
        GITHUB_DEVICE_AUTH_URL, data=data,
        headers={"Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": f"{APP_NAME}/{APP_VERSION}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise OAuthError(f"Impossible de démarrer l'authentification : {exc}") from exc
    if "error" in body:
        raise OAuthError(f"GitHub a refusé la demande : {body.get('error_description', body['error'])}")
    return DeviceFlowPending(
        device_code=body["device_code"], user_code=body["user_code"],
        verification_uri=body["verification_uri"],
        expires_in=int(body.get("expires_in", 900)), interval=int(body.get("interval", 5)),
    )


def poll_device_flow(pending: DeviceFlowPending, on_success: Callable,
                     on_error: Callable, stop_event=None) -> None:
    deadline = time.monotonic() + pending.expires_in
    interval = pending.interval
    while time.monotonic() < deadline:
        if stop_event and stop_event.is_set():
            on_error("Authentification annulée.")
            return
        time.sleep(interval)
        data = urllib.parse.urlencode({
            "client_id": get_github_client_id(),
            "device_code": pending.device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }).encode("ascii")
        req = urllib.request.Request(
            GITHUB_TOKEN_URL, data=data,
            headers={"Accept": "application/json", "User-Agent": f"{APP_NAME}/{APP_VERSION}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
        error = body.get("error", "")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 5
            continue
        elif error == "expired_token":
            on_error("Le code a expiré.")
            return
        elif error == "access_denied":
            on_error("Accès refusé.")
            return
        elif error:
            on_error(f"Erreur GitHub : {body.get('error_description', error)}")
            return
        elif "access_token" in body:
            on_success(body["access_token"])
            return
    on_error("Délai d'authentification expiré.")


def fetch_github_user(token: str) -> dict:
    req = urllib.request.Request(
        GITHUB_API_USER_URL,
        headers={"Authorization": f"token {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": f"{APP_NAME}/{APP_VERSION}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise OAuthError(f"Erreur GitHub API ({e.code})") from e
    except Exception as exc:
        raise OAuthError(f"Erreur réseau : {exc}") from exc



def verify_github_token(token: str) -> tuple[bool, str]:
    """
    Vérifie qu'un token GitHub est valide en appelant /user.
    Retourne (True, login) ou (False, message_erreur).
    """
    try:
        user = fetch_github_user(token)
        login = user.get("login", "")
        if login:
            return True, login
        return False, "Réponse GitHub invalide"
    except OAuthError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Erreur réseau : {exc}"


def save_github_account(token: str, user_info: dict, password: str = "") -> None:
    global _GITHUB_SESSION
    cfg     = _load_config()
    account = cfg.setdefault("github_account", {})
    account["login"]      = user_info.get("login", "")
    account["name"]       = user_info.get("name", "") or user_info.get("login", "")
    account["avatar_url"] = user_info.get("avatar_url", "")

    if vault_is_unlocked():
        # Vault disponible → AES-256 Fernet, clé dérivée du master password
        vault_store("github_token", token, domain="github_token")
        account["token_encrypted"] = "__vault__"
        account["token_protected"] = False
    elif password:
        # Fallback : chiffrement par mot de passe fourni (AES-256 Fernet)
        account["token_encrypted"] = token_encrypt(token, password)
        account["token_protected"] = True
    else:
        account["token_encrypted"] = token
        account["token_protected"] = False

    _save_config(cfg)
    _GITHUB_SESSION = {
        "login": account["login"], "name": account["name"],
        "token": token, "avatar_url": account.get("avatar_url", ""),
    }


def load_github_account_session(password: str = "") -> bool:
    global _GITHUB_SESSION
    cfg  = _load_config()
    info = cfg.get("github_account", {})
    if not info.get("login"):
        return False
    raw = info.get("token_encrypted", "")

    if raw == "__vault__":
        if not vault_is_unlocked():
            return False
        token = vault_retrieve("github_token")
        if not token:
            return False
    elif info.get("token_protected"):
        if not password:
            return False
        token = token_decrypt(raw, password)
        if not token:
            return False
    else:
        token = raw

    _GITHUB_SESSION = {
        "login": info["login"], "name": info.get("name", info["login"]),
        "token": token, "avatar_url": info.get("avatar_url", ""),
        "auth_type": AUTH_METHOD_OAUTH,
    }
    return True


def get_github_session() -> dict | None:
    return _GITHUB_SESSION


def get_github_account_info() -> dict:
    cfg  = _load_config()
    info = cfg.get("github_account", {})
    return {
        "connected":       bool(info.get("login")),
        "login":           info.get("login", ""),
        "name":            info.get("name", ""),
        "avatar_url":      info.get("avatar_url", ""),
        "token_protected": bool(info.get("token_protected", False)),
    }


def clear_github_account() -> None:
    global _GITHUB_SESSION
    _GITHUB_SESSION = None
    cfg = _load_config()
    cfg["github_account"] = {
        "login": None, "name": None, "avatar_url": None,
        "token_encrypted": None, "token_protected": False,
    }
    _save_config(cfg)


def get_effective_token(path: Path | None = None) -> str:
    """Raccourci — délègue à get_effective_token_unified()."""
    return get_effective_token_unified(path)


# ──────────────────────────────────────────────
# CRYPTO (Whirlpool / SHA-512 + XOR)
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# CHIFFREMENT AES-256 via Fernet (AES-128-CBC + HMAC-SHA256)
# Dérivation : PBKDF2-HMAC-SHA256, 480 000 itérations, sel 32 octets aléatoires
#
# Chaque appel à token_encrypt() génère un nouveau sel → les ciphertexts sont
# différents pour le même plaintext+password, ce qui est correct et attendu.
# ──────────────────────────────────────────────────────────────────────────────

def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 → clé 32 octets → encodée base64url pour Fernet."""
    import hashlib as _hl
    raw = _hl.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=AES_KEY_BYTES,
    )
    return base64.urlsafe_b64encode(raw)   # Fernet attend une clé base64url 32B


def token_encrypt(plaintext: str, password: str) -> str:
    """
    Chiffre `plaintext` avec AES-256 (Fernet) dérivé de `password`.
    Format du blob : base64url( salt[32] || fernet_token )
    """
    from cryptography.fernet import Fernet
    salt      = os.urandom(SALT_BYTES)
    fkey      = _derive_fernet_key(password, salt)
    f         = Fernet(fkey)
    encrypted = f.encrypt(plaintext.encode("utf-8"))
    # Préfixer avec le sel pour le stockage
    blob = base64.urlsafe_b64encode(salt + base64.urlsafe_b64decode(encrypted))
    return blob.decode("ascii")


def token_decrypt(ciphertext: str, password: str) -> str:
    """
    Déchiffre un blob produit par token_encrypt().
    Retourne "" si le mot de passe est faux ou le blob corrompu.
    """
    try:
        from cryptography.fernet import Fernet, InvalidToken
        raw       = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        salt      = raw[:SALT_BYTES]
        fernet_tk = base64.urlsafe_b64encode(raw[SALT_BYTES:])
        fkey      = _derive_fernet_key(password, salt)
        f         = Fernet(fkey)
        return f.decrypt(fernet_tk).decode("utf-8")
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# VAULT — Master Password + dérivation de clé unique par domaine
#
# Au premier lancement, l'utilisateur choisit UN mot de passe maître.
# On dérive un verifier (PBKDF2) stocké dans la config pour valider les
# saisies futures. On dérive aussi une clé AES-256 par "domaine"
# (github_token, ssh_key, api_key, env_secret…) via HKDF-like construction :
#   domain_key = PBKDF2(master_password, salt_domain, 480000)
# Ainsi compromettre un secret ne compromet pas les autres.
# ──────────────────────────────────────────────────────────────────────────────

_VAULT_MASTER_KEY: bytes | None = None   # clé en mémoire uniquement (session)

_VAULT_VERIFIER_ITER = 480_000
_VAULT_VERIFIER_LEN  = 64


def vault_is_initialized() -> bool:
    """True si un master password a déjà été créé."""
    cfg = _load_config()
    return bool(cfg.get("vault", {}).get("verifier"))


def vault_init(master_password: str) -> None:
    """
    Initialise le vault avec le mot de passe maître.
    Calcule le verifier (PBKDF2) et le sel global. Ne stocke PAS le mot de passe.
    """
    global _VAULT_MASTER_KEY
    salt     = os.urandom(SALT_BYTES)
    verifier = hashlib.pbkdf2_hmac(
        "sha256", master_password.encode(), salt,
        _VAULT_VERIFIER_ITER, dklen=_VAULT_VERIFIER_LEN,
    )
    cfg = _load_config()
    cfg["vault"] = {
        "verifier": base64.b64encode(verifier).decode(),
        "salt":     base64.b64encode(salt).decode(),
    }
    _save_config(cfg)
    # Dériver la clé maître en mémoire
    _VAULT_MASTER_KEY = _pbkdf2_raw(master_password, salt)


def vault_unlock(master_password: str) -> bool:
    """
    Vérifie le mot de passe et charge la clé maître en mémoire.
    Retourne True si correct.
    """
    global _VAULT_MASTER_KEY
    cfg  = _load_config()
    info = cfg.get("vault", {})
    if not info.get("verifier") or not info.get("salt"):
        return False
    salt     = base64.b64decode(info["salt"])
    expected = base64.b64decode(info["verifier"])
    actual   = hashlib.pbkdf2_hmac(
        "sha256", master_password.encode(), salt,
        _VAULT_VERIFIER_ITER, dklen=_VAULT_VERIFIER_LEN,
    )
    if not hmac.compare_digest(expected, actual):
        return False
    _VAULT_MASTER_KEY = _pbkdf2_raw(master_password, salt)
    return True


def vault_is_unlocked() -> bool:
    return _VAULT_MASTER_KEY is not None


def vault_lock() -> None:
    global _VAULT_MASTER_KEY
    _VAULT_MASTER_KEY = None


def _pbkdf2_raw(password: str, salt: bytes) -> bytes:
    """Dérive 32 octets bruts pour usage interne."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, PBKDF2_ITERATIONS, dklen=AES_KEY_BYTES
    )


def _vault_domain_key(domain: str) -> bytes:
    """
    Dérive une clé Fernet spécifique à un domaine depuis la clé maître.
    Chaque domaine (github_token, ssh_key, api_key…) a sa propre clé.
    """
    if _VAULT_MASTER_KEY is None:
        raise RuntimeError("Vault verrouillé — appelez vault_unlock() d'abord.")
    cfg  = _load_config()
    salt = base64.b64decode(cfg["vault"]["salt"])
    domain_salt = hashlib.sha256(salt + domain.encode()).digest()
    raw  = hashlib.pbkdf2_hmac(
        "sha256", _VAULT_MASTER_KEY, domain_salt, 1, dklen=AES_KEY_BYTES
    )
    return base64.urlsafe_b64encode(raw)


def vault_encrypt(plaintext: str, domain: str) -> str:
    """Chiffre `plaintext` avec la clé dérivée pour `domain`."""
    from cryptography.fernet import Fernet
    key = _vault_domain_key(domain)
    return Fernet(key).encrypt(plaintext.encode()).decode()


def vault_decrypt(ciphertext: str, domain: str) -> str:
    """Déchiffre un secret du vault. Retourne "" si échoue."""
    try:
        from cryptography.fernet import Fernet
        key = _vault_domain_key(domain)
        return Fernet(key).decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""


def vault_store(key: str, value: str, domain: str = "general") -> None:
    """Stocke un secret chiffré dans la config sous vault.secrets.<key>."""
    cfg = _load_config()
    cfg.setdefault("vault", {}).setdefault("secrets", {})[key] = {
        "domain":     domain,
        "ciphertext": vault_encrypt(value, domain),
    }
    _save_config(cfg)


def vault_retrieve(key: str) -> str:
    """Récupère et déchiffre un secret du vault. Retourne "" si absent/verrouillé."""
    cfg    = _load_config()
    entry  = cfg.get("vault", {}).get("secrets", {}).get(key)
    if not entry:
        return ""
    return vault_decrypt(entry["ciphertext"], entry.get("domain", "general"))


def vault_delete(key: str) -> None:
    cfg = _load_config()
    cfg.get("vault", {}).get("secrets", {}).pop(key, None)
    _save_config(cfg)


def vault_list_keys() -> list[str]:
    cfg = _load_config()
    return list(cfg.get("vault", {}).get("secrets", {}).keys())


# ──────────────────────────────────────────────
# INSTANCES
# ──────────────────────────────────────────────

def list_instances() -> list:
    return _load_config().get("instances", [])


def create_instance(drive: str, name: str) -> Path:
    name = name.strip()
    validate_name(name)
    root = get_instances_root(drive)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if path.exists():
        raise FileExistsError(f"L'instance « {name} » existe déjà ({path}).")
    path.mkdir(parents=True, exist_ok=True)
    cfg = _load_config()
    cfg["instances"].append({
        "name": name, "path": str(path), "drive": drive,
        "created": datetime.now().isoformat(),
        "github_repo": None, "github_branch": "main",
        "github_branches": ["main"], "github_token": "",
        "github_token_protected": False, "note": "",
        "status": DEFAULT_PROJECT_STATUS, "color": None,
        "emoji": None, "category": None, "language": None,
    })
    _save_config(cfg)
    return path


def delete_instance(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    cfg = _load_config()
    cfg["instances"] = [e for e in cfg["instances"] if e["path"] != str(path)]
    _save_config(cfg)


def rename_instance(path: Path, new_name: str) -> Path:
    validate_name(new_name)
    new_path = path.parent / new_name
    if new_path.exists():
        raise FileExistsError(f"Un dossier « {new_name} » existe déjà.")
    path.rename(new_path)
    cfg = _load_config()
    entry = _find_entry(cfg, "instances", path)
    if entry:
        entry["path"] = str(new_path)
        entry["name"] = new_name
    _save_config(cfg)
    return new_path


def rename_intent(path: Path, new_name: str) -> Path:
    validate_name(new_name)
    new_path = path.parent / new_name
    if new_path.exists():
        raise FileExistsError(f"Un dossier « {new_name} » existe déjà.")
    path.rename(new_path)
    cfg = _load_config()
    entry = _find_entry(cfg, "intents", path)
    if entry:
        entry["path"] = str(new_path)
        entry["name"] = new_name
    _save_config(cfg)
    return new_path


def get_instance_note(path: Path) -> str:
    cfg = _load_config()
    entry = _find_entry(cfg, "instances", path)
    return (entry.get("note") or "") if entry else ""


def set_instance_note(path: Path, note: str) -> None:
    cfg = _load_config()
    _update_entry(cfg, "instances", path, note=note)
    _save_config(cfg)


def get_instance_repo(path: Path) -> str:
    cfg = _load_config()
    entry = _find_entry(cfg, "instances", path)
    return (entry.get("github_repo") or "") if entry else ""


def set_instance_repo(path: Path, url: str) -> None:
    cfg = _load_config()
    _update_entry(cfg, "instances", path, github_repo=url)
    _save_config(cfg)


def get_instance_branch(path: Path) -> str:
    cfg = _load_config()
    entry = _find_entry(cfg, "instances", path)
    return (entry.get("github_branch") or "main") if entry else "main"


def set_instance_branch(path: Path, branch: str) -> None:
    cfg = _load_config()
    _update_entry(cfg, "instances", path, github_branch=branch)
    _save_config(cfg)


def get_instance_branches(path: Path) -> list:
    cfg = _load_config()
    entry = _find_entry(cfg, "instances", path)
    return (entry.get("github_branches") or ["main"]) if entry else ["main"]


def set_instance_branches(path: Path, branches: list) -> None:
    cfg = _load_config()
    _update_entry(cfg, "instances", path, github_branches=branches)
    _save_config(cfg)


def set_instance_token(path: Path, token: str, password: str = "") -> None:
    if password:
        stored    = token_encrypt(token, password)
        protected = True
        _SESSION_VAULT[str(path)] = token
    else:
        stored    = token
        protected = False
    cfg = _load_config()
    _update_entry(cfg, "instances", path, github_token=stored, github_token_protected=protected)
    _save_config(cfg)


def get_instance_token_raw(path: Path) -> str:
    cfg = _load_config()
    entry = _find_entry(cfg, "instances", path)
    return (entry.get("github_token") or "") if entry else ""


def is_token_protected(path: Path) -> bool:
    cfg = _load_config()
    entry = _find_entry(cfg, "instances", path)
    return bool(entry.get("github_token_protected", False)) if entry else False


def get_instance_token(path: Path, password: str = "") -> str:
    vault_key = str(path)
    if vault_key in _SESSION_VAULT:
        return _SESSION_VAULT[vault_key]
    raw = get_instance_token_raw(path)
    if not raw:
        return ""
    if is_token_protected(path):
        if not password:
            return ""
        decrypted = token_decrypt(raw, password)
        if decrypted:
            _SESSION_VAULT[vault_key] = decrypted
        return decrypted
    return raw


def vault_session_store(path: Path, token: str) -> None:
    """Stocke un token déchiffré en mémoire (session uniquement, non persisté)."""
    _SESSION_VAULT[str(path)] = token


def vault_session_clear(path: Path) -> None:
    """Supprime un token du cache de session."""
    _SESSION_VAULT.pop(str(path), None)


# ──────────────────────────────────────────────
# MISES À JOUR — Vérification GitHub Releases
# ──────────────────────────────────────────────

def _version_gt(v1: str, v2: str) -> bool:
    """True si v1 > v2 (comparaison sémantique X.Y.Z)."""
    def _parse(v: str) -> tuple:
        try:
            return tuple(int(x) for x in v.strip().lstrip("v").split("."))
        except ValueError:
            return (0,)
    return _parse(v1) > _parse(v2)


def check_for_update() -> tuple[bool, str, str]:
    """
    Interroge l'API GitHub Releases pour vérifier si une nouvelle version est disponible.
    Retourne (update_available: bool, latest_version: str, release_url: str).
    Ne lève jamais d'exception — toujours sûr à appeler depuis un thread.
    """
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/yo-le-zz/Voktora/releases/latest",
            headers={
                "User-Agent": f"{APP_NAME}/{APP_VERSION}",
                "Accept":     "application/vnd.github+json",
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest  = data.get("tag_name", "").lstrip("v").strip()
        rel_url = data.get("html_url",
                           "https://github.com/yo-le-zz/Voktora/releases/latest")
        if latest and _version_gt(latest, APP_VERSION):
            return True, latest, rel_url
        return False, latest, rel_url
    except Exception:
        return False, "", ""


# ──────────────────────────────────────────────
# ORDRE DES PROJETS — persistance drag & drop / tri
# ──────────────────────────────────────────────

def reorder_entries(kind: str, ordered_paths: list[str]) -> None:
    """
    Persiste l'ordre des instances ou intents après un glisser-déposer.
    kind        : "instance" ou "intent"
    ordered_paths : chemins dans le nouvel ordre.
    Les entrées absentes de la liste sont ajoutées à la fin (sécurité).
    """
    key = f"{kind}s"          # "instances" | "intents"
    cfg = _load_config()
    entries       = cfg.get(key, [])
    path_to_entry = {e["path"]: e for e in entries}
    reordered: list[dict] = []
    for p in ordered_paths:
        if p in path_to_entry:
            reordered.append(path_to_entry[p])
    seen = set(ordered_paths)
    for e in entries:
        if e["path"] not in seen:
            reordered.append(e)
    cfg[key] = reordered
    _save_config(cfg)


# ──────────────────────────────────────────────
# TRANSFERT Instance ↔ Intent (v1.0.1)
# ──────────────────────────────────────────────

def transfer_project(path: Path, from_kind: str, to_kind: str) -> Path:
    """
    Transfère un projet d'un type à l'autre (instance → intent ou intent → instance).
    Déplace le dossier et met à jour la configuration.

    Args:
        path:      Chemin du projet à transférer.
        from_kind: "instance" ou "intent".
        to_kind:   "instance" ou "intent".

    Returns:
        Nouveau chemin du projet après déplacement.

    Raises:
        ValueError:      Si from_kind == to_kind ou types invalides.
        FileExistsError: Si un projet du même nom existe déjà dans la destination.
    """
    if from_kind == to_kind:
        raise ValueError("Le projet est déjà de ce type.")
    if from_kind not in ("instance", "intent") or to_kind not in ("instance", "intent"):
        raise ValueError("Types invalides (attendu : 'instance' ou 'intent').")

    cfg = _load_config()
    from_key = f"{from_kind}s"
    to_key   = f"{to_kind}s"

    # Retrouver l'entrée source
    src_entry = _find_entry(cfg, from_key, path)
    if src_entry is None:
        raise FileNotFoundError(f"Projet introuvable dans la configuration : {path}")

    # Calculer le chemin de destination
    drive = src_entry.get("drive", "")
    name  = src_entry.get("name", path.name)

    if to_kind == "instance":
        dest_root = get_instances_root(drive)
    else:
        dest_root = get_intents_root(drive)

    dest_root.mkdir(parents=True, exist_ok=True)
    new_path = dest_root / name

    if new_path.exists():
        raise FileExistsError(
            f"Un projet nommé « {name} » existe déjà dans les {to_kind}s."
        )

    # Déplacer physiquement le dossier
    shutil.move(str(path), str(new_path))

    # Créer la nouvelle entrée
    new_entry = dict(src_entry)
    new_entry["path"] = str(new_path)
    new_entry["drive"] = drive

    # Les intents n'ont pas les champs GitHub — nettoyer si passage vers intent
    if to_kind == "intent":
        for field in ["github_repo", "github_branch", "github_branches",
                       "github_token", "github_token_protected"]:
            new_entry.pop(field, None)
    else:
        # Passage vers instance : ajouter les champs GitHub manquants
        new_entry.setdefault("github_repo", None)
        new_entry.setdefault("github_branch", "main")
        new_entry.setdefault("github_branches", ["main"])
        new_entry.setdefault("github_token", "")
        new_entry.setdefault("github_token_protected", False)

    # Mettre à jour la configuration : supprimer de la source, ajouter dans la dest
    cfg[from_key] = [e for e in cfg[from_key] if e["path"] != str(path)]
    cfg[to_key].append(new_entry)
    _save_config(cfg)

    return new_path


# ──────────────────────────────────────────────
# CLONE DANS UN PROJET EXISTANT (v1.0.1)
# ──────────────────────────────────────────────

def clone_into_existing(project_path: Path, repo_url: str,
                         token: str = "", branch: str = "main") -> str:
    """
    Clone un repo GitHub dans un projet/dossier existant.
    Utilise `git clone --no-checkout` puis copie les fichiers.
    Le dossier `project_path` doit déjà exister.

    Returns: Sortie de la commande git.
    """
    if not project_path.exists():
        raise FileNotFoundError(f"Le dossier projet n'existe pas : {project_path}")

    # Construire l'URL avec token si nécessaire
    clone_url = repo_url
    if token and repo_url.startswith("https://"):
        clone_url = "https://" + token + "@" + repo_url[len("https://"):]

    # Clone dans un dossier temporaire
    tmp_dir = project_path.parent / f"_voktora_tmp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        out = _run_git(["clone", "--branch", branch, clone_url, str(tmp_dir)],
                       project_path.parent)
        # Copier le contenu (sauf .git si on veut conserver le .git existant)
        git_src = tmp_dir / ".git"
        for item in tmp_dir.iterdir():
            dst = project_path / item.name
            if item.is_dir():
                if dst.exists():
                    shutil.copytree(str(item), str(dst), dirs_exist_ok=True)
                else:
                    shutil.copytree(str(item), str(dst))
            else:
                shutil.copy2(str(item), str(dst))
        return out
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ──────────────────────────────────────────────
# INTENTS
# ──────────────────────────────────────────────

def list_intents() -> list:
    return _load_config().get("intents", [])


def create_intent(drive: str, name: str) -> Path:
    name = name.strip()
    validate_name(name)
    root = get_intents_root(drive)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if path.exists():
        raise FileExistsError(f"L'intent « {name} » existe déjà ({path}).")
    path.mkdir(parents=True, exist_ok=True)
    cfg = _load_config()
    cfg["intents"].append({
        "name": name, "path": str(path), "drive": drive,
        "created": datetime.now().isoformat(), "note": "",
        "color": None, "emoji": None, "category": None, "language": None,
    })
    _save_config(cfg)
    return path


def delete_intent(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    cfg = _load_config()
    cfg["intents"] = [e for e in cfg["intents"] if e["path"] != str(path)]
    _save_config(cfg)


def get_intent_note(path: Path) -> str:
    cfg = _load_config()
    entry = _find_entry(cfg, "intents", path)
    return (entry.get("note") or "") if entry else ""


def set_intent_note(path: Path, note: str) -> None:
    cfg = _load_config()
    _update_entry(cfg, "intents", path, note=note)
    _save_config(cfg)


# ──────────────────────────────────────────────
# EXPORT / IMPORT (ZIP)
# ──────────────────────────────────────────────

def export_to_zip(folder_path: Path, output_dir: Path | None = None) -> Path:
    if output_dir is None:
        output_dir = get_backups_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path  = output_dir / f"{folder_path.name}_{timestamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in folder_path.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(folder_path.parent))
    return zip_path


def import_from_zip(zip_path: Path, drive: str, kind: str) -> Path:
    root = get_instances_root(drive) if kind == "instance" else get_intents_root(drive)
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        top_dirs    = {Path(n).parts[0] for n in zf.namelist() if n.strip("/")}
        folder_name = next(iter(top_dirs)) if top_dirs else zip_path.stem
        zf.extractall(root)
    extracted_path = root / folder_name
    cfg = _load_config()
    key = "instances" if kind == "instance" else "intents"
    existing_paths = {e["path"] for e in cfg[key]}
    if str(extracted_path) not in existing_paths:
        entry: dict = {
            "name": folder_name, "path": str(extracted_path),
            "drive": drive, "created": datetime.now().isoformat(), "note": "",
        }
        if kind == "instance":
            entry.update({
                "github_repo": None, "github_branch": "main",
                "github_branches": ["main"], "github_token": "",
                "github_token_protected": False,
            })
        cfg[key].append(entry)
        _save_config(cfg)
    return extracted_path


# ──────────────────────────────────────────────
# GIT — Infrastructure
# ──────────────────────────────────────────────

def _run_git(args: list, cwd: Path) -> str:
    result = subprocess.run(
        ["git"] + args, cwd=str(cwd),
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW,
    )
    return (result.stdout + result.stderr).strip()



def export_all_to_zip() -> str:
    """Exporte toutes les instances et intents dans un fichier ZIP horodaté."""
    import json as _json
    import zipfile as _zip
    from datetime import datetime as _dt

    backups_dir = get_backups_dir()
    timestamp   = _dt.now().strftime("%Y%m%d_%H%M%S")
    zip_path    = backups_dir / f"voktora_export_{timestamp}.zip"

    with _zip.ZipFile(zip_path, "w", _zip.ZIP_DEFLATED) as zf:
        cfg = _load_config()

        for category, prefix in [("instances", "instances"), ("intents", "intents")]:
            for entry in cfg.get(category, []):
                p = Path(entry["path"])
                if not p.exists():
                    continue
                try:
                    for f in p.rglob("*"):
                        if f.is_file() and ".git/objects" not in str(f):
                            arc = f"{prefix}/{p.name}/{f.relative_to(p)}"
                            zf.write(f, arc)
                except Exception as exc:
                    print(f"[export] {p}: {exc}")

        zf.writestr("config.json",
                    _json.dumps(cfg, indent=2, ensure_ascii=False))
        zf.writestr("export_info.txt",
                    f"Voktora export — {timestamp}\nVersion : {APP_VERSION}\n")

    return str(zip_path)


class GitQueue:
    def __init__(self, path: Path, on_step: Callable | None = None):
        self._path    = path
        self._on_step = on_step
        self._cmds:   list = []

    def add(self, args: list, label: str | None = None) -> "GitQueue":
        self._cmds.append((args, label))
        return self

    def run_all(self) -> list:
        outputs = []
        for args, label in self._cmds:
            out = _run_git(args, self._path)
            if self._on_step:
                self._on_step(label or " ".join(args), out)
            outputs.append(out)
        return outputs


def git_set_github_credentials(path: Path, username: str, token: str) -> str:
    _run_git(["config", "user.name", username], path)
    url = f"https://{username}:{token}@github.com/"
    _run_git(["config", "credential.helper", "store"], path)
    _run_git(["remote", "set-url", "origin", url], path)
    return f"Credentials configurées pour {username}"


def git_clone_with_auth(repo_url: str, target_path: Path, username: str, token: str) -> str:
    auth_url = repo_url.replace("https://github.com/", f"https://{username}:{token}@github.com/")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    return _run_git(["clone", auth_url, str(target_path)], target_path.parent)


def git_clone_public(repo_url: str, target_path: Path) -> str:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    return _run_git(["clone", repo_url, str(target_path)], target_path.parent)


def git_clone(repo_url: str, target_path: Path, token: str = "") -> str:
    if not token:
        token = get_effective_token()
    if token:
        try:
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={"Authorization": f"token {token}",
                         "User-Agent": f"{APP_NAME}/{APP_VERSION}"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                user_data = json.loads(resp.read().decode())
                username = user_data.get("login", "voktora-user")
        except Exception:
            username = "voktora-user"
        return git_clone_with_auth(repo_url, target_path, username, token)
    else:
        return git_clone_public(repo_url, target_path)


def git_init(path: Path) -> str:
    return _run_git(["init"], path)


def git_pull(path: Path, branch: str = "main") -> str:
    return _run_git(["pull", "origin", branch.strip() or "main"], path)


def git_status(path: Path) -> str:
    return _run_git(["status"], path)


def git_log(path: Path, n: int = 15) -> str:
    return _run_git(
        ["log", f"--max-count={n}", "--oneline", "--decorate", "--color=never"], path,
    )


def git_list_local_branches(path: Path) -> list:
    raw = _run_git(["branch", "--format=%(refname:short)"], path)
    return [b.strip() for b in raw.splitlines() if b.strip()]


def git_checkout(path: Path, branch: str) -> str:
    branch = branch.strip()
    out    = _run_git(["checkout", branch], path)
    if "error" in out.lower() or "fatal" in out.lower():
        out = _run_git(["checkout", "-b", branch], path)
    return out


def git_merge(path: Path, branch: str, token: str = "", on_step: Callable | None = None) -> None:
    gq = GitQueue(path, on_step=on_step)
    gq.add(["merge", branch.strip()], label=f"merge {branch.strip()}")
    gq.run_all()


def git_push_advanced(path: Path, repo_url: str, branches: list,
                       message: str = "", description: str = "",
                       force: bool = False, follow_tags: bool = False,
                       no_verify: bool = False, is_initial: bool = False,
                       on_step: Callable | None = None) -> None:
    branches = [b.strip() for b in branches if b.strip()] or ["main"]
    if not message:
        message = ("Initial commit — Voktora" if is_initial
                   else f"Voktora commit — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    full_message = message.strip()
    if description and description.strip():
        full_message = f"{full_message}\n\n{description.strip()}"

    gq = GitQueue(path, on_step=on_step)
    gq.add(["add", "."], label="add .")
    gq.add(["commit", "-m", full_message], label=f'commit -m "{message[:60]}"')

    existing_remotes = _run_git(["remote"], path).splitlines()
    if "origin" in existing_remotes:
        gq.add(["remote", "set-url", "origin", repo_url], label="remote set-url origin …")
    else:
        gq.add(["remote", "add", "origin", repo_url], label="remote add origin …")

    for branch in branches:
        if is_initial:
            gq.add(["branch", "-M", branch], label=f"branch -M {branch}")
        push_args = ["push", "-u", "origin", branch]
        if force:       push_args.append("--force")
        if follow_tags: push_args.append("--follow-tags")
        if no_verify:   push_args.append("--no-verify")
        gq.add(push_args, label=" ".join(push_args[1:]))

    gq.run_all()


def git_push_initial(path: Path, repo_url: str, branch: str = "main") -> str:
    lines: list = []
    git_push_advanced(path=path, repo_url=repo_url, branches=[branch],
                      force=True, is_initial=True,
                      on_step=lambda cmd, out: lines.append(f"$ git {cmd}\n{out}"))
    return "\n".join(lines)


def git_commit_and_push(path: Path, repo_url: str, branch: str = "main", message: str = "") -> str:
    lines: list = []
    git_push_advanced(path=path, repo_url=repo_url, branches=[branch], message=message,
                      on_step=lambda cmd, out: lines.append(f"$ git {cmd}\n{out}"))
    return "\n".join(lines)


def verify_github_repo(repo_url: str, token: str = "") -> tuple:
    url_clean = repo_url.rstrip("/").removesuffix(".git")
    parts = url_clean.rstrip("/").split("/")
    if len(parts) < 2:
        return False, "⚠  URL invalide."
    owner, repo = parts[-2], parts[-1]
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        name = data.get("full_name", repo)
        private_label = "🔒 privé" if data.get("private") else "🌐 public"
        return True, f"✅  Repo trouvé : {name} ({private_label})"
    except urllib.error.HTTPError as e:
        if e.code == 404: return False, "❌  Repo introuvable (404)."
        if e.code == 401: return False, "❌  Non autorisé (401)."
        return False, f"❌  Erreur HTTP {e.code}."
    except Exception as e:
        return False, f"❌  Erreur réseau : {e}"


def list_github_branches(repo_url: str, token: str = "") -> list:
    url_clean = repo_url.rstrip("/").removesuffix(".git")
    parts = url_clean.rstrip("/").split("/")
    if len(parts) < 2:
        return []
    owner, repo = parts[-2], parts[-1]
    api_url = f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100"
    headers = {"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [b["name"] for b in data if isinstance(b, dict)]
    except Exception:
        return []


# ──────────────────────────────────────────────
# SYSTÈME — Windows + Linux
# ──────────────────────────────────────────────

def open_explorer(path: Path) -> None:
    """Ouvre l'explorateur de fichiers au chemin donné (Windows + Linux)."""
    if IS_WINDOWS:
        subprocess.Popen(["explorer", str(path)])
    elif IS_LINUX:
        # Essayer plusieurs gestionnaires de fichiers courants
        for fm in ["xdg-open", "nautilus", "dolphin", "thunar", "nemo", "pcmanfm"]:
            try:
                subprocess.Popen([fm, str(path)])
                return
            except FileNotFoundError:
                continue
    else:
        # macOS
        subprocess.Popen(["open", str(path)])


def open_terminal(path: Path) -> None:
    """Ouvre un terminal au chemin donné (Windows + Linux)."""
    if IS_WINDOWS:
        subprocess.Popen(
            f'start "Voktora Terminal" cmd /k "cd /d "{path}""',
            shell=True,
        )
    elif IS_LINUX:
        # Essayer plusieurs émulateurs de terminal courants
        terminals = [
            ["gnome-terminal", f"--working-directory={path}"],
            ["konsole", "--workdir", str(path)],
            ["xterm", "-e", f"cd '{path}' && bash"],
            ["xfce4-terminal", f"--working-directory={path}"],
            ["tilix", f"--working-directory={path}"],
            ["bash", "-c", f"cd '{path}' && bash"],
        ]
        for cmd in terminals:
            try:
                subprocess.Popen(cmd)
                return
            except FileNotFoundError:
                continue
    else:
        subprocess.Popen(["open", "-a", "Terminal", str(path)])


def open_vscode(path: Path) -> None:
    """Ouvre VS Code au chemin donné."""
    try:
        subprocess.Popen(["code", str(path)])
    except FileNotFoundError:
        raise RuntimeError(
            "VS Code (commande 'code') est introuvable dans le PATH.\n"
            "Installez VS Code et activez la commande 'code' dans votre PATH."
        )


def open_app_at_path(cmd: str, path: Path) -> None:
    """
    Ouvre une application personnalisée avec le chemin projet.
    La commande peut contenir {path} comme placeholder.
    Ex : cmd = "code {path}"  →  code /home/user/MonProjet
    """
    if "{path}" in cmd:
        full_cmd = cmd.replace("{path}", str(path))
    else:
        full_cmd = f"{cmd} {path}"
    subprocess.Popen(full_cmd, shell=True)


def run_project_builder(path: Path) -> None:
    if IS_WINDOWS:
        try:
            cmd = [PROJECT_BUILDER, f"--path={str(path)}"]
            subprocess.Popen(cmd, cwd=str(path))
        except (OSError, subprocess.SubprocessError):
            cmd = (f'start "ProjectsBuilder" cmd /k '
                   f'"cd /d "{path}" && "{PROJECT_BUILDER}""')
            subprocess.Popen(cmd, shell=True, cwd=str(path))
    else:
        raise RuntimeError("Project Builder n'est disponible que sous Windows.")


def open_url_in_browser(url: str) -> None:
    import webbrowser
    webbrowser.open(url)


# ──────────────────────────────────────────────
# DIAGNOSTIC & RÉPARATION
# ──────────────────────────────────────────────

@dataclass
class DiagnosticIssue:
    level:     str
    category:  str
    title:     str
    detail:    str
    can_fix:   bool = False
    fix_label: str  = ""


@dataclass
class HealthCheckResult:
    issues: list = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.level == "warning" for i in self.issues)

    @property
    def is_healthy(self) -> bool:
        return not self.issues


def run_health_check() -> HealthCheckResult:
    result = HealthCheckResult()
    cfg_path = get_config_path()
    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                result.issues.append(DiagnosticIssue(
                    level="error", category="config",
                    title="config.json invalide",
                    detail="Le fichier de configuration n'est pas un objet JSON valide.",
                    can_fix=True, fix_label="Réinitialiser la configuration",
                ))
        except (json.JSONDecodeError, OSError) as exc:
            result.issues.append(DiagnosticIssue(
                level="error", category="config",
                title="config.json corrompu",
                detail=f"Impossible de lire la configuration : {exc}",
                can_fix=True, fix_label="Réinitialiser la configuration",
            ))

    try:
        cfg = _load_config()
        orphan_instances = [e for e in cfg.get("instances", []) if not Path(e["path"]).exists()]
        orphan_intents   = [e for e in cfg.get("intents", [])   if not Path(e["path"]).exists()]
        if orphan_instances or orphan_intents:
            names = [e["name"] for e in orphan_instances + orphan_intents]
            result.issues.append(DiagnosticIssue(
                level="warning", category="data",
                title=f"{len(names)} entrée(s) orpheline(s) détectée(s)",
                detail=(f"Dossiers référencés mais absents : {', '.join(names)}."),
                can_fix=True, fix_label="Supprimer les entrées orphelines",
            ))
    except ConfigCorruptedError:
        pass

    try:
        subprocess.run(["git", "--version"], capture_output=True,
                       timeout=5, creationflags=_NO_WINDOW)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        result.issues.append(DiagnosticIssue(
            level="warning", category="dependency",
            title="git introuvable dans le PATH",
            detail="Installez Git depuis https://git-scm.com",
            can_fix=False,
        ))

    try:
        import importlib
        importlib.import_module("PySide6")
    except ImportError:
        result.issues.append(DiagnosticIssue(
            level="error", category="dependency",
            title="PySide6 manquant",
            detail="Le module PySide6 n'est pas installé.",
            can_fix=True, fix_label="Réinstaller PySide6 (pip)",
        ))

    if not is_github_client_id_configured():
        result.issues.append(DiagnosticIssue(
            level="warning", category="config",
            title="GitHub OAuth non configuré",
            detail="Aucun Client ID GitHub OAuth configuré.",
            can_fix=False,
        ))

    return result


def repair_config() -> tuple:
    global _config_cache
    cfg_path = get_config_path()
    salvaged_instances: list = []
    salvaged_intents:   list = []
    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                salvaged_instances = [e for e in raw.get("instances", [])
                                       if isinstance(e, dict) and "name" in e and "path" in e]
                salvaged_intents   = [e for e in raw.get("intents", [])
                                       if isinstance(e, dict) and "name" in e and "path" in e]
        except Exception:
            pass
        backup = cfg_path.with_suffix(".json.bak")
        try:
            shutil.copy2(cfg_path, backup)
        except OSError:
            pass

    new_cfg = _get_default_config()
    new_cfg["instances"] = salvaged_instances
    new_cfg["intents"]   = salvaged_intents
    _config_cache = None
    try:
        new_cfg, _ = _migrate_config(new_cfg)
        _save_config(new_cfg)
    except OSError as exc:
        return False, f"Impossible d'écrire la configuration : {exc}"
    return True, (f"Configuration réparée. {len(salvaged_instances)} instance(s), "
                  f"{len(salvaged_intents)} intent(s) récupérés.")


def repair_orphans() -> tuple:
    try:
        cfg = _load_config()
    except ConfigCorruptedError as exc:
        return False, str(exc)
    before_inst = len(cfg["instances"])
    before_int  = len(cfg["intents"])
    cfg["instances"] = [e for e in cfg["instances"] if Path(e["path"]).exists()]
    cfg["intents"]   = [e for e in cfg["intents"]   if Path(e["path"]).exists()]
    removed = (before_inst - len(cfg["instances"])) + (before_int - len(cfg["intents"]))
    _save_config(cfg)
    return True, f"{removed} entrée(s) orpheline(s) supprimée(s)."


def reinstall_dependencies() -> tuple:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "PySide6"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, creationflags=_NO_WINDOW,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "La réinstallation a dépassé le délai (120s)."
    except Exception as exc:
        return False, f"Erreur : {exc}"


# ──────────────────────────────────────────────
# DÉSINSTALLATION — Windows + Linux
# ──────────────────────────────────────────────

def uninstall_backup_all(destination: Path) -> list:
    destination.mkdir(parents=True, exist_ok=True)
    done: list = []
    for item in get_backups_dir().iterdir():
        dst = destination / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)
        done.append(f"[backup existant] {item.name}")
    cfg = _load_config()
    for entry in cfg.get("instances", []):
        p = Path(entry["path"])
        if p.exists():
            try:
                zp = export_to_zip(p, destination)
                done.append(f"[instance] {entry['name']} → {zp.name}")
            except Exception as e:
                done.append(f"[ERREUR instance] {entry['name']} : {e}")
    for entry in cfg.get("intents", []):
        p = Path(entry["path"])
        if p.exists():
            try:
                zp = export_to_zip(p, destination)
                done.append(f"[intent] {entry['name']} → {zp.name}")
            except Exception as e:
                done.append(f"[ERREUR intent] {entry['name']} : {e}")
    return done


def create_uninstall_script() -> Path:
    app_dir  = get_app_dir()
    data_dir = get_data_dir()

    if IS_WINDOWS:
        temp_dir = Path(os.environ.get("TEMP", r"C:\Windows\Temp"))
        script_path = temp_dir / "voktora_uninstall.bat"
        lines = [
            "@echo off", "chcp 65001 > nul", "echo.",
            "echo  Voktora - Desinstallation en cours...",
            "timeout /t 2 /nobreak > nul",
            f'if exist "{app_dir}" (',
            f'    rmdir /s /q "{app_dir}"',
            f'    echo  [OK] Supprime : {app_dir}',
            ") else (", "    echo  [INFO] Dossier app deja absent.", ")",
        ]
        try:
            data_dir.relative_to(app_dir)
        except ValueError:
            lines += [
                f'if exist "{data_dir}" (',
                f'    rmdir /s /q "{data_dir}"',
                f'    echo  [OK] Donnees supprimees : {data_dir}', ")",
            ]
        lines += ["echo.", "echo  Voktora a ete desinstalle proprement.",
                  "timeout /t 2 /nobreak > nul", 'del "%~f0"']
        script_path.write_text("\n".join(lines), encoding="utf-8")
    else:
        # Linux : script bash
        temp_dir = Path("/tmp")
        script_path = temp_dir / "voktora_uninstall.sh"
        lines = [
            "#!/bin/bash", "echo ''",
            "echo 'Voktora - Désinstallation en cours...'",
            "sleep 2",
            f'if [ -d "{app_dir}" ]; then',
            f'    rm -rf "{app_dir}"',
            f'    echo "[OK] Supprimé : {app_dir}"',
            "else", "    echo '[INFO] Dossier app absent.'", "fi",
        ]
        try:
            data_dir.relative_to(app_dir)
        except ValueError:
            lines += [
                f'if [ -d "{data_dir}" ]; then',
                f'    rm -rf "{data_dir}"',
                f'    echo "[OK] Données supprimées : {data_dir}"', "fi",
            ]
        lines += ["echo ''", "echo 'Voktora désinstallé.'",
                  "rm -- \"$0\""]  # Auto-suppression du script
        script_path.write_text("\n".join(lines), encoding="utf-8")
        os.chmod(script_path, 0o755)

    return script_path


def launch_uninstall_and_quit(script_path: Path) -> None:
    if IS_WINDOWS:
        subprocess.Popen(
            f'start "Voktora — Désinstallation" cmd /c "{script_path}"',
            shell=True,
        )
    else:
        subprocess.Popen(["bash", str(script_path)])
    sys.exit(0)


# ──────────────────────────────────────────────
# EXCEPTIONS PERSONNALISÉES
# ──────────────────────────────────────────────

class ConfigCorruptedError(RuntimeError):
    """Levée quand config.json est illisible ou structurellement invalide."""


class OAuthError(RuntimeError):
    """Levée lors d'un échec du flux OAuth GitHub."""
