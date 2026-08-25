"""
Voktora — core.github_auth
Fragment de core.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import config_store, constants, crypto, projects

_GITHUB_SESSION: dict | None = None

# ──────────────────────────────────────────────
# OAUTH GITHUB — Device Flow
# ──────────────────────────────────────────────

@dataclass
class DeviceFlowPending:
    device_code:      str
    user_code:        str
    verification_uri: str
    expires_in:       int
    interval:         int


def get_github_client_id() -> str:
    cfg = config_store._load_config()
    return cfg.get("app_config", {}).get("github_client_id", "") or constants.GITHUB_CLIENT_ID


def set_github_client_id(client_id: str) -> None:
    cfg = config_store._load_config()
    cfg.setdefault("app_config", {})["github_client_id"] = client_id
    config_store._save_config(cfg)


def is_github_client_id_configured() -> bool:
    return bool(get_github_client_id())


# ──────────────────────────────────────────────────────────────────────────────
# AUTH METHOD
# ──────────────────────────────────────────────────────────────────────────────

def get_auth_method() -> str:
    """Retourne 'oauth' ou 'github_app'."""
    return config_store._load_config().get("app_config", {}).get("auth_method", constants.AUTH_METHOD_OAUTH)


def set_auth_method(method: str) -> None:
    cfg = config_store._load_config()
    cfg.setdefault("app_config", {})["auth_method"] = method
    config_store._save_config(cfg)


def is_using_github_app() -> bool:
    return get_auth_method() == constants.AUTH_METHOD_GITHUB_APP


# ──────────────────────────────────────────────────────────────────────────────
# GITHUB APP — Configuration
# ──────────────────────────────────────────────────────────────────────────────

def get_github_app_config() -> dict:
    """
    Retourne {app_id, private_key, installation_id} depuis la config chiffrée.
    private_key peut être chiffré (crypto.token_encrypt) si token_protected=True.
    """
    cfg = config_store._load_config()
    acct = cfg.get("github_account", {})
    return {
        "app_id":          acct.get("github_app_id", ""),
        "private_key":     acct.get("github_app_private_key", ""),
        "installation_id": acct.get("github_app_installation_id", ""),
    }


def set_github_app_config(app_id: str, private_key_pem: str,
                           installation_id: str, password: str = "") -> None:
    """
    Sauvegarde la config GitHub App.
    La clé privée est optionnellement chiffrée avec crypto.token_encrypt.
    """
    cfg = config_store._load_config()
    acct = cfg.setdefault("github_account", {})

    if password:
        stored_key = crypto.token_encrypt(private_key_pem, password)
        acct["token_protected"] = True
    else:
        stored_key = private_key_pem
        acct["token_protected"] = False

    acct["github_app_id"]              = app_id
    acct["github_app_private_key"]     = stored_key
    acct["github_app_installation_id"] = installation_id
    # Invalider le cache de token
    acct["github_app_token_cache"]      = ""
    acct["github_app_token_expires_at"] = 0.0
    # Méthode d'auth
    cfg.setdefault("app_config", {})["auth_method"] = constants.AUTH_METHOD_GITHUB_APP
    config_store._save_config(cfg)


def clear_github_app_config() -> None:
    cfg = config_store._load_config()
    acct = cfg.setdefault("github_account", {})
    for key in ("github_app_id", "github_app_private_key",
                "github_app_installation_id", "github_app_token_cache",
                "github_app_token_expires_at"):
        acct[key] = "" if isinstance(acct.get(key), str) else 0.0
    cfg.setdefault("app_config", {})["auth_method"] = constants.AUTH_METHOD_OAUTH
    config_store._save_config(cfg)


def get_github_app_installation_id() -> str:
    return config_store._load_config().get("github_account", {}).get("github_app_installation_id", "")


def is_github_app_configured() -> bool:
    cfg = get_github_app_config()
    return bool(cfg["app_id"] and cfg["private_key"] and cfg["installation_id"])


# ──────────────────────────────────────────────────────────────────────────────
# GITHUB APP — JWT + Installation Token
# ──────────────────────────────────────────────────────────────────────────────

def _build_jwt(app_id: str, private_key_pem: str) -> str:
    """
    Génère un JWT signé RS256 valable 10 minutes.
    Utilise uniquement la stdlib + la clé PEM brute (via rsa/cryptography si dispo,
    sinon subprocess openssl comme fallback).
    """

    now = int(time.time())
    header  = {"alg": "RS256", "typ": "JWT"}
    payload = {"iat": now - 60, "exp": now + 540, "iss": app_id}

    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    msg = f"{h}.{p}".encode()

    # Essayer cryptography d'abord (disponible si PySide6 l'a tiré en dep)
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as _padding
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode(), password=None
        )
        sig = private_key.sign(msg, _padding.PKCS1v15(), hashes.SHA256())
        return f"{h}.{p}.{_b64url(sig)}"
    except ImportError:
        pass

    # Fallback : openssl CLI (présent partout où git est présent)
    import tempfile as _tmp
    with _tmp.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as kf:
        kf.write(private_key_pem)
        kf_path = kf.name
    try:
        import subprocess as _sp
        result = _sp.run(
            ["openssl", "dgst", "-sha256", "-sign", kf_path],
            input=msg, capture_output=True, check=True,
        )
        sig = result.stdout
        return f"{h}.{p}.{_b64url(sig)}"
    finally:
        try:
            Path(kf_path).unlink()
        except Exception:
            pass


def _get_installation_token_cached(app_id: str, private_key_pem: str,
                                    installation_id: str) -> str:
    """
    Retourne un installation token valide (durée max 1h).
    Met en cache dans la config pour éviter de recréer un JWT à chaque appel.
    """
    cfg  = config_store._load_config()
    acct = cfg.setdefault("github_account", {})

    cached     = acct.get("github_app_token_cache", "")
    expires_at = float(acct.get("github_app_token_expires_at", 0))

    # Valide si expire dans plus de 5 min
    if cached and time.time() < expires_at - 300:
        return cached

    # Générer nouveau JWT et demander un installation token
    jwt_token = _build_jwt(app_id, private_key_pem)

    url = constants.GITHUB_APP_TOKEN_URL.format(installation_id=installation_id)
    req = urllib.request.Request(
        url, data=b"{}",
        headers={
            "Authorization":        f"Bearer {jwt_token}",
            "Accept":               "application/vnd.github+json",
            "Content-Type":         "application/json",
            "User-Agent":           f"{constants.APP_NAME}/{constants.APP_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise constants.OAuthError(f"GitHub App token error ({e.code}): {body}") from e
    except Exception as exc:
        raise constants.OAuthError(f"Réseau : {exc}") from exc

    token      = data.get("token", "")
    expires_str = data.get("expires_at", "")  # ISO 8601

    # Parser la date d'expiration
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(expires_str)
        expires_ts = dt.timestamp()
    except Exception:
        expires_ts = time.time() + 3300  # fallback 55 min

    acct["github_app_token_cache"]      = token
    acct["github_app_token_expires_at"] = expires_ts
    config_store._save_config(cfg)

    return token


def get_github_app_token(password: str = "") -> str:
    """
    Retourne un installation token prêt à l'emploi.
    Déchiffre la clé privée si elle est protégée par mot de passe.
    """
    cfg_app = get_github_app_config()
    if not all([cfg_app["app_id"], cfg_app["private_key"], cfg_app["installation_id"]]):
        raise constants.OAuthError("GitHub App non configurée (app_id / clé privée / installation_id manquants).")

    raw_key = cfg_app["private_key"]
    cfg     = config_store._load_config()
    acct    = cfg.get("github_account", {})
    if acct.get("token_protected"):
        if not password:
            raise constants.OAuthError("Ce compte GitHub App est protégé par mot de passe.")
        raw_key = crypto.token_decrypt(raw_key, password)
        if not raw_key:
            raise constants.OAuthError("Mot de passe incorrect pour déchiffrer la clé privée.")

    return _get_installation_token_cached(
        cfg_app["app_id"], raw_key, cfg_app["installation_id"]
    )


def fetch_github_app_user(token: str) -> dict:
    """
    Avec un installation token on ne peut pas /user, on utilise /app/installations.
    Retourne un pseudo-profil avec le nom de l'app.
    """
    req = urllib.request.Request(
        constants.GITHUB_API_BASE + "/installation/repositories",
        headers={
            "Authorization":        f"Bearer {token}",
            "Accept":               "application/vnd.github+json",
            "User-Agent":           f"{constants.APP_NAME}/{constants.APP_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        repo_count = data.get("total_count", 0)
        return {
            "login":      "github-app",
            "name":       f"GitHub App ({repo_count} repos)",
            "avatar_url": "",
            "type":       "github_app",
        }
    except Exception:
        return {"login": "github-app", "name": "GitHub App", "avatar_url": "", "type": "github_app"}


def fetch_github_app_installations(app_id: str, private_key_pem: str) -> list[dict]:
    """
    Retourne la liste des installations de la GitHub App (compte perso + orgs).
    Chaque entrée : {"installation_id", "account_login", "account_type", "repos"}.
    Lève constants.OAuthError si l'App ID ou la clé privée sont incorrects.
    """
    jwt_token = _build_jwt(app_id, private_key_pem)
    req = urllib.request.Request(
        constants.GITHUB_APP_INSTALL_URL,
        headers={
            "Authorization":        f"Bearer {jwt_token}",
            "Accept":               "application/vnd.github+json",
            "User-Agent":           f"{constants.APP_NAME}/{constants.APP_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise constants.OAuthError(
            f"Erreur {e.code} lors du fetch des installations.\n"
            f"→ Vérifiez l'App ID et la clé privée.\nDétail: {body}"
        ) from e
    except Exception as exc:
        raise constants.OAuthError(f"Réseau : {exc}") from exc

    result = []
    for inst in (data if isinstance(data, list) else []):
        acct = inst.get("account", {})
        result.append({
            "installation_id": str(inst.get("id", "")),
            "account_login":   acct.get("login", "?"),
            "account_type":    acct.get("type", "?"),
            "repos":           inst.get("repositories_count", "?"),
        })
    return result


# ──────────────────────────────────────────────────────────────────────────────
# EFFECTIVE TOKEN — unifié OAuth + GitHub App
# ──────────────────────────────────────────────────────────────────────────────

def get_effective_token_unified(path: Path | None = None, password: str = "") -> str:
    """
    Retourne le meilleur token disponible selon la méthode d'auth configurée :
      1. Token spécifique à l'instance (priorité max)
      2. GitHub App installation token (si auth_method == github_app)
      3. OAuth token de session
    """
    # 1. Token par instance
    if path:
        tok = projects.get_instance_token(path)
        if tok:
            return tok

    # 2. GitHub App
    if is_using_github_app() and is_github_app_configured():
        try:
            return get_github_app_token(password)
        except constants.OAuthError:
            pass  # fallback OAuth si disponible

    # 3. OAuth session
    session = get_github_session()
    if session and session.get("token"):
        return session["token"]

    return ""


def load_github_app_session() -> bool:
    """
    Charge une session GitHub App depuis la config (si configurée).
    Équivalent de load_github_account_session() pour GitHub App.
    """
    global _GITHUB_SESSION
    if not is_github_app_configured():
        return False
    try:
        token     = get_github_app_token()
        user_info = fetch_github_app_user(token)
        _GITHUB_SESSION = {
            "login":      user_info.get("login", "github-app"),
            "name":       user_info.get("name", "GitHub App"),
            "token":      token,
            "avatar_url": "",
            "auth_type":  constants.AUTH_METHOD_GITHUB_APP,
        }
        return True
    except Exception:
        return False


def start_device_flow() -> DeviceFlowPending:
    client_id = get_github_client_id()
    if not client_id:
        raise constants.OAuthError("Aucun Client ID GitHub configuré.")
    data = urllib.parse.urlencode({"client_id": client_id, "scope": constants.GITHUB_SCOPES}).encode("ascii")
    req = urllib.request.Request(
        constants.GITHUB_DEVICE_AUTH_URL, data=data,
        headers={"Accept": "application/json",
                 "Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": f"{constants.APP_NAME}/{constants.APP_VERSION}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise constants.OAuthError(f"Impossible de démarrer l'authentification : {exc}") from exc
    if "error" in body:
        raise constants.OAuthError(f"GitHub a refusé la demande : {body.get('error_description', body['error'])}")
    return DeviceFlowPending(
        device_code=body["device_code"], user_code=body["user_code"],
        verification_uri=body["verification_uri"],
        expires_in=int(body.get("expires_in", 900)), interval=int(body.get("interval", 5)),
    )


def poll_device_flow(pending: DeviceFlowPending, on_success: Callable,
                     on_error: Callable, stop_event=None) -> None:
    deadline = time.monotonic() + pending.expires_in
    interval = pending.interval
    while time.monotonic() < deadline:
        if stop_event and stop_event.is_set():
            on_error("Authentification annulée.")
            return
        time.sleep(interval)
        data = urllib.parse.urlencode({
            "client_id": get_github_client_id(),
            "device_code": pending.device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }).encode("ascii")
        req = urllib.request.Request(
            constants.GITHUB_TOKEN_URL, data=data,
            headers={"Accept": "application/json", "User-Agent": f"{constants.APP_NAME}/{constants.APP_VERSION}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
        error = body.get("error", "")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 5
            continue
        elif error == "expired_token":
            on_error("Le code a expiré.")
            return
        elif error == "access_denied":
            on_error("Accès refusé.")
            return
        elif error:
            on_error(f"Erreur GitHub : {body.get('error_description', error)}")
            return
        elif "access_token" in body:
            on_success(body["access_token"])
            return
    on_error("Délai d'authentification expiré.")


def fetch_github_user(token: str) -> dict:
    req = urllib.request.Request(
        constants.GITHUB_API_USER_URL,
        headers={"Authorization": f"token {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": f"{constants.APP_NAME}/{constants.APP_VERSION}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise constants.OAuthError(f"Erreur GitHub API ({e.code})") from e
    except Exception as exc:
        raise constants.OAuthError(f"Erreur réseau : {exc}") from exc



def verify_github_token(token: str) -> tuple[bool, str]:
    """
    Vérifie qu'un token GitHub est valide en appelant /user.
    Retourne (True, login) ou (False, message_erreur).
    """
    try:
        user = fetch_github_user(token)
        login = user.get("login", "")
        if login:
            return True, login
        return False, "Réponse GitHub invalide"
    except constants.OAuthError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Erreur réseau : {exc}"


def save_github_account(token: str, user_info: dict, password: str = "") -> None:
    global _GITHUB_SESSION
    cfg     = config_store._load_config()
    account = cfg.setdefault("github_account", {})
    account["login"]      = user_info.get("login", "")
    account["name"]       = user_info.get("name", "") or user_info.get("login", "")
    account["avatar_url"] = user_info.get("avatar_url", "")

    if crypto.vault_is_unlocked():
        # Vault disponible → AES-256 Fernet, clé dérivée du master password
        crypto.vault_store("github_token", token, domain="github_token")
        account["token_encrypted"] = "__vault__"
        account["token_protected"] = False
    elif password:
        # Fallback : chiffrement par mot de passe fourni (AES-256 Fernet)
        account["token_encrypted"] = crypto.token_encrypt(token, password)
        account["token_protected"] = True
    else:
        account["token_encrypted"] = token
        account["token_protected"] = False

    config_store._save_config(cfg)
    _GITHUB_SESSION = {
        "login": account["login"], "name": account["name"],
        "token": token, "avatar_url": account.get("avatar_url", ""),
    }


def load_github_account_session(password: str = "") -> bool:
    global _GITHUB_SESSION
    cfg  = config_store._load_config()
    info = cfg.get("github_account", {})
    if not info.get("login"):
        return False
    raw = info.get("token_encrypted", "")

    if raw == "__vault__":
        if not crypto.vault_is_unlocked():
            return False
        token = crypto.vault_retrieve("github_token")
        if not token:
            return False
    elif info.get("token_protected"):
        if not password:
            return False
        token = crypto.token_decrypt(raw, password)
        if not token:
            return False
    else:
        token = raw

    _GITHUB_SESSION = {
        "login": info["login"], "name": info.get("name", info["login"]),
        "token": token, "avatar_url": info.get("avatar_url", ""),
        "auth_type": constants.AUTH_METHOD_OAUTH,
    }
    return True


def get_github_session() -> dict | None:
    return _GITHUB_SESSION


def get_github_account_info() -> dict:
    cfg  = config_store._load_config()
    info = cfg.get("github_account", {})
    return {
        "connected":       bool(info.get("login")),
        "login":           info.get("login", ""),
        "name":            info.get("name", ""),
        "avatar_url":      info.get("avatar_url", ""),
        "token_protected": bool(info.get("token_protected", False)),
    }


def clear_github_account() -> None:
    global _GITHUB_SESSION
    _GITHUB_SESSION = None
    cfg = config_store._load_config()
    cfg["github_account"] = {
        "login": None, "name": None, "avatar_url": None,
        "token_encrypted": None, "token_protected": False,
    }
    config_store._save_config(cfg)


def get_effective_token(path: Path | None = None) -> str:
    """Raccourci — délègue à get_effective_token_unified()."""
    return get_effective_token_unified(path)


