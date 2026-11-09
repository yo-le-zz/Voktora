"""
Voktora — forges.accounts
Comptes de forge (GitLab, Forgejo/Fedora, GitHub Enterprise…) enregistrés dans la configuration. Le compte
GitHub principal reste géré par `core.github_auth` (OAuth / GitHub App) et apparaît dans le hub comme les autres.
Les jetons vont dans le coffre (Fernet) lorsqu'il est déverrouillé ; sinon ils sont conservés dans la
configuration, comme le fait déjà le compte GitHub — et ne sont JAMAIS synchronisés entre PC ni écrits dans un remote.
"""

from __future__ import annotations

import re
import uuid

import core

from .base import PRESETS, ForgeError, guess_kind
from .clients import make_client

KEY = "forge_accounts"
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")


def clean_host(host: str) -> str:
    host = (host or "").strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    if not _HOST_RE.match(host) or "." not in host and host != "localhost":
        raise ForgeError(f"Adresse de forge invalide : « {host} »")
    return host


def _store():
    return core.config_store


def list_accounts() -> list[dict]:
    """Comptes sans leur jeton : {id, kind, host, label, login, name}."""
    cfg = _store()._load_config()
    return [{k: v for k, v in acc.items() if k not in ("token", "token_encrypted")} for acc in cfg.get(KEY, [])]


def get_token(account_id: str) -> str:
    cfg = _store()._load_config()
    acc = next((a for a in cfg.get(KEY, []) if a.get("id") == account_id), None)
    if not acc:
        return ""
    if acc.get("token_encrypted") == "__vault__":
        try:
            return core.vault_retrieve(f"forge_token:{account_id}") if core.vault_is_unlocked() else ""
        except Exception:  # noqa: BLE001
            return ""
    return acc.get("token", "")


def add_account(kind: str, host: str, token: str, label: str = "") -> dict:
    """Vérifie le jeton auprès de la forge (une requête `user`), puis enregistre le compte."""
    host = clean_host(host)
    kind = kind or guess_kind(host)
    if not token.strip():
        raise ForgeError("Jeton d'accès requis (créez un jeton personnel sur la forge, droit de lecture des dépôts).")
    me = make_client(kind, host, token.strip()).user()
    cfg = _store()._load_config()
    accounts = [a for a in cfg.get(KEY, []) if not (a.get("host") == host and a.get("login") == me["login"])]
    entry = {"id": uuid.uuid4().hex[:12], "kind": kind, "host": host,
             "label": label or next((n for n, k, h in PRESETS if h == host and k == kind), host),
             "login": me["login"], "name": me["name"]}
    if core.vault_is_unlocked():
        core.vault_store(f"forge_token:{entry['id']}", token.strip(), domain="forge_token")
        entry["token_encrypted"] = "__vault__"
    else:
        entry["token"] = token.strip()
    accounts.append(entry)
    cfg[KEY] = accounts
    _store()._save_config(cfg)
    return {k: v for k, v in entry.items() if k not in ("token", "token_encrypted")}


def remove_account(account_id: str) -> None:
    cfg = _store()._load_config()
    cfg[KEY] = [a for a in cfg.get(KEY, []) if a.get("id") != account_id]
    _store()._save_config(cfg)
    try:
        core.vault_delete(f"forge_token:{account_id}")
    except Exception:  # noqa: BLE001
        pass


def rename_account(account_id: str, label: str) -> str:
    """Change le nom affiché d'un compte de forge (le login ne change pas)."""
    cfg = _store()._load_config()
    acc = next((a for a in cfg.get(KEY, []) if a.get("id") == account_id), None)
    if not acc:
        raise ForgeError("Compte de forge introuvable.")
    acc["label"] = " ".join((label or "").split())[:80] or acc.get("login", "") or acc.get("label", "")
    _store()._save_config(cfg)
    return acc["label"]


def client_for(account_id: str):
    acc = next((a for a in list_accounts() if a["id"] == account_id), None)
    if not acc:
        raise ForgeError("Compte de forge introuvable.")
    token = get_token(account_id)
    if not token:
        raise ForgeError("Jeton indisponible sur ce PC : reconnectez ce compte (les jetons ne sont jamais synchronisés) ou déverrouillez le coffre.")
    return make_client(acc["kind"], acc["host"], token)


def account_for_host(host: str) -> dict | None:
    return next((a for a in list_accounts() if a["host"] == host.lower()), None)
