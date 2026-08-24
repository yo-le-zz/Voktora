"""
Voktora — mc.py
Migration multi-ordinateur : export/import de la configuration (instances,
intents, catégories, statuts personnalisés) sous forme de bundle portable
`.mpack` (zip), avec réécriture de chemins par règles de préfixe lors de
l'import.

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
_EXPORTED_KEYS = ("instances", "intents", "categories", "custom_statuses")


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
        payload = {key: cfg.get(key, [] if key in ("instances", "intents", "categories") else {})
                   for key in _EXPORTED_KEYS}
        n_projects = len(payload["instances"]) + len(payload["intents"])

        manifest = {
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

    manifest["_detected_project_count"] = len(payload.get("instances", [])) + len(payload.get("intents", []))
    manifest["_bundle_size_kb"] = round(path.stat().st_size / 1024, 1)
    return {"valid": True, "error": "", "manifest": manifest}


def import_bundle(
    src: Path,
    base: Path,
    custom_rules: list[tuple[str, str]],
    on_progress: Callable[[str, int], None] | None = None,
) -> MigrationResult:
    """Importe un bundle .mpack : remplace instances/intents locaux par ceux
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

        new_instances = []
        for entry in payload.get("instances", []):
            entry = dict(entry)
            old_path = entry.get("path", "")
            entry["path"] = rewrite(old_path)
            new_instances.append(entry)
            log.append(f"Instance « {entry.get('name', '?')} » → {entry['path']}")

        new_intents = []
        for entry in payload.get("intents", []):
            entry = dict(entry)
            old_path = entry.get("path", "")
            entry["path"] = rewrite(old_path)
            new_intents.append(entry)
            log.append(f"Intent « {entry.get('name', '?')} » → {entry['path']}")

        progress("Écriture de la configuration…", 80)
        cfg = core._load_config()
        cfg["instances"] = new_instances
        cfg["intents"] = new_intents
        if payload.get("categories"):
            cfg["categories"] = payload["categories"]
        if payload.get("custom_statuses"):
            cfg["custom_statuses"] = payload["custom_statuses"]
        core._save_config(cfg)

        n = len(new_instances) + len(new_intents)
        progress("Terminé", 100)
        warnings.append(
            "Les chemins sans règle de correspondance ont été replacés sous "
            f"« {base} » : vérifiez qu'ils pointent vers les bons dossiers."
        )
        return MigrationResult(True, f"Import terminé : {n} projet(s) importé(s).", log, warnings)

    except (zipfile.BadZipFile, json.JSONDecodeError, OSError) as exc:
        return MigrationResult(False, f"Erreur d'import : {exc}", log, warnings)
