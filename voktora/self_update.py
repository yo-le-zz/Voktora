"""
Voktora — self_update (1.1.1) : mise à jour de Voktora depuis les versions GitHub de yo-le-zz/Voktora (tags `vX.Y.Z`).

Principe volontairement prudent :
  1. `check()` interroge l'API GitHub (https uniquement), au plus une fois par 24 h en tâche de fond ;
  2. `download(release)` télécharge la ressource adaptée à la plateforme dans un dossier de préparation, vérifie sa somme
     SHA-256 (ressource « <fichier>.sha256 » ou champ `digest` de GitHub ; sans somme → refus) puis la laisse en place ;
  3. Voktora ne remplace JAMAIS son propre exécutable en marche : il indique où se trouve le fichier vérifié et comment
     l'installer. L'application ne se met donc pas à jour « dans votre dos ».
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import core

REPO = "yo-le-zz/Voktora"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
CHECK_SECONDS = 24 * 3600
MAX_DOWNLOAD = 2 * 1024 ** 3
TIMEOUT = 20.0


class UpdateError(RuntimeError):
    pass


@dataclass
class Release:
    tag: str
    version: str
    notes: str = ""
    url: str = ""
    assets: dict[str, dict] = field(default_factory=dict)       # nom → {"url", "size", "digest"}


def parse_version(text: str) -> tuple[int, int, int] | None:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", text.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_newer(candidate: str, current: str | None = None) -> bool:
    a, b = parse_version(candidate), parse_version(current or core.APP_VERSION)
    return bool(a and b and a > b)


def _get(url: str, limit: int = 4 * 1024 * 1024) -> bytes:
    if not url.startswith("https://"):
        raise UpdateError("Adresse non sécurisée refusée.")
    request = urllib.request.Request(url, headers={"User-Agent": f"Voktora/{core.APP_VERSION}",
                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:      # noqa: S310 — https vérifié ci-dessus
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("Réponse trop volumineuse.")
    return data


def parse_release(payload: dict) -> Release | None:
    tag = str(payload.get("tag_name", ""))
    if not TAG_RE.match(tag) or payload.get("draft") or payload.get("prerelease"):
        return None
    assets = {}
    for a in payload.get("assets", []):
        url = str(a.get("browser_download_url", ""))
        if url.startswith("https://") and a.get("name"):
            assets[str(a["name"])] = {"url": url, "size": int(a.get("size", 0)), "digest": str(a.get("digest") or "")}
    return Release(tag=tag, version=tag[1:], notes=str(payload.get("body") or "")[:4000],
                   url=str(payload.get("html_url", "")), assets=assets)


def check() -> Release | None:
    """La dernière version publiée si elle est plus récente que celle-ci, sinon None. Peut lever UpdateError/OSError."""
    try:
        payload = json.loads(_get(API))
    except ValueError as exc:
        raise UpdateError("Réponse de GitHub illisible.") from exc
    release = parse_release(payload)
    return release if release and is_newer(release.version) else None


def platform_keywords() -> list[str]:
    if sys.platform == "win32":
        return ["windows", "win", ".exe", ".msi"]
    if sys.platform == "darwin":
        return ["macos", "mac", "darwin", ".dmg"]
    return ["linux", ".appimage", ".tar.gz", ".rpm", ".deb"]


def pick_asset(release: Release) -> str | None:
    names = [n for n in release.assets if not n.endswith((".sha256", ".sig", ".asc"))]
    for keyword in platform_keywords():
        for name in names:
            if keyword in name.lower():
                return name
    return None


def staging_dir() -> Path:
    path = core.get_data_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def expected_sha256(release: Release, name: str) -> str:
    asset = release.assets[name]
    digest = asset.get("digest", "")
    if digest.startswith("sha256:"):
        return digest[7:].lower()
    sidecar = release.assets.get(name + ".sha256")
    if sidecar:
        m = re.search(r"\b[0-9a-fA-F]{64}\b", _get(sidecar["url"], 4096).decode("utf-8", "replace"))
        if m:
            return m.group(0).lower()
    raise UpdateError("Aucune somme SHA-256 publiée pour ce fichier : téléchargement refusé.")


def download(release: Release, name: str | None = None, progress=None) -> Path:
    name = name or pick_asset(release)
    if not name or name not in release.assets:
        raise UpdateError("Aucun fichier de cette version ne correspond à votre système.")
    if not re.fullmatch(r"[A-Za-z0-9._+-]{1,120}", name):
        raise UpdateError("Nom de fichier suspect.")
    want = expected_sha256(release, name)
    asset = release.assets[name]
    if asset["size"] > MAX_DOWNLOAD:
        raise UpdateError("Fichier trop volumineux.")
    target = staging_dir() / name
    partial = target.with_suffix(target.suffix + ".part")
    digest, done = hashlib.sha256(), 0
    request = urllib.request.Request(asset["url"], headers={"User-Agent": f"Voktora/{core.APP_VERSION}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, partial.open("wb") as out:     # noqa: S310
        while chunk := response.read(256 * 1024):
            done += len(chunk)
            if done > MAX_DOWNLOAD:
                partial.unlink(missing_ok=True)
                raise UpdateError("Fichier trop volumineux.")
            digest.update(chunk)
            out.write(chunk)
            if progress:
                progress(done, asset["size"])
    if digest.hexdigest() != want:
        partial.unlink(missing_ok=True)
        raise UpdateError("Somme SHA-256 incorrecte : fichier supprimé.")
    partial.replace(target)
    return target


def due() -> bool:
    cfg = core.get_app_config().get("updates", {})
    return bool(cfg.get("check", True)) and time.time() - float(cfg.get("last_check", 0)) >= CHECK_SECONDS


def stamp() -> None:
    cfg = core.get_app_config()
    section = cfg.get("updates") if isinstance(cfg.get("updates"), dict) else {}
    section["last_check"] = time.time()
    cfg["updates"] = section
    core.set_app_config(cfg)


def set_check_enabled(on: bool) -> None:
    cfg = core.get_app_config()
    section = cfg.get("updates") if isinstance(cfg.get("updates"), dict) else {}
    section["check"] = bool(on)
    cfg["updates"] = section
    core.set_app_config(cfg)


def check_if_due() -> Release | None:
    if not due():
        return None
    stamp()
    return check()
