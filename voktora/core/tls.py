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
)

_installed = False


def _bundle_candidates() -> list[str]:
    found = [os.environ.get("SSL_CERT_FILE", "")]
    with contextlib.suppress(Exception):
        import certifi
        found.append(certifi.where())
    found.extend(SYSTEM_BUNDLES)
    return [path for path in found if path and Path(path).is_file()]


def make_context() -> ssl.SSLContext:
    """Contexte par défaut (vérification activée) + certificats système/certifi si disponibles."""
    context = ssl.create_default_context()
    if context.cert_store_stats().get("x509_ca", 0) == 0:
        for bundle in _bundle_candidates():
            with contextlib.suppress(ssl.SSLError, OSError):
                context.load_verify_locations(cafile=bundle)
                break
    return context


def install() -> None:
    """Fait de ce contexte celui de urllib/http.client pour tout le processus (idempotent)."""
    global _installed
    if _installed:
        return
    _installed = True
    ssl._create_default_https_context = make_context      # noqa: SLF001 - point d'extension documenté
