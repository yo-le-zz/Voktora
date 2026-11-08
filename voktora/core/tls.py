"""
Voktora — core.tls
Certificats TLS pour toutes les requêtes HTTPS (urllib).

Dans une version compilée (Nuitka), OpenSSL cherche ses certificats à l'emplacement du Python qui a
compilé l'application — absent sur la machine de l'utilisateur — d'où « CERTIFICATE_VERIFY_FAILED :
unable to get local issuer certificate ». On charge donc explicitement un lot de certificats :
variable SSL_CERT_FILE, certifi s'il est installé, puis les emplacements système usuels (Fedora, Debian,
openSUSE, Alpine, macOS). La vérification n'est JAMAIS désactivée.
"""

from __future__ import annotations

import contextlib
import os
import ssl
from pathlib import Path

SYSTEM_BUNDLES = (
    "/etc/pki/tls/certs/ca-bundle.crt",            # Fedora / RHEL
    "/etc/ssl/certs/ca-certificates.crt",          # Debian / Ubuntu / Arch
    "/etc/ssl/ca-bundle.pem",                      # openSUSE
    "/etc/ssl/cert.pem",                           # Alpine / macOS / BSD
    "/usr/local/share/certs/ca-root-nss.crt",      # FreeBSD
    "/etc/ca-certificates/extracted/tls-ca-bundle.pem",   # Arch / Omarchy / Manjaro (p11-kit)
    "/etc/pki/tls/cacert.pem",                     # anciens RHEL / CentOS
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # Fedora (emplacement réel du lien)
)

_installed = False
_context: ssl.SSLContext | None = None
_ENV_VARS = ("SSL_CERT_FILE", "GIT_SSL_CAINFO", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE")


def _bundle_candidates() -> list[str]:
    """Lots de certificats existants, dans l'ordre : variable d'environnement, système, certifi."""
    found = [os.environ.get("SSL_CERT_FILE", ""), *SYSTEM_BUNDLES]
    with contextlib.suppress(Exception):
        import certifi
        found.append(certifi.where())
    return [path for path in found if path and Path(path).is_file()]


def make_context() -> ssl.SSLContext:
    """Contexte (vérification activée) qui charge TOUJOURS les certificats du système en plus des chemins par
    défaut d'OpenSSL. Avant, on ne les chargeait que si le magasin par défaut paraissait vide : un chemin par
    défaut périmé ou un dossier de certificats « paresseux » donnait un magasin non vide mais inutile, et GitHub
    était refusé alors que `SSL_CERT_FILE=…` marchait. Charger deux fois le même certificat est sans effet."""
    global _context
    if _context is not None:
        return _context
    context = ssl.create_default_context()
    for bundle in _bundle_candidates()[:2]:        # le 1er (env/système) + un secours (système ou certifi)
        with contextlib.suppress(ssl.SSLError, OSError):
            context.load_verify_locations(cafile=bundle)
    _context = context
    return context


def export_environment() -> str:
    """Publie le lot de certificats dans l'environnement du processus : git, curl et toute bibliothèque lancée par
    Voktora (qui peuvent embarquer leur propre OpenSSL, aux chemins périmés) le retrouvent. Ne remplace jamais
    une variable valide de l'utilisateur (seulement celles absentes ou cassées). Retourne le lot utilisé ('' si aucun)."""
    candidates = _bundle_candidates()
    if not candidates:
        return ""
    chosen = candidates[0]
    for name in _ENV_VARS:
        current = os.environ.get(name, "")
        if not current or not Path(current).is_file():       # absente ou pointant vers un fichier inexistant
            os.environ[name] = chosen
    return chosen


def install() -> None:
    """Fait de ce contexte celui de urllib/http.client pour tout le processus et exporte les variables
    d'environnement pour les sous-processus (idempotent)."""
    global _installed
    if _installed:
        return
    _installed = True
    export_environment()
    ssl._create_default_https_context = make_context      # noqa: SLF001 - point d'extension documenté
