"""
Voktora — core.diagnostics
Fragment de core.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import config_store, constants, github_auth, paths, projects

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
    cfg_path = paths.get_config_path()
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
        cfg = config_store._load_config()
        orphans = [e for e in cfg.get("projects", []) if not Path(e["path"]).exists()]
        if orphans:
            names = [e["name"] for e in orphans]
            result.issues.append(DiagnosticIssue(
                level="warning", category="data",
                title=f"{len(names)} entrée(s) orpheline(s) détectée(s)",
                detail=(f"Dossiers référencés mais absents : {', '.join(names)}."),
                can_fix=True, fix_label="Supprimer les entrées orphelines",
            ))
    except constants.ConfigCorruptedError:
        pass

    try:
        subprocess.run(["git", "--version"], capture_output=True,
                       timeout=5, creationflags=constants._NO_WINDOW, check=False)
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

    already_connected = (
        github_auth.get_github_account_info()["connected"]
        or (github_auth.is_using_github_app() and github_auth.is_github_app_configured())
    )
    notice_hidden = config_store.get_app_config().get("hide_github_not_connected", False)
    if not already_connected and not notice_hidden and not github_auth.is_github_client_id_configured():
        result.issues.append(DiagnosticIssue(
            level="warning", category="config",
            title="GitHub OAuth non configuré",
            detail="Aucun Client ID GitHub OAuth configuré.",
            can_fix=False,
        ))

    return result


def repair_config() -> tuple:
    cfg_path = paths.get_config_path()
    salvaged_projects: list = []
    salvaged_categories: list = []
    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                # « instances » / « intents » : ancien format, récupéré aussi.
                for key in ("projects", "instances", "intents"):
                    salvaged_projects += [e for e in raw.get(key) or []
                                          if isinstance(e, dict) and "name" in e and "path" in e]
                salvaged_categories = raw.get("categories") or []
        except Exception:
            pass
        backup = cfg_path.with_suffix(".json.bak")
        try:
            shutil.copy2(cfg_path, backup)
        except OSError:
            pass

    new_cfg = config_store._get_default_config()
    new_cfg["projects"] = salvaged_projects
    new_cfg["categories"] = salvaged_categories
    config_store.invalidate_cache()
    try:
        new_cfg, _ = config_store._migrate_config(new_cfg)
        config_store._save_config(new_cfg)
    except OSError as exc:
        return False, f"Impossible d'écrire la configuration : {exc}"
    return True, f"Configuration réparée. {len(new_cfg['projects'])} projet(s) récupéré(s)."


def repair_orphans() -> tuple:
    try:
        cfg = config_store._load_config()
    except constants.ConfigCorruptedError as exc:
        return False, str(exc)
    before = len(cfg["projects"])
    cfg["projects"] = [e for e in cfg["projects"] if Path(e["path"]).exists()]
    removed = before - len(cfg["projects"])
    config_store._save_config(cfg)
    return True, f"{removed} entrée(s) orpheline(s) supprimée(s)."


def reinstall_dependencies() -> tuple:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "PySide6"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, creationflags=constants._NO_WINDOW, check=False,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "La réinstallation a dépassé le délai (120s)."
    except Exception as exc:
        return False, f"Erreur : {exc}"


# ──────────────────────────────────────────────
# DÉSINSTALLATION — Windows + Linux
# ──────────────────────────────────────────────

def uninstall_backup_all(destination: Path, on_progress=None, cancel=None) -> list:
    """Sauvegarde les backups existants et exporte chaque projet. Pensé pour un thread de travail."""
    destination.mkdir(parents=True, exist_ok=True)
    done: list = []
    for item in paths.get_backups_dir().iterdir():
        dst = destination / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)
        done.append(f"[backup existant] {item.name}")
    cfg = config_store._load_config()
    for entry in cfg.get("projects", []):
        p = Path(entry["path"])
        if p.exists():
            try:
                zp = projects.export_to_zip(p, destination, on_progress, cancel)
                done.append(f"[projet] {entry['name']} → {zp.name}")
            except Exception as e:
                done.append(f"[ERREUR projet] {entry['name']} : {e}")
    return done


def _removal_targets() -> list[Path]:
    """Dossiers que la désinstallation peut supprimer, après vérification qu'ils sont raisonnables.

    L'application n'est supprimée que si elle tourne compilée : depuis les sources, `get_app_dir()`
    est le dossier du code (voire du dépôt), qu'un script de désinstallation ne doit jamais effacer.
    Racine de disque, dossier personnel et ses parents sont toujours refusés.
    """
    home = Path.home().resolve()
    app_dir, data_dir = paths.get_app_dir().resolve(), paths.get_data_dir().resolve()
    candidates = [app_dir] if paths.is_frozen() else []
    if data_dir != app_dir and app_dir not in data_dir.parents:
        candidates.append(data_dir)
    targets = []
    for path in candidates:
        if path == path.parent or path == home or path in home.parents:
            raise RuntimeError(f"Suppression refusée : « {path} » est un dossier système ou personnel.")
        targets.append(path)
    return targets


def _write_private_script(suffix: str, content: str) -> Path:
    """Écrit un script dans un fichier temporaire à nom imprévisible, lisible par le seul propriétaire.

    Un nom fixe dans /tmp permettrait à un autre utilisateur local de pré-créer un lien ou un script
    à cet emplacement (écrasement de fichier, ou exécution de code à la place du nôtre).
    """
    fd, name = tempfile.mkstemp(prefix="voktora_uninstall_", suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    if os.name == "posix":
        os.chmod(name, 0o700)
    return Path(name)


def create_uninstall_script() -> Path:
    targets = _removal_targets()

    if constants.IS_WINDOWS:
        lines = [
            "@echo off", "chcp 65001 > nul", "echo.",
            "echo  Voktora - Desinstallation en cours...",
            "timeout /t 2 /nobreak > nul",
        ]
        for target in targets:
            if '"' in str(target) or "%" in str(target):
                raise RuntimeError(f"Chemin non pris en charge pour la désinstallation : {target}")
            lines += [
                f'if exist "{target}" (',
                f'    rmdir /s /q "{target}"',
                f'    echo  [OK] Supprime : {target}',
                ")",
            ]
        lines += ["echo.", "echo  Voktora a ete desinstalle proprement.",
                  "timeout /t 2 /nobreak > nul", 'del "%~f0"']
        return _write_private_script(".bat", "\n".join(lines))

    # Linux : script bash. Les chemins sont échappés par shlex.quote (aucune interprétation par le shell).
    lines = ["#!/bin/bash", "echo ''", "echo 'Voktora - Désinstallation en cours...'", "sleep 2"]
    for target in targets:
        q = shlex.quote(str(target))
        lines += [f"if [ -d {q} ]; then", f"    rm -rf -- {q}", f"    echo \"[OK] Supprimé : \"{q}", "fi"]
    lines += ["echo ''", "echo 'Voktora désinstallé.'", 'rm -- "$0"']   # auto-suppression du script
    return _write_private_script(".sh", "\n".join(lines) + "\n")


def launch_uninstall_and_quit(script_path: Path) -> None:
    if constants.IS_WINDOWS:
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

