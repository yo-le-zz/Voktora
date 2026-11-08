"""
Voktora — forges.base
Modèle commun aux forges (GitHub, GitLab, Forgejo/Gitea — dont la forge de Fedora et Codeberg) : analyse d'un
remote git, dépôt normalisé (avec la notion de FORK et de dépôt parent) et petit client HTTP vérifié (TLS).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

KINDS = {
    "github": "GitHub",
    "gitlab": "GitLab",
    "forgejo": "Forgejo / Gitea",
}
# Instances connues : (nom affiché, type, hôte). Le type est déduit de l'hôte pour tout remote déjà configuré.
PRESETS = (
    ("GitHub", "github", "github.com"),
    ("GitLab.com", "gitlab", "gitlab.com"),
    ("Fedora Forge", "forgejo", "forge.fedoraproject.org"),
    ("GitLab Fedora (gitlab.com/fedora)", "gitlab", "gitlab.com"),
    ("Codeberg", "forgejo", "codeberg.org"),
)
_HOST_KIND = {"github.com": "github", "gitlab.com": "gitlab", "forge.fedoraproject.org": "forgejo",
              "codeberg.org": "forgejo", "gitlab.freedesktop.org": "gitlab", "salsa.debian.org": "gitlab",
              "gitlab.gnome.org": "gitlab", "invent.kde.org": "gitlab", "framagit.org": "gitlab"}


class ForgeError(Exception):
    """Erreur lisible par l'utilisateur (authentification, réseau, dépôt introuvable…)."""


@dataclass(frozen=True)
class Remote:
    host: str
    owner: str          # peut contenir des sous-groupes GitLab : « groupe/sous-groupe »
    name: str
    url: str = ""

    @property
    def kind(self) -> str:
        return guess_kind(self.host)

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass
class Repo:
    forge: str                  # type : github | gitlab | forgejo
    host: str
    full_name: str
    web_url: str = ""
    clone_url: str = ""
    ssh_url: str = ""
    description: str = ""
    private: bool = False
    fork: bool = False
    parent: str = ""            # « propriétaire/dépôt » du dépôt dont celui-ci est un fork (si connu)
    parent_url: str = ""
    default_branch: str = ""
    extra: dict = field(default_factory=dict)


_SCP = re.compile(r"^(?:[\w.-]+@)?(?P<host>[\w.-]+):(?P<path>[^/].*)$")


def parse_remote(url: str) -> Remote | None:
    """`https://host/o/r(.git)`, `git@host:o/r.git`, `ssh://git@host:22/o/r` → Remote ; None si illisible."""
    url = (url or "").strip()
    if not url:
        return None
    host, path = "", ""
    if "://" in url:
        parts = urllib.parse.urlsplit(url)
        host, path = (parts.hostname or ""), parts.path
    else:
        match = _SCP.match(url)
        if match:
            host, path = match["host"], match["path"]
    path = path.strip("/")
    path = path.removesuffix(".git")
    if not host or "/" not in path:
        return None
    owner, name = path.rsplit("/", 1)
    if not owner or not name:
        return None
    return Remote(host.lower(), owner, name, url)


def guess_kind(host: str, custom: dict[str, str] | None = None) -> str:
    host = (host or "").lower()
    if custom and host in custom:
        return custom[host]
    if host in _HOST_KIND:
        return _HOST_KIND[host]
    if "gitlab" in host:
        return "gitlab"
    if any(word in host for word in ("forgejo", "gitea", "codeberg", "forge")):
        return "forgejo"
    return "github" if host.endswith("github.com") else ""


def http_json(url: str, headers: dict[str, str], timeout: float = 15.0):
    """GET JSON avec vérification TLS (certificats système/certifi). Lève ForgeError avec un message clair."""
    if not url.lower().startswith("https://"):
        raise ForgeError("Seul HTTPS est autorisé pour parler à une forge.")
    try:
        import core.tls as tls
        context = tls.make_context()
    except Exception:  # noqa: BLE001 — repli : contexte par défaut
        import ssl
        context = ssl.create_default_context()
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Voktora", **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as resp:  # noqa: S310 — https imposé
            return json.loads(resp.read(8_000_000))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ForgeError("Accès refusé : jeton invalide, expiré ou sans la permission de lecture des dépôts.") from exc
        if exc.code == 404:
            raise ForgeError("Introuvable (404) : dépôt privé sans accès, ou adresse incorrecte.") from exc
        raise ForgeError(f"Erreur HTTP {exc.code} de la forge.") from exc
    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        if "CERTIFICATE" in reason.upper():
            raise ForgeError(f"Certificat TLS refusé ({reason}). Vérifiez l'adresse et l'heure du PC ; "
                             "pour une forge interne, ajoutez son autorité dans SSL_CERT_FILE.") from exc
        raise ForgeError(f"Forge injoignable : {reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise ForgeError(f"Forge injoignable : {exc}") from exc
    except ValueError as exc:
        raise ForgeError("Réponse illisible de la forge.") from exc
