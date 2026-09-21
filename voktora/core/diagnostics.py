"""
Voktora — core.diagnostics
Fragment de core.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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

    new_cfg = config_store._get_default_config()
    new_cfg["instances"] = salvaged_instances
    new_cfg["intents"]   = salvaged_intents
    config_store.invalidate_cache()
    try:
        new_cfg, _ = config_store._migrate_config(new_cfg)
        config_store._save_config(new_cfg)
    except OSError as exc:
        return False, f"Impossible d'écrire la configuration : {exc}"
    return True, (f"Configuration réparée. {len(salvaged_instances)} instance(s), "
                  f"{len(salvaged_intents)} intent(s) récupérés.")


def repair_orphans() -> tuple:
    try:
        cfg = config_store._load_config()
    except constants.ConfigCorruptedError as exc:
        return False, str(exc)
    before_inst = len(cfg["instances"])
    before_int  = len(cfg["intents"])
    cfg["instances"] = [e for e in cfg["instances"] if Path(e["path"]).exists()]
    cfg["intents"]   = [e for e in cfg["intents"]   if Path(e["path"]).exists()]
    removed = (before_inst - len(cfg["instances"])) + (before_int - len(cfg["intents"]))
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

def uninstall_backup_all(destination: Path) -> list:
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
    for entry in cfg.get("instances", []):
        p = Path(entry["path"])
        if p.exists():
            try:
                zp = projects.export_to_zip(p, destination)
                done.append(f"[instance] {entry['name']} → {zp.name}")
            except Exception as e:
                done.append(f"[ERREUR instance] {entry['name']} : {e}")
    for entry in cfg.get("intents", []):
        p = Path(entry["path"])
        if p.exists():
            try:
                zp = projects.export_to_zip(p, destination)
                done.append(f"[intent] {entry['name']} → {zp.name}")
            except Exception as e:
                done.append(f"[ERREUR intent] {entry['name']} : {e}")
    return done


def create_uninstall_script() -> Path:
    app_dir  = paths.get_app_dir()
    data_dir = paths.get_data_dir()

    if constants.IS_WINDOWS:
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

