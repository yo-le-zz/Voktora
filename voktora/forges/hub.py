"""
Voktora — forges.hub
Point d'entrée UNIQUE pour savoir « sur quelle forge est ce projet, est-ce un fork, de qui ? » et pour lister les
dépôts de tous les comptes (GitHub compris). Les heuristiques hors-ligne (remote `upstream`) sont instantanées ;
la confirmation par l'API (drapeau `fork`, dépôt parent) est optionnelle et mise en cache.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .base import Remote, Repo, parse_remote

_cache: dict[tuple[str, str], Repo] = {}


@dataclass
class ProjectForgeInfo:
    remotes: list[dict] = field(default_factory=list)       # {name, url, host, kind, full_name}
    origin: Remote | None = None
    upstream: Remote | None = None
    is_fork: bool = False
    parent: str = ""                                          # « propriétaire/dépôt » du dépôt d'origine
    parent_url: str = ""
    source: str = "none"                                      # "api" | "upstream" | "none"

    @property
    def forge_label(self) -> str:
        from .base import KINDS
        return KINDS.get(self.origin.kind, self.origin.host) if self.origin else ""

    def badge(self) -> str:
        if not self.origin:
            return ""
        text = f"{self.forge_label} · {self.origin.full_name}"
        if self.is_fork:
            text += f" — 🍴 fork de {self.parent}" if self.parent else " — 🍴 fork"
        return text


def git_remotes(path: str | Path) -> list[tuple[str, str]]:
    """[(nom, url)] des remotes (fetch). Sans git ou hors dépôt : liste vide."""
    try:
        out = subprocess.run(["git", "-C", str(path), "remote", "-v"], capture_output=True, text=True, timeout=8,
                             check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    seen, result = set(), []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "(fetch)" and parts[0] not in seen:
            seen.add(parts[0])
            result.append((parts[0], parts[1]))
    return result


def project_info(path: str | Path, remotes: list[tuple[str, str]] | None = None) -> ProjectForgeInfo:
    """Analyse instantanée (sans réseau). `origin` = remote « origin » (sinon le premier), `upstream` = remote
    « upstream » s'il pointe vers un AUTRE dépôt — signe habituel d'un fork."""
    info = ProjectForgeInfo()
    pairs = remotes if remotes is not None else git_remotes(path)
    parsed = {name: parse_remote(url) for name, url in pairs}
    for name, url in pairs:
        remote = parsed[name]
        info.remotes.append({"name": name, "url": _scrub(url), "host": remote.host if remote else "",
                             "kind": remote.kind if remote else "", "full_name": remote.full_name if remote else ""})
    info.origin = parsed.get("origin") or next((r for r in parsed.values() if r), None)
    up = parsed.get("upstream")
    if up and info.origin and (up.host, up.full_name.lower()) != (info.origin.host, info.origin.full_name.lower()):
        info.upstream, info.is_fork, info.parent, info.parent_url, info.source = (
            up, True, up.full_name, f"https://{up.host}/{up.full_name}", "upstream")
    if info.origin:
        cached = _cache.get((info.origin.host, info.origin.full_name.lower()))
        if cached is not None:
            _apply_repo(info, cached)
    return info


def _scrub(url: str) -> str:
    """Retire d'éventuels identifiants intégrés (https://user:token@host/…) avant tout affichage."""
    if "://" in url and "@" in url.split("://", 1)[1].split("/", 1)[0]:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://{rest.split('@', 1)[1]}"
    return url


def _apply_repo(info: ProjectForgeInfo, repo: Repo) -> None:
    info.is_fork = repo.fork or info.is_fork
    if repo.fork and repo.parent:
        info.parent, info.parent_url, info.source = repo.parent, repo.parent_url, "api"


def confirm_with_api(info: ProjectForgeInfo) -> ProjectForgeInfo:
    """Interroge la forge (si un compte est connu pour cet hôte) : fork confirmé / infirmé et dépôt parent exact.
    Bloquant : à appeler dans un thread. Les erreurs sont silencieuses (on garde l'heuristique)."""
    from . import accounts
    from .base import ForgeError
    from .clients import make_client
    if not info.origin:
        return info
    origin = info.origin
    token, kind = "", origin.kind
    acc = accounts.account_for_host(origin.host)
    if acc:
        token, kind = accounts.get_token(acc["id"]), acc["kind"]
    elif kind == "github":
        try:
            import core
            token = core.get_effective_token() or ""
        except Exception:  # noqa: BLE001
            token = ""
    if not kind:
        return info
    try:
        repo = make_client(kind, origin.host, token).repo(origin.owner, origin.name)
    except ForgeError:
        return info
    _cache[(origin.host, origin.full_name.lower())] = repo
    if not repo.fork and info.source == "api":
        info.is_fork, info.parent, info.parent_url, info.source = False, "", "", "none"
    _apply_repo(info, repo)
    return info


def all_repos() -> list[tuple[str, Repo]]:
    """[(étiquette du compte, dépôt)] pour tous les comptes de forge enregistrés + GitHub s'il est connecté."""
    from . import accounts
    from .base import ForgeError
    from .clients import make_client
    out: list[tuple[str, Repo]] = []
    for acc in accounts.list_accounts():
        try:
            for repo in accounts.client_for(acc["id"]).list_repos():
                out.append((f"{acc['label']} (@{acc['login']})", repo))
        except ForgeError as exc:
            out.append((f"{acc['label']} — erreur : {exc}", Repo(acc["kind"], acc["host"], "")))
    try:
        import core
        token = core.get_effective_token()
        session = core.get_github_session() or {}
        if token:
            for repo in make_client("github", "github.com", token).list_repos():
                out.append((f"GitHub (@{session.get('login', '')})", repo))
    except (ForgeError, Exception):  # noqa: BLE001
        pass
    return out
