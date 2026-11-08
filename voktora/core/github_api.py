"""
Voktora — core.github_api
Lecture des dépôts et organisations GitHub de l'utilisateur.

Utilisé par le clone « depuis mes dépôts » et le classement par organisation.
Toutes les fonctions font des appels réseau BLOQUANTS : à lancer depuis un
thread de travail, jamais depuis l'interface.

Points vérifiés dans la documentation officielle de l'API REST :
  • GET /user/repos accepte `affiliation=owner,collaborator,organization_member`,
    `sort` (created, updated, pushed, full_name) et `per_page` (max 100) ;
  • GET /user/orgs exige le scope `user` ou `read:org` pour un token OAuth ou
    un PAT classique — or Voktora ne demande que `repo`. Les propriétaires
    (organisations comprises) sont donc dérivés des dépôts accessibles, et
    /user/orgs n'est utilisé qu'en complément, sans jamais faire échouer l'appel ;
  • un token d'installation de GitHub App n'a pas accès à /user/repos : on
    utilise alors GET /installation/repositories.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from . import constants

API_BASE = constants.GITHUB_API_BASE
_PER_PAGE = 100
_TIMEOUT = 15


@dataclass(frozen=True)
class RepoInfo:
    full_name: str
    name: str
    owner: str
    owner_type: str          # "User" ou "Organization"
    private: bool
    description: str
    clone_url: str
    default_branch: str
    pushed_at: str
    fork: bool = False
    archived: bool = False


@dataclass(frozen=True)
class OwnerInfo:
    login: str
    owner_type: str
    repo_count: int


def _headers(token: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{constants.APP_NAME}/{constants.APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(path_and_query: str, token: str):
    """GET sur l'API GitHub avec des messages d'erreur lisibles (jamais le token)."""
    request = urllib.request.Request(f"{API_BASE}{path_and_query}", headers=_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise constants.GitHubAPIError("Token GitHub invalide ou expiré (401). Reconnectez-vous.") from exc
        if exc.code in (403, 429):
            if exc.headers.get("X-RateLimit-Remaining") == "0" or exc.code == 429:
                raise constants.GitHubAPIError(
                    "Limite de requêtes GitHub atteinte. Réessayez dans quelques minutes.") from exc
            raise constants.GitHubAPIError(
                "Accès refusé par GitHub (403) : le token n'a pas les droits nécessaires.") from exc
        if exc.code == 404:
            raise constants.GitHubAPIError("Ressource GitHub introuvable (404).") from exc
        raise constants.GitHubAPIError(f"Erreur GitHub (HTTP {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise constants.GitHubAPIError(f"Réseau indisponible : {exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise constants.GitHubAPIError(f"Erreur réseau : {exc}") from exc
    except ValueError as exc:
        raise constants.GitHubAPIError("Réponse GitHub illisible.") from exc


def _parse_repo(raw: dict) -> RepoInfo | None:
    owner = raw.get("owner") or {}
    full_name, clone_url = raw.get("full_name"), raw.get("clone_url")
    if not isinstance(full_name, str) or not isinstance(clone_url, str) or not owner.get("login"):
        return None
    return RepoInfo(
        full_name=full_name,
        name=raw.get("name") or full_name.split("/")[-1],
        owner=owner["login"],
        owner_type=owner.get("type") or "User",
        private=bool(raw.get("private")),
        description=raw.get("description") or "",
        clone_url=clone_url,
        default_branch=raw.get("default_branch") or "main",
        pushed_at=raw.get("pushed_at") or "",
        fork=bool(raw.get("fork")),
        archived=bool(raw.get("archived")),
    )


def list_user_repos(token: str, *, installation: bool = False, max_pages: int = 30,
                    cancel: Callable[[], bool] | None = None) -> list[RepoInfo]:
    """Liste tous les dépôts accessibles (comptes personnels, organisations, collaborations).

    `installation=True` pour un token de GitHub App. `max_pages` borne le
    volume (30 pages de 100 = 3000 dépôts) pour éviter une boucle interminable.
    """
    if not token:
        raise constants.GitHubAPIError("Aucun compte GitHub connecté.")
    repos: list[RepoInfo] = []
    for page in range(1, max_pages + 1):
        if cancel and cancel():
            raise constants.OperationCancelled("Chargement annulé.")
        if installation:
            data = _get_json(f"/installation/repositories?per_page={_PER_PAGE}&page={page}", token)
            items = data.get("repositories", []) if isinstance(data, dict) else []
        else:
            data = _get_json(
                f"/user/repos?per_page={_PER_PAGE}&page={page}&sort=pushed"
                "&affiliation=owner,collaborator,organization_member", token)
            items = data if isinstance(data, list) else []
        repos.extend(r for r in (_parse_repo(item) for item in items if isinstance(item, dict)) if r)
        if len(items) < _PER_PAGE:
            break
    return repos


def _paged(path: str, token: str, key: str = "login", max_pages: int = 10) -> list[str]:
    """Parcourt toutes les pages d'une liste GitHub et renvoie les valeurs `key` (organisations, etc.)."""
    names: list[str] = []
    sep = "&" if "?" in path else "?"
    for page in range(1, max_pages + 1):
        data = _get_json(f"{path}{sep}per_page={_PER_PAGE}&page={page}", token)
        if not isinstance(data, list):
            break
        for item in data:
            value = item.get(key) if isinstance(item, dict) else None
            if not value and isinstance(item, dict) and isinstance(item.get("organization"), dict):
                value = item["organization"].get(key)          # /user/memberships/orgs : {organization: {login}}
            if value and value not in names:
                names.append(value)
        if len(data) < _PER_PAGE:
            break
    return names


def list_user_orgs_report(token: str) -> tuple[list[str], list[str]]:
    """Toutes les organisations de l'utilisateur (pagination complète, deux sources) + messages d'aide.

    `/user/orgs` (organisations visibles) complété par `/user/memberships/orgs` (adhésions actives, y compris
    privées). Sans le droit `read:org` GitHub n'en renvoie que quelques-unes : on le signale au lieu d'échouer.
    """
    orgs: list[str] = []
    notes: list[str] = []
    for path in ("/user/orgs", "/user/memberships/orgs?state=active"):
        try:
            for name in _paged(path, token):
                if name not in orgs:
                    orgs.append(name)
        except constants.GitHubAPIError as exc:
            notes.append(f"{path.split('?')[0]} : {exc}")
    if notes and not orgs:
        notes.append("Reconnectez le compte GitHub pour accorder le droit « read:org » (lecture des organisations).")
    return orgs, notes


def list_user_orgs(token: str) -> list[str]:
    """Organisations dont l'utilisateur est membre (complément, jamais bloquant) : [] en cas d'erreur."""
    return list_user_orgs_report(token)[0]


def owners_from_repos(repos: list[RepoInfo], extra_orgs: list[str] | tuple[str, ...] = ()) -> list[OwnerInfo]:
    """Regroupe les dépôts par propriétaire (compte ou organisation), triés par nom."""
    counts: dict[str, list] = {}
    for repo in repos:
        slot = counts.setdefault(repo.owner.lower(), [repo.owner, repo.owner_type, 0])
        slot[2] += 1
    for org in extra_orgs:
        counts.setdefault(org.lower(), [org, "Organization", 0])
    return sorted((OwnerInfo(*v) for v in counts.values()), key=lambda o: o.login.lower())
