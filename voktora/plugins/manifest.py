"""
Voktora — plugins.manifest
Description d'un plugin (`plugin.json`) : lecture, validation, comparaison de versions.

Ce module n'importe rien d'autre de Voktora : l'outil `tools/plugin_tool.py` (CI du dépôt, contributeurs)
s'en sert pour valider une contribution SANS lancer l'application.

Exemple de `plugin.json` :
    {
      "id": "quick-notes",
      "name": "Quick Notes",
      "version": "1.0.0",
      "author": "yolezz",
      "description": "Un bloc-notes par projet.",
      "api": 2,
      "entry": "main.py",
      "permissions": ["ui", "projects.read"],
      "tags": ["notes"],
      "homepage": "https://github.com/yo-le-zz/Voktora"
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

API_VERSION = 3                       # version de l'API de plugins fournie par cette version de Voktora
MANIFEST_NAME = "plugin.json"

# Permissions déclarables. Elles sont affichées avant l'installation et vérifiées par l'API.
PERMISSIONS: dict[str, str] = {
    "ui":            "Modifier l'interface (menus, onglets, boutons, styles)",
    "projects.read": "Lire la liste et les informations de vos projets",
    "files":         "Lire des fichiers dans vos projets",
    "network":       "Accéder à Internet",
    "shell":         "Lancer des programmes sur votre ordinateur",
    # API 3 (Voktora 1.0.8)
    "config.read":   "Lire les réglages de Voktora (jamais les jetons ni mots de passe)",
    "config.write":  "Modifier les réglages de Voktora (confirmation à chaque changement)",
    "quick_actions": "Lire, ajouter et supprimer des actions rapides (l'ajout est confirmé)",
    "snapshots":     "Lister et créer des snapshots de vos projets",
    "diskusage":     "Mesurer l'espace disque de vos projets",
    "forges":        "Voir les forges, dépôts et forks de vos projets (sans jetons)",
    "sync":          "Voir et lancer la synchronisation entre PC",
    "plugins.manage": "Lister les plugins et les activer/désactiver (confirmé)",
    "security":      "Lire l'état de sécurité (coffre, plugins, révocations, synchro) et auditer du code",
    "vault":         "Verrouiller le coffre et garder des secrets propres au plugin dans le coffre",
}

ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
ENTRY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,80}\.py$")

MAX_NAME = 60
MAX_DESCRIPTION = 400


class ManifestError(ValueError):
    """Manifeste absent ou invalide (le message dit quoi corriger)."""


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    author: str
    description: str = ""
    api: int = API_VERSION
    entry: str = "main.py"
    permissions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    homepage: str = ""
    min_voktora: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "version": self.version, "author": self.author,
            "description": self.description, "api": self.api, "entry": self.entry,
            "permissions": list(self.permissions), "tags": list(self.tags),
            "homepage": self.homepage, "min_voktora": self.min_voktora,
        }


def version_tuple(version: str) -> tuple[int, int, int]:
    """'1.2.3-beta' -> (1, 2, 3). Tout ce qui n'est pas numérique est ignoré."""
    parts = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(version or ""))
    if not parts:
        return (0, 0, 0)
    return tuple(int(p or 0) for p in parts.groups())   # type: ignore[return-value]


def is_newer(candidate: str, installed: str) -> bool:
    return version_tuple(candidate) > version_tuple(installed)


def _text(data: dict, key: str, required: bool, limit: int, errors: list[str]) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        errors.append(f"« {key} » doit être une chaîne de caractères.")
        return ""
    value = value.strip()
    if required and not value:
        errors.append(f"« {key} » est obligatoire.")
    if len(value) > limit:
        errors.append(f"« {key} » est trop long ({len(value)} > {limit} caractères).")
    return value


def validate(data: object) -> tuple[Manifest | None, list[str]]:
    """Retourne (manifeste, erreurs). Le manifeste est None si une erreur bloque."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return None, ["Le manifeste doit être un objet JSON."]

    plugin_id = _text(data, "id", True, 40, errors)
    if plugin_id and not ID_RE.match(plugin_id):
        errors.append("« id » : minuscules, chiffres et tirets uniquement (2 à 40 caractères, ex. « quick-notes »).")
    name = _text(data, "name", True, MAX_NAME, errors)
    version = _text(data, "version", True, 30, errors)
    if version and not VERSION_RE.match(version):
        errors.append("« version » doit suivre le format MAJEUR.MINEUR.CORRECTIF (ex. 1.0.0).")
    author = _text(data, "author", True, 60, errors)
    description = _text(data, "description", False, MAX_DESCRIPTION, errors)
    homepage = _text(data, "homepage", False, 200, errors)
    if homepage and not homepage.startswith("https://"):
        errors.append("« homepage » doit commencer par https://.")
    min_voktora = _text(data, "min_voktora", False, 30, errors)

    api = data.get("api", API_VERSION)
    if not isinstance(api, int) or isinstance(api, bool) or api < 1:
        errors.append("« api » doit être un entier (version de l'API de plugins visée).")
        api = API_VERSION
    elif api > API_VERSION:
        errors.append(f"Ce plugin vise l'API {api}, cette version de Voktora fournit l'API {API_VERSION}.")

    entry = data.get("entry", "main.py")
    if not isinstance(entry, str) or not ENTRY_RE.match(entry) or ".." in entry.split("/"):
        errors.append("« entry » doit être un fichier .py relatif au dossier du plugin (ex. « main.py »).")
        entry = "main.py"

    permissions = data.get("permissions", [])
    if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
        errors.append("« permissions » doit être une liste de chaînes.")
        permissions = []
    unknown = sorted(set(permissions) - set(PERMISSIONS))
    if unknown:
        errors.append(f"Permission(s) inconnue(s) : {', '.join(unknown)}. Valeurs possibles : {', '.join(PERMISSIONS)}.")

    tags = data.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) and len(t) <= 24 for t in tags) or len(tags) > 8:
        errors.append("« tags » : liste de 8 mots-clés maximum (24 caractères chacun).")
        tags = []

    if errors:
        return None, errors
    return Manifest(
        id=plugin_id, name=name, version=version, author=author, description=description,
        api=api, entry=entry, permissions=sorted(set(permissions)), tags=list(tags),
        homepage=homepage, min_voktora=min_voktora,
    ), []


def load(folder: Path) -> Manifest:
    """Lit et valide `<folder>/plugin.json`. Lève ManifestError."""
    path = folder / MANIFEST_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"{MANIFEST_NAME} introuvable dans {folder.name} ({exc.strerror or exc}).") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{MANIFEST_NAME} : JSON invalide ({exc}).") from exc
    manifest, errors = validate(data)
    if manifest is None:
        raise ManifestError(" ".join(errors))
    if not (folder / manifest.entry).is_file():
        raise ManifestError(f"Fichier d'entrée « {manifest.entry} » introuvable.")
    return manifest
