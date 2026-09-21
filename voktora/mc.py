"""
Voktora — mc.py
Migration multi-ordinateur : export/import de la configuration (projets,
catégories, statuts personnalisés) sous forme de bundle portable `.mpack`
(zip), avec réécriture de chemins par règles de préfixe lors de l'import.
Les bundles créés avant la version 1.0.3 (listes « instances » et « intents »)
restent importables : ils sont fusionnés en projets.

Par sécurité, le bundle exporté ne contient JAMAIS de secret : ni le
compte/token GitHub, ni le contenu du coffre (vault). Un bundle .mpack
peut donc être partagé ou stocké sans exposer d'identifiants.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import core

_MANIFEST_NAME = "manifest.json"
_CONFIG_NAME = "config.json"

# Clés de configuration incluses dans un bundle. Explicitement absentes :
# "github_account" et "vault" (secrets), qui ne doivent jamais quitter la
# machine dans un fichier portable non chiffré.
_EXPORTED_KEYS = ("projects", "categories", "custom_statuses")
_BUNDLE_VERSION = 2


@dataclass
class MigrationResult:
    success: bool
    message: str
    log: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def export_bundle(dest: Path, on_progress: Callable[[str, int], None] | None = None) -> MigrationResult:
    """Exporte la configuration courante (hors secrets) dans un bundle .mpack."""
    dest = Path(dest)
    log: list[str] = []
    warnings: list[str] = []

    def progress(msg: str, pct: int) -> None:
        if on_progress:
            on_progress(msg, pct)

    try:
        progress("Lecture de la configuration…", 10)
        cfg = core._load_config()
        payload = {key: cfg.get(key, [] if key in ("projects", "categories") else {})
                   for key in _EXPORTED_KEYS}
        # Les tokens de projet sont des secrets : jamais dans un bundle partageable.
        payload["projects"] = [{**e, "github_token": "", "github_token_protected": False}
                               for e in payload["projects"]]
        n_projects = len(payload["projects"])

        manifest = {
            "bundle_version": _BUNDLE_VERSION,
            "app_version": core.APP_VERSION,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_platform": "windows" if core.IS_WINDOWS else "linux",
            "_detected_project_count": n_projects,
        }

        progress("Écriture du bundle…", 50)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(_CONFIG_NAME, json.dumps(payload, ensure_ascii=False, indent=2))
            zf.writestr(_MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))

        progress("Terminé", 100)
        log.append(f"{n_projects} projet(s) exporté(s) vers {dest.name}")
        return MigrationResult(True, f"Export réussi : {n_projects} projet(s) écrit(s) dans {dest.name}.", log, warnings)

    except OSError as exc:
        return MigrationResult(False, f"Erreur d'écriture du bundle : {exc}", log, warnings)


def validate_bundle(path: Path) -> dict:
    """Vérifie qu'un fichier est un bundle .mpack valide et lit son manifeste."""
    path = Path(path)
    if not path.exists():
        return {"valid": False, "error": f"Fichier introuvable : {path}", "manifest": {}}

    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if _MANIFEST_NAME not in names or _CONFIG_NAME not in names:
                return {"valid": False, "error": "Ce fichier n'est pas un bundle Voktora valide (.mpack).", "manifest": {}}
            manifest = json.loads(zf.read(_MANIFEST_NAME))
            payload = json.loads(zf.read(_CONFIG_NAME))
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError) as exc:
        return {"valid": False, "error": f"Bundle corrompu ou illisible : {exc}", "manifest": {}}

    manifest["_detected_project_count"] = sum(
        len(payload.get(key) or []) for key in ("projects", "instances", "intents"))
    manifest["_bundle_size_kb"] = round(path.stat().st_size / 1024, 1)
    return {"valid": True, "error": "", "manifest": manifest}


def import_bundle(
    src: Path,
    base: Path,
    custom_rules: list[tuple[str, str]],
    on_progress: Callable[[str, int], None] | None = None,
) -> MigrationResult:
    """Importe un bundle .mpack : remplace les projets locaux par ceux
    du bundle, en réécrivant les chemins selon `custom_rules` (préfixe ancien
    -> préfixe nouveau). Tout chemin ne correspondant à aucune règle est
    replié sous `base` (nom du dossier de projet conservé)."""
    src, base = Path(src), Path(base)
    log: list[str] = []
    warnings: list[str] = []

    def progress(msg: str, pct: int) -> None:
        if on_progress:
            on_progress(msg, pct)

    progress("Validation du bundle…", 10)
    info = validate_bundle(src)
    if not info["valid"]:
        return MigrationResult(False, info["error"], log, warnings)

    def rewrite(raw_path: str) -> str:
        for old, new in custom_rules:
            if raw_path.startswith(old):
                return new + raw_path[len(old):]
        # Aucune règle ne correspond : replier sous le dossier de destination.
        # On extrait le dernier segment manuellement (et non via Path(...).name)
        # car un chemin exporté depuis Windows ("D:\Projects\x") doit être
        # traité correctement même quand l'import a lieu sur Linux, où '\\'
        # n'est pas un séparateur de chemin reconnu par pathlib.
        folder_name = raw_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        return str(base / (folder_name or "projet"))

    try:
        progress("Lecture du bundle…", 30)
        with zipfile.ZipFile(src) as zf:
            payload = json.loads(zf.read(_CONFIG_NAME))

        # Un bundle antérieur à 1.0.3 contient « instances » / « intents » : on les
        # fusionne en projets avec la même routine que la migration de config.
        core.config_store._fold_legacy_kinds(payload)
        new_projects = []
        for entry in payload.get("projects", []):
            entry = dict(entry)
            entry["path"] = rewrite(entry.get("path", ""))
            entry["name"] = entry.get("name") or core.config_store._path_basename(entry["path"])
            core.config_store.normalize_entry(entry)
            new_projects.append(entry)
            log.append(f"Projet « {entry['name']} » → {entry['path']}")

        progress("Écriture de la configuration…", 80)
        cfg = core._load_config()
        cfg["projects"] = new_projects
        used = [e["category"] for e in new_projects if e.get("category")]
        cfg["categories"] = core.config_store.normalize_categories(
            payload.get("categories") or cfg.get("categories", []), used)
        if payload.get("custom_statuses"):
            cfg["custom_statuses"] = payload["custom_statuses"]
        core._save_config(cfg)

        n = len(new_projects)
        progress("Terminé", 100)
        warnings.append(
            "Les chemins sans règle de correspondance ont été replacés sous "
            f"« {base} » : vérifiez qu'ils pointent vers les bons dossiers."
        )
        return MigrationResult(True, f"Import terminé : {n} projet(s) importé(s).", log, warnings)

    except (zipfile.BadZipFile, json.JSONDecodeError, OSError) as exc:
        return MigrationResult(False, f"Erreur d'import : {exc}", log, warnings)
