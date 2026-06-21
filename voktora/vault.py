"""
vault.py — Vault sécurisé Voktora
Version : 1.0.1
Stockage chiffré de secrets : tokens GitHub, clés SSH, API keys, .env, etc.
Toutes les clés sont dérivées du master password via PBKDF2 (core.vault_*).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import core

SecretKind = Literal["github_token", "ssh_key", "api_key", "env_secret", "general"]

DOMAIN_MAP: dict[SecretKind, str] = {
    "github_token": "github_token",
    "ssh_key":      "ssh_key",
    "api_key":      "api_key",
    "env_secret":   "env_secret",
    "general":      "general",
}


@dataclass
class VaultEntry:
    key:    str
    kind:   SecretKind
    label:  str = ""
    note:   str = ""


# ── API publique ──────────────────────────────────────────────────────────────

def store(key: str, value: str, kind: SecretKind = "general",
          label: str = "", note: str = "") -> None:
    """Stocke un secret chiffré. Écrase si la clé existe déjà."""
    if not core.vault_is_unlocked():
        raise PermissionError("Vault verrouillé.")
    domain = DOMAIN_MAP[kind]
    core.vault_store(key, value, domain)
    # Métadonnées (non chiffrées)
    import json
    from pathlib import Path
    meta_path = _meta_path()
    meta = _load_meta()
    meta[key] = {"kind": kind, "label": label or key, "note": note}
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def retrieve(key: str) -> str:
    """Récupère et déchiffre un secret. Retourne "" si absent ou vault verrouillé."""
    if not core.vault_is_unlocked():
        return ""
    return core.vault_retrieve(key)


def delete(key: str) -> None:
    core.vault_delete(key)
    meta = _load_meta()
    meta.pop(key, None)
    _meta_path().write_text(
        __import__("json").dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_entries() -> list[VaultEntry]:
    meta = _load_meta()
    keys = core.vault_list_keys()
    entries = []
    for k in keys:
        m = meta.get(k, {})
        entries.append(VaultEntry(
            key=k,
            kind=m.get("kind", "general"),
            label=m.get("label", k),
            note=m.get("note", ""),
        ))
    return entries


def exists(key: str) -> bool:
    return key in core.vault_list_keys()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _meta_path():
    return core.get_data_dir() / "vault_meta.json"


def _load_meta() -> dict:
    p = _meta_path()
    if not p.exists():
        return {}
    try:
        return __import__("json").loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
