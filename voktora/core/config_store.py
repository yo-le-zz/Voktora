"""
Voktora — core.config_store
Fragment de core.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import json
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
            for field_name, default in [("status", constants.DEFAULT_PROJECT_STATUS), ("color", None),
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
        ("auth_method", constants.AUTH_METHOD_OAUTH), ("github_client_id", ""),
    ]:
        if key not in app_cfg:
            app_cfg[key] = val
            changed = True

    # Migration entrées instances
    for entry in cfg["instances"]:
        for field_name, default in [
            ("github_branches", [entry.get("github_branch") or "main"]),
            ("github_token_protected", False), ("note", ""),
            ("status", constants.DEFAULT_PROJECT_STATUS), ("color", None),
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
        "_schema_version": constants.CONFIG_SCHEMA_VERSION,
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

    _migrate_legacy_configs(cfg_path.parent)

    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            if _safe_winerror(exc) == 2:
                cfg = _get_default_config()
            else:
                raise constants.ConfigCorruptedError(f"config.json illisible : {exc}") from exc
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
            if legacy_file == paths.get_config_path():
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


def _merge_legacy_config(legacy_cfg: dict, filename: str, migrations_made: list) -> None:
    try:
        current_cfg = _load_config() if paths.get_config_path().exists() else _get_default_config()
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


