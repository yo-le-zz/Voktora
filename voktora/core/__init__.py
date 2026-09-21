"""
Voktora — core (package)
Version : 1.0.2

Anciennement un unique fichier core.py (2533 lignes). Découpé en modules
par domaine pour être plus lisible et plus facile à maintenir :

  constants.py    — constantes globales, statuts de projet, exceptions
  paths.py        — dossiers de l'application, validation de nom
  config_store.py — lecture/écriture/migration de config.json
  drives.py       — disques disponibles, racines Instances/Intents
  crypto.py       — chiffrement AES-256 (Fernet+PBKDF2), vault
  github_auth.py  — OAuth device flow, GitHub App, sessions
  projects.py     — CRUD instances/intents, transfert, archives
  git_ops.py      — opérations Git (clone, push, pull, branches...)
  system.py       — lancement d'applications externes, mises à jour
  diagnostics.py  — health-check, réparation, désinstallation

Ce fichier __init__.py ne fait AUCUN ré-export statique par nom : il
délègue dynamiquement (`__getattr__`, PEP 562) vers le sous-module qui
définit réellement chaque nom. C'est nécessaire car plusieurs fonctions
partagent un état mutable au niveau module (ex. `_config_cache` dans
config_store, `_GITHUB_SESSION` dans github_auth) : un ré-export statique
("from .config_store import _config_cache") figerait une copie de la
valeur au moment de l'import, qui se désynchroniserait dès que le
sous-module réassigne sa propre globale. La délégation dynamique garantit
que `core.X` reflète toujours l'état réel du sous-module propriétaire —
y compris pour les tests qui patchent directement `core.config_store.X`.

Tout le code existant (`import core`, puis `core.get_data_dir()`,
`core._load_config()`, `core.APP_VERSION`, etc.) continue de fonctionner
sans aucune modification.
"""

from __future__ import annotations

from . import (
    config_store,
    constants,
    crypto,
    diagnostics,
    drives,
    git_ops,
    github_auth,
    paths,
    projects,
    system,
)

_SUBMODULES = (
    constants,   # en premier : erreurs et constantes n'ont jamais de collision
    paths,
    config_store,
    drives,
    crypto,
    projects,
    git_ops,
    github_auth,
    system,
    diagnostics,
)


def __getattr__(name: str):
    for module in _SUBMODULES:
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module 'core' has no attribute {name!r}")


def __dir__() -> list[str]:
    names = set(globals())
    for module in _SUBMODULES:
        names.update(n for n in dir(module) if not n.startswith("__"))
    return sorted(names)
