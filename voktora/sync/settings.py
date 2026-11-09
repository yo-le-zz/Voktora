"""
Voktora — sync.settings
Réglages de la synchronisation (fichier `<données>/sync/settings.json`, permissions 0600 : il contient les
secrets d'appairage — ils ne sont JAMAIS écrits dans config.json ni synchronisés).
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import tempfile
import uuid
from pathlib import Path

from . import net

DEFAULT_PORT = 47821
POLICIES = ("ask", "primary", "smart")        # divergence au premier échange : demander / le principal gagne / fusion
CATEGORIES = {
    "config": "Réglages de l'application (thème, interface…)",
    "quick_actions": "Actions rapides",
    "categories": "Catégories et statuts personnalisés",
    "projects_meta": "Informations des projets (catégorie, statut, notes, icône…)",
    "project_files": "Fichiers des projets",
    "plugin_settings": "Réglages des plugins",
    "ai_providers": "Fournisseurs IA et permissions de l'assistant (SANS les clés d'API)",
    "accounts": "Comptes GitHub / forges : identité et nom affiché (jamais les jetons)",
    "themes": "Thèmes personnalisés",
    "profiles": "Profils de projets",
}
DEFAULTS: dict = {
    "enabled": False,
    "device_id": "",
    "device_name": "",
    "role": "secondary",                # "primary" | "secondary"
    "primary_id": "",                   # identifiant du PC principal (priorité en cas de conflit)
    "port": DEFAULT_PORT,
    "port_auto": True,                  # port occupé → on en prend un libre tout seul (les pairs le retrouvent)
    "auto": True,                       # synchroniser tout seul quand un pair est sur le même réseau
    "interval": 30,                     # secondes entre deux recherches de pair
    "policy": "ask",
    "categories": dict.fromkeys(CATEGORIES, True),
    "include_git": True,                # synchroniser .git (traité comme un bloc : le principal gagne)
    "include_regenerable": False,       # node_modules, target, caches… (inutile et lourd)
    "max_file_mb": 200,
    "exclude": ["*.tmp", "*.swp", "*.log", ".DS_Store", "Thumbs.db", "_market_cache.json", "_revoked.json"],
    "only_projects": [],                # vide = tous ; sinon liste de noms de projets
    "propagate_deletes": True,          # supprimer aussi chez l'autre (corbeille récupérable 30 jours)
    "peers": [],                        # [{"id","name","host","port","secret"(base64)}]
    "invites": [],                      # [{"secret","expires"}] codes d'appairage en attente
    "log_enabled": True,                # journal de synchronisation (désactivable : plus léger)
    "log_level": "normal",              # "quiet" (essentiel) | "normal" (par projet) | "detailed" (par fichier)
    "performance": "auto",
    "quick_check": True,
    "full_check_hours": 12,              # "auto" | "eco" (PC peu puissant) | "normal" | "fast"
}
SECRET_KEYS = {"peers", "invites"}


class SyncSettings:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "settings.json"
        self.data: dict = copy.deepcopy(DEFAULTS)
        self.load()

    # ── performances ─────────────────────────────────────────────────────────

    def performance_profile(self) -> dict:
        """Réglages de charge : analyses en parallèle, pause entre blocs lus, priorité système, rythme de l'interface.
        « auto » s'adapte au nombre de cœurs (PC modeste → mode économe)."""
        mode = self["performance"]
        if mode not in ("eco", "normal", "fast"):
            cores = os.cpu_count() or 2
            mode = "eco" if cores <= 2 else "normal" if cores <= 6 else "fast"
        return {"eco": {"mode": "eco", "scans": 1, "pause": 0.004, "nice": 12, "ui_ms": 800},
                "normal": {"mode": "normal", "scans": 2, "pause": 0.0008, "nice": 6, "ui_ms": 400},
                "fast": {"mode": "fast", "scans": 4, "pause": 0.0, "nice": 0, "ui_ms": 250}}[mode]

    # ── persistance ──────────────────────────────────────────────────────────

    def load(self) -> None:
        loaded: dict = {}
        with contextlib.suppress(OSError, json.JSONDecodeError):
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            loaded = raw if isinstance(raw, dict) else {}
        data = copy.deepcopy(DEFAULTS)
        for key, value in loaded.items():
            if key in data:
                data[key] = {**data[key], **value} if isinstance(data[key], dict) and isinstance(value, dict) else value
        if not data["device_id"]:
            data["device_id"] = uuid.uuid4().hex
            data["device_name"] = data["device_name"] or net.default_hostname()
            data["primary_id"] = data["primary_id"] or data["device_id"]
            data["role"] = "primary" if data["primary_id"] == data["device_id"] else "secondary"
            self.data = data
            self.save()
        self.data = data

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def __getitem__(self, key: str):
        return self.data[key]

    def __setitem__(self, key: str, value) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        self.data[key] = value

    # ── confort ──────────────────────────────────────────────────────────────

    @property
    def device_id(self) -> str:
        return self.data["device_id"]

    @property
    def is_primary(self) -> bool:
        return self.data["primary_id"] == self.device_id

    def set_primary(self, device_id: str) -> None:
        self.data["primary_id"] = device_id
        self.data["role"] = "primary" if device_id == self.device_id else "secondary"

    def fingerprint(self) -> str:
        """Empreinte des réglages qui changent CE qui est synchronisé (vérification rapide invalidée s'ils changent)."""
        import hashlib
        import json
        keys = ("categories", "exclude", "only_projects", "max_file_mb", "include_git", "include_regenerable", "primary_id")
        return hashlib.sha1(json.dumps({k: self.data.get(k) for k in keys}, sort_keys=True).encode()).hexdigest()

    def category(self, name: str) -> bool:
        return bool(self.data["categories"].get(name, False))

    def peer(self, device_id: str) -> dict | None:
        return next((p for p in self.data["peers"] if p["id"] == device_id), None)

    def add_peer(self, device_id: str, name: str, host: str, port: int, secret: bytes) -> dict:
        import base64
        entry = {"id": device_id, "name": name or host, "host": host, "port": int(port),
                 "secret": base64.urlsafe_b64encode(secret).decode()}
        self.data["peers"] = [p for p in self.data["peers"] if p["id"] != device_id] + [entry]
        return entry

    def remove_peer(self, device_id: str) -> None:
        self.data["peers"] = [p for p in self.data["peers"] if p["id"] != device_id]
        if self.data["primary_id"] == device_id:
            self.set_primary(self.device_id)

    @staticmethod
    def peer_secret(peer: dict) -> bytes:
        import base64
        return base64.urlsafe_b64decode(peer["secret"])

    def excluded(self, rel: str) -> bool:
        import fnmatch
        name = rel.rsplit("/", 1)[-1]
        return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p) for p in self.data["exclude"])

    def project_selected(self, name: str) -> bool:
        only = self.data["only_projects"]
        return not only or name in only
