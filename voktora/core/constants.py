"""
Voktora — core.constants
Fragment de core.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

from . import config_store

"""
Voktora — Project Instance Manager
Voktora v1.0.2
core.py : Logique métier — config, instances, intents, Git, chiffrement AES-256 (Fernet+PBKDF2), auth GitHub
Version : 1.0.2  —  Windows + Linux compatible
"""


# ──────────────────────────────────────────────
# CONSTANTES
# ──────────────────────────────────────────────

APP_NAME              = "Voktora"
APP_VERSION           = "1.0.2"
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

CONFIG_SCHEMA_VERSION = 8

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
    cfg = config_store._load_config()
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



# ──────────────────────────────────────────────
# CHEMIN DE L'APPLICATION (Nuitka + dev)
# ──────────────────────────────────────────────

class ConfigCorruptedError(RuntimeError):
    """Levée quand config.json est illisible ou structurellement invalide."""


class OAuthError(RuntimeError):
    """Levée lors d'un échec du flux OAuth GitHub."""
