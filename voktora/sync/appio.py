"""
Voktora — sync.appio
Pont entre la synchronisation et la configuration réelle de l'application (config.json) + instance partagée.
"""

from __future__ import annotations

import copy
import threading
from pathlib import Path

import core

_service = None
_lock = threading.Lock()


class AppConfigIO:
    """Implémente `store.ConfigIO` au-dessus de `core`."""

    def load(self) -> dict:
        return copy.deepcopy(core._load_config())

    def save(self, cfg: dict) -> None:
        # on ne remplace pas la config entière : seules les clés que la synchro gère sont reprises, le reste
        # (compte GitHub, coffre, schéma…) reste exactement ce qu'il est sur ce PC.
        current = core._load_config()
        for key in ("categories", "custom_statuses", "projects"):
            if key in cfg:
                current[key] = copy.deepcopy(cfg[key])
        if isinstance(cfg.get("app_config"), dict):
            current.setdefault("app_config", {}).update(copy.deepcopy(cfg["app_config"]))
            for stale in [k for k in current["app_config"] if k not in cfg["app_config"]
                          and k not in _KEEP_LOCAL]:
                current["app_config"].pop(stale)
        core._save_config(current)

    def projects_root(self) -> Path:
        root = core.get_projects_root()
        root.mkdir(parents=True, exist_ok=True)
        return root


# Réglages locaux : jamais supprimés par une synchronisation (voir store.APP_CONFIG_LOCAL_ONLY).
_KEEP_LOCAL = {"window_geometry", "splitter_states", "github_client_id", "auth_method"}


def get_service():
    """Instance unique du service de synchronisation de l'application."""
    global _service
    with _lock:
        if _service is None:
            from .service import SyncService
            plugin_data = core.get_data_dir() / "plugins_data"
            plugin_data.mkdir(parents=True, exist_ok=True)
            _service = SyncService(core.get_data_dir(), AppConfigIO(), {"plugin_settings": plugin_data})
        return _service


def reset_service_for_tests() -> None:
    global _service
    with _lock:
        if _service is not None:
            _service.stop()
        _service = None
