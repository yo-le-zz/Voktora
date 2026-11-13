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
      "homepage": "https://github.com/yo-le-zz/Voktora",
      "lang": "python",                       # ou "js" / "rust"
      "requires": ["rich>=13"],               # bibliothèques PyPI propres au plugin (dossier libs/ dédié)
      "dependencies": {"api-plus": ">=1.0.0"} # autres plugins nécessaires
    }
    « permissions »: "auto" détecte les permissions depuis le code (plugins locaux ; le marketplace exige la liste).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

API_VERSION = 5                       # version de l'API de plugins fournie par cette version de Voktora
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
    # API 4 (Voktora 1.1.0)
    "fleet":         "Voir l'état Git de tous vos projets et chercher dans leurs fichiers",
    "projects.write": "Modifier les informations d'un projet (description, catégorie, statut… ; confirmé)",
    "ai":            "Envoyer une question au fournisseur IA configuré (confirmé à chaque appel)",
    # API 5 (Voktora 1.1.1)
    "files.write":   "Écrire des fichiers dans vos projets (confirmé à chaque écriture)",
    "libs":          "Installer des bibliothèques Python externes (PyPI) réservées à ce plugin",
    "native":        "Exécuter du code natif (Rust) : AUCUN bac à sable, mêmes droits que Voktora",
    "system":        "Lire l'état de l'ordinateur (processeur, mémoire, disques, processus)",
    "clipboard":     "Lire et écrire le presse-papiers",
    "ai.tools":      "Ajouter des outils à l'assistant IA (chaque appel reste soumis à ses permissions)",
}

LANGS = ("python", "js", "rust")
AUTO = "auto"                           # « permissions": "auto » : détectées depuis le code (plugins locaux)

ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
ENTRY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,80}\.(py|js|mjs)$")
REQUIRES_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}(\[[A-Za-z0-9,._-]{1,40}\])?"
                         r"((==|>=|<=|~=|!=|>|<)[0-9A-Za-z.*+!-]{1,24}(,(==|>=|<=|~=|!=|>|<)[0-9A-Za-z.*+!-]{1,24})*)?$")
RANGE_RE = re.compile(r"^(\*|(>=|<=|==|>|<|\^|~)?\s*\d+(\.\d+){0,2})(\s*,\s*(>=|<=|==|>|<)\s*\d+(\.\d+){0,2})*$")
RUST_ENTRY = "Cargo.toml"

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
    lang: str = "python"
    requires: list[str] = field(default_factory=list)          # bibliothèques PyPI propres au plugin
    dependencies: dict[str, str] = field(default_factory=dict)  # autres plugins : {id: « >=1.0.0 »}
    auto_permissions: bool = False                              # permissions détectées depuis le code

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "version": self.version, "author": self.author,
            "description": self.description, "api": self.api, "entry": self.entry,
            "permissions": list(self.permissions), "tags": list(self.tags),
            "homepage": self.homepage, "min_voktora": self.min_voktora, "lang": self.lang,
            "requires": list(self.requires), "dependencies": dict(self.dependencies),
        }


def version_tuple(version: str) -> tuple[int, int, int]:
    """'1.2.3-beta' -> (1, 2, 3). Tout ce qui n'est pas numérique est ignoré."""
    parts = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(version or ""))
    if not parts:
        return (0, 0, 0)
    return tuple(int(p or 0) for p in parts.groups())   # type: ignore[return-value]


def satisfies(version: str, spec: str) -> bool:
    """`version` respecte-t-elle `spec` ? « * », « 1.2 », « >=1.0.0 », « ^1.2.0 », « ~1.2 », « >=1,<2 »."""
    spec = (spec or "*").strip()
    if spec in ("", "*"):
        return True
    have = version_tuple(version)
    for part in (p.strip() for p in spec.split(",")):
        match = re.match(r"^(>=|<=|==|>|<|\^|~)?\s*(\d+(?:\.\d+){0,2})$", part)
        if not match:
            return False
        op, number = match.group(1) or "==", match.group(2)
        want = version_tuple(number)
        size = number.count(".") + 1
        if op == "^":
            upper = (want[0] + 1, 0, 0) if want[0] else (0, want[1] + 1, 0) if want[1] else (0, 0, want[2] + 1)
            ok = want <= have < upper
        elif op == "~":
            upper = (want[0], want[1] + 1, 0) if size >= 2 else (want[0] + 1, 0, 0)
            ok = want <= have < upper
        elif op == "==":
            ok = have[:size] == want[:size]
        else:
            ok = {">=": have >= want, "<=": have <= want, ">": have > want, "<": have < want}[op]
        if not ok:
            return False
    return True


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

    lang = data.get("lang", "python")
    if lang not in LANGS:
        errors.append(f"« lang » doit valoir : {', '.join(LANGS)}.")
        lang = "python"
    default_entry = {"python": "main.py", "js": "main.js", "rust": RUST_ENTRY}[lang]
    entry = data.get("entry", default_entry)
    if lang == "rust":
        if entry != RUST_ENTRY:
            errors.append(f"Un plugin Rust a pour « entry » {RUST_ENTRY!r}.")
    elif not isinstance(entry, str) or not ENTRY_RE.match(entry) or ".." in entry.split("/"):
        errors.append("« entry » doit être un fichier .py/.js relatif au dossier du plugin (ex. « main.py »).")
        entry = default_entry
    elif entry.endswith(".py") != (lang == "python"):
        errors.append(f"« entry » ({entry}) ne correspond pas à « lang » ({lang}).")

    auto = data.get("permissions") == AUTO
    permissions = [] if auto else data.get("permissions", [])
    if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
        errors.append("« permissions » doit être une liste de chaînes (ou \"auto\").")
        permissions = []

    requires = data.get("requires", [])
    if not isinstance(requires, list) or len(requires) > 30 or not all(
            isinstance(r, str) and REQUIRES_RE.match(r.strip()) for r in requires):
        errors.append("« requires » : liste de bibliothèques PyPI (« nom », « nom==1.2.3 », « nom>=2,<3 »), 30 au plus.")
        requires = []
    dependencies = data.get("dependencies", {})
    if not isinstance(dependencies, dict) or len(dependencies) > 20 or not all(
            isinstance(k, str) and ID_RE.match(k) and isinstance(v, str) and RANGE_RE.match(v.strip())
            for k, v in dependencies.items()):
        errors.append("« dependencies » : objet {\"id-du-plugin\": \">=1.0.0\"} (20 au plus).")
        dependencies = {}
    if plugin_id in dependencies:
        errors.append("Un plugin ne peut pas dépendre de lui-même.")
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
        homepage=homepage, min_voktora=min_voktora, lang=lang,
        requires=[r.strip() for r in requires], dependencies={k: v.strip() for k, v in dependencies.items()},
        auto_permissions=auto,
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
