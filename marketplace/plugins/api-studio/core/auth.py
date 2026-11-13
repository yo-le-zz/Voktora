"""Authentification : Basic, Bearer, clé d'API, OAuth2 (client_credentials et code + PKCE)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.parse


def basic_header(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def apply(auth: dict, headers: list[tuple[str, str]], params: list[tuple[str, str]]) -> None:
    """Ajoute l'authentification (valeurs déjà substituées) aux en-têtes / paramètres."""
    t = auth.get("type", "none")
    if t == "basic":
        headers.append(("Authorization", basic_header(auth.get("user", ""), auth.get("password", ""))))
    elif t == "bearer":
        headers.append(("Authorization", f"{auth.get('prefix', 'Bearer')} {auth.get('token', '')}"))
    elif t == "apikey":
        (params if auth.get("in") == "query" else headers).append((auth.get("name", "X-API-Key"), auth.get("value", "")))
    elif t == "oauth2" and auth.get("access_token"):
        headers.append(("Authorization", f"Bearer {auth['access_token']}"))


# --- PKCE (RFC 7636) -----------------------------------------------------------------------------
def pkce_pair(verifier: str | None = None) -> tuple[str, str]:
    verifier = verifier or secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorization_url(auth_url: str, client_id: str, redirect_uri: str, scope: str, challenge: str, state: str) -> str:
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": scope, "state": state,
         "code_challenge": challenge, "code_challenge_method": "S256"}
    sep = "&" if "?" in auth_url else "?"
    return auth_url + sep + urllib.parse.urlencode({k: v for k, v in q.items() if v})


def token_request(grant: str, token_url: str, client_id: str, client_secret: str = "", **extra) -> dict:
    """Décrit la requête de jeton (méthode, URL, en-têtes, corps) ; l'envoi se fait avec le client HTTP du plugin."""
    form = {"grant_type": grant, "client_id": client_id, **{k: v for k, v in extra.items() if v}}
    headers = [("Content-Type", "application/x-www-form-urlencoded"), ("Accept", "application/json")]
    if client_secret:
        headers.append(("Authorization", basic_header(client_id, client_secret)))
        form.pop("client_id", None) if grant == "client_credentials" else None
    return {"method": "POST", "url": token_url, "headers": headers, "body": urllib.parse.urlencode(form)}


def parse_token_response(text: str) -> dict:
    try:
        d = json.loads(text)
    except ValueError as exc:
        raise ValueError("Réponse de jeton illisible.") from exc
    if "access_token" not in d:
        raise ValueError(d.get("error_description") or d.get("error") or "Pas de jeton dans la réponse.")
    return {"access_token": d["access_token"], "token_type": d.get("token_type", "Bearer"), "expires_in": d.get("expires_in"),
            "refresh_token": d.get("refresh_token", "")}


def parse_redirect(path_query: str, expected_state: str) -> str:
    """Extrait `code` de la redirection locale ; vérifie `state` (anti-CSRF)."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(path_query).query)
    if q.get("error"):
        raise ValueError(f"Autorisation refusée : {q['error'][0]}")
    if q.get("state", [""])[0] != expected_state:
        raise ValueError("Paramètre « state » incorrect (requête ignorée).")
    if not q.get("code"):
        raise ValueError("Pas de code dans la redirection.")
    return q["code"][0]
