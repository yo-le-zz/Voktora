"""
Voktora — shops.py (1.1.1)
Boutiques d'apparence : CHAQUE type de contenu a sa propre boutique (son propre index) —
thèmes (couleurs), packs d'icônes (SVG), styles (feuilles QSS : arrondis, densité, barres…).

  • index    : `<base>/shops/<kind>/index.json` ; objets dans `<base>/shops/<kind>/items/<id>/…`
  • sources  : la boutique officielle + des sources supplémentaires (adresse ajoutée par l'utilisateur, ou par un
               plugin via `api.register_shop_source`) — « chacun son shop », compatible avec les plugins ;
  • sécurité : https obligatoire, taille bornée, noms de fichiers relatifs, extensions propres à chaque type, chaque
               fichier vérifié par SHA-256 ; un objet n'est que de la DONNÉE (JSON, SVG, QSS) : aucun code exécuté.
               SVG : scripts, liens externes et <foreignObject> refusés. QSS : `url(` refusé.
  • application : thème → `theme_manager` ; pack d'icônes → `icons` (les icônes absentes du pack gardent la police) ;
                  styles → ajoutés après le thème, comme ceux des plugins.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import shutil
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import core

DEFAULT_BASE = "https://raw.githubusercontent.com/yo-le-zz/Voktora/main/marketplace"
KIND_THEMES, KIND_ICONS, KIND_STYLES = "themes", "icons", "styles"
KINDS: dict[str, dict] = {
    KIND_THEMES: {"label": "Thèmes", "icon": "mdi:palette-outline", "suffixes": {".json"},
                  "hint": "Couleurs de toute la fenêtre. Un thème = un fichier theme.json."},
    KIND_ICONS: {"label": "Icônes", "icon": "mdi:shape-outline", "suffixes": {".svg", ".json"},
                 "hint": "Pack d'icônes SVG : remplace celles de la police ; les icônes absentes gardent l'original."},
    KIND_STYLES: {"label": "Styles", "icon": "mdi:format-paint", "suffixes": {".qss", ".json"},
                  "hint": "Feuille de style : arrondis, densité, barres… ajoutée après le thème."},
}
MAX_FILES, MAX_FILE_BYTES, MAX_ITEM_BYTES, MAX_INDEX_BYTES = 400, 2 * 1024 * 1024, 16 * 1024 * 1024, 2 * 1024 * 1024
TIMEOUT = 15.0
ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_BAD_SVG = re.compile(r"<\s*(script|foreignObject|iframe|object|embed)\b|\bon\w+\s*=|(?:xlink:)?href\s*=\s*[\"']\s*(?!#)", re.I)
_BAD_QSS = re.compile(r"url\s*\(|@import|expression\s*\(", re.I)
_lock = threading.RLock()


class ShopError(RuntimeError):
    """Erreur de boutique (réseau, index, fichier refusé, empreinte incorrecte)."""


@dataclass
class ShopItem:
    kind: str
    id: str
    name: str
    version: str
    author: str
    description: str = ""
    files: dict[str, str] = field(default_factory=dict)        # chemin relatif → SHA-256
    colors: list[str] = field(default_factory=list)            # aperçu (thèmes)
    source: str = ""                                           # nom de la source
    base: str = ""                                             # URL de la boutique d'où il vient
    tags: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.kind}/{self.id}"


# ── sources (boutique officielle + ajouts) ────────────────────────────────────────

_plugin_sources: dict[str, list[tuple[str, str, str]]] = {}      # kind → [(propriétaire, nom, url)]


def _section() -> dict:
    cfg = core.get_app_config().get("shops")
    return cfg if isinstance(cfg, dict) else {}


def _save_section(section: dict) -> None:
    cfg = core.get_app_config()
    cfg["shops"] = section
    core.set_app_config(cfg)


def valid_base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ShopError("L'adresse d'une boutique doit commencer par https://.")
    return url


def sources(kind: str) -> list[tuple[str, str]]:
    """[(nom, URL de base)] : officielle, ajoutées par l'utilisateur, ajoutées par des plugins."""
    base = (core.get_app_config().get("plugins", {}) or {}).get("market_url") or DEFAULT_BASE
    out = [("Officielle", str(base).rstrip("/"))]
    out += [(str(s.get("name") or s["url"]), s["url"]) for s in _section().get("sources", {}).get(kind, [])
            if isinstance(s, dict) and s.get("url")]
    out += [(f"{name} (plugin {owner})", url) for owner, name, url in _plugin_sources.get(kind, [])]
    seen, unique = set(), []
    for name, url in out:
        if url not in seen:
            seen.add(url)
            unique.append((name, url))
    return unique


def add_source(kind: str, name: str, url: str) -> None:
    _check_kind(kind)
    url = valid_base(url)
    section = _section()
    items = section.setdefault("sources", {}).setdefault(kind, [])
    if not any(s.get("url") == url for s in items):
        items.append({"name": (name or url)[:60], "url": url})
    _save_section(section)


def remove_source(kind: str, url: str) -> None:
    section = _section()
    items = section.get("sources", {}).get(kind, [])
    section["sources"][kind] = [s for s in items if s.get("url") != url] if items else []
    _save_section(section)


def register_plugin_source(owner: str, kind: str, name: str, url: str) -> Callable[[], None]:
    """Pour les plugins (`api.register_shop_source`). Retourne la fonction qui retire la source."""
    _check_kind(kind)
    entry = (owner, name[:60] or url, valid_base(url))
    _plugin_sources.setdefault(kind, []).append(entry)
    return lambda: _plugin_sources.get(kind, []).remove(entry) if entry in _plugin_sources.get(kind, []) else None


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ShopError(f"Type de boutique inconnu : « {kind} » ({', '.join(KINDS)}).")


# ── réseau (point d'entrée unique, remplaçable en test) ───────────────────────────

def _fetch(url: str, limit: int = MAX_FILE_BYTES) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ShopError("Seules les adresses https:// sont acceptées.")
    request = urllib.request.Request(url, headers={"User-Agent": f"Voktora/{core.APP_VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:       # noqa: S310 — https vérifié
            if not response.geturl().startswith("https://"):
                raise ShopError("Redirection vers un site non sécurisé refusée.")
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise ShopError(f"Le serveur a répondu {exc.code} pour {parsed.path}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ShopError(f"Connexion impossible : {getattr(exc, 'reason', exc)}") from exc
    if len(data) > limit:
        raise ShopError(f"Fichier trop volumineux (> {limit // 1024} Ko) : {parsed.path}")
    return data


# ── index ────────────────────────────────────────────────────────────────────────

def safe_name(kind: str, name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > 100 or "\\" in name or name.startswith("/"):
        raise ShopError(f"Nom de fichier refusé : {name!r}")
    path = PurePosixPath(name)
    if ".." in path.parts or any(p.startswith(".") for p in path.parts):
        raise ShopError(f"Nom de fichier refusé : {name!r}")
    if path.suffix.lower() not in KINDS[kind]["suffixes"]:
        raise ShopError(f"Extension refusée pour une boutique « {kind} » : {name!r}")
    return str(path)


def parse_index(kind: str, data: bytes, base: str = "", source: str = "") -> list[ShopItem]:
    _check_kind(kind)
    if len(data) > MAX_INDEX_BYTES:
        raise ShopError("Index trop volumineux.")
    try:
        raw = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ShopError(f"Index illisible : {exc}") from exc
    entries = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise ShopError("Index invalide : liste « items » absente.")
    items = []
    for entry in entries:
        try:
            items.append(_parse_item(kind, entry, base, source))
        except ShopError:
            continue                                  # un objet invalide n'empêche pas les autres
    return items


def _parse_item(kind: str, entry: object, base: str, source: str) -> ShopItem:
    if not isinstance(entry, dict) or not ID_RE.match(str(entry.get("id", ""))):
        raise ShopError("objet invalide")
    files = entry.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise ShopError("fichiers invalides")
    clean = {}
    for name, digest in files.items():
        if not SHA_RE.match(str(digest)):
            raise ShopError("empreinte invalide")
        clean[safe_name(kind, name)] = digest
    colors = [c for c in entry.get("colors", []) if isinstance(c, str) and re.match(r"^#[0-9a-fA-F]{6}$", c)][:8]
    return ShopItem(kind, entry["id"], str(entry.get("name") or entry["id"])[:60], str(entry.get("version", "1.0.0"))[:30],
                    str(entry.get("author", "?"))[:60], str(entry.get("description", ""))[:300], clean, colors,
                    source, base, [str(t)[:24] for t in entry.get("tags", [])][:8])


def fetch_catalog(kind: str) -> tuple[list[ShopItem], list[str]]:
    """Objets de toutes les sources de la boutique + erreurs par source (une source en panne ne bloque pas)."""
    _check_kind(kind)
    items: dict[str, ShopItem] = {}
    errors: list[str] = []
    for name, base in sources(kind):
        try:
            data = _fetch(f"{base}/shops/{kind}/index.json", MAX_INDEX_BYTES)
            for item in parse_index(kind, data, base, name):
                items.setdefault(item.id, item)
        except ShopError as exc:
            errors.append(f"{name} : {exc}")
    return sorted(items.values(), key=lambda i: i.name.lower()), errors


# ── installation ─────────────────────────────────────────────────────────────────

def shops_dir() -> Path:
    return core.get_data_dir() / "shops"


def item_dir(kind: str, item_id: str) -> Path:
    return shops_dir() / kind / item_id


def check_content(kind: str, name: str, data: bytes) -> None:
    """Refuse le contenu actif ou dangereux (le contenu d'une boutique ne doit être que de la donnée)."""
    text = data.decode("utf-8", errors="replace") if name.endswith((".svg", ".qss", ".json")) else ""
    if name.endswith(".svg") and _BAD_SVG.search(text):
        raise ShopError(f"{name} : SVG refusé (script, lien externe ou élément actif).")
    if name.endswith(".qss") and _BAD_QSS.search(text):
        raise ShopError(f"{name} : feuille de style refusée (url(), @import).")
    if name.endswith(".json"):
        try:
            json.loads(text)
        except ValueError as exc:
            raise ShopError(f"{name} : JSON invalide ({exc}).") from exc


def install(item: ShopItem, on_progress: Callable[[int, int], None] | None = None) -> Path:
    """Télécharge, vérifie (SHA-256, contenu) puis installe. Atomique : rien n'est modifié en cas d'échec."""
    _check_kind(item.kind)
    base = valid_base(item.base)
    staged: dict[str, bytes] = {}
    total = 0
    for index, (name, digest) in enumerate(item.files.items(), 1):
        data = _fetch(f"{base}/shops/{item.kind}/items/{item.id}/{name}")
        if hashlib.sha256(data).hexdigest() != digest:
            raise ShopError(f"{name} : l'empreinte ne correspond pas à l'index — installation refusée.")
        check_content(item.kind, name, data)
        total += len(data)
        if total > MAX_ITEM_BYTES:
            raise ShopError("Objet trop volumineux.")
        staged[name] = data
        if on_progress:
            on_progress(index, len(item.files))
    return _write(item, staged)


def _write(item: ShopItem, staged: dict[str, bytes]) -> Path:
    with _lock:
        target = item_dir(item.kind, item.id)
        tmp = target.with_name(target.name + ".new")
        shutil.rmtree(tmp, ignore_errors=True)
        for name, data in staged.items():
            path = tmp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        meta = {"kind": item.kind, "id": item.id, "name": item.name, "version": item.version, "author": item.author,
                "description": item.description, "colors": item.colors, "source": item.source, "tags": item.tags}
        (tmp / "item.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.rmtree(target, ignore_errors=True)
        tmp.replace(target)
        _bump()
        return target


def install_local(kind: str, folder: Path) -> ShopItem:
    """Installe un objet depuis un dossier (création/essai local) : mêmes contrôles de contenu."""
    _check_kind(kind)
    meta_path = folder / "item.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ShopError(f"item.json illisible : {exc}") from exc
    staged = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.name != "item.json":
            rel = safe_name(kind, str(path.relative_to(folder).as_posix()))
            data = path.read_bytes()
            check_content(kind, rel, data)
            staged[rel] = data
    if not staged:
        raise ShopError("Dossier vide.")
    meta["files"] = {n: hashlib.sha256(d).hexdigest() for n, d in staged.items()}
    item = _parse_item(kind, meta, "", "local")
    _write(item, staged)
    return item


def uninstall(kind: str, item_id: str) -> bool:
    with _lock:
        target = item_dir(kind, item_id)
        existed = target.is_dir()
        shutil.rmtree(target, ignore_errors=True)
        cfg = _section()
        changed = False
        if cfg.get("icon_pack") == item_id and kind == KIND_ICONS:
            cfg["icon_pack"], changed = "", True
        if item_id in cfg.get("styles", []) and kind == KIND_STYLES:
            cfg["styles"] = [s for s in cfg["styles"] if s != item_id]
            changed = True
        if changed:
            _save_section(cfg)
        _bump()
        return existed


def installed(kind: str) -> list[dict]:
    out = []
    folder = shops_dir() / kind
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        meta = path / "item.json"
        if path.is_dir() and not path.name.endswith(".new") and meta.is_file():
            with contextlib.suppress(OSError, ValueError):
                data = json.loads(meta.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("id") == path.name:
                    out.append(data)
    return out


def installed_version(kind: str, item_id: str) -> str | None:
    return next((m.get("version") for m in installed(kind) if m.get("id") == item_id), None)


# ── application ──────────────────────────────────────────────────────────────────

_generation = 0
_icon_cache: tuple[int, str, dict[str, Path]] | None = None


def _bump() -> None:
    global _generation, _icon_cache
    _generation += 1
    _icon_cache = None


def installed_themes() -> dict[str, dict]:
    """Thèmes installés depuis les boutiques : {identifiant: thème}, au format de theme_manager."""
    out: dict[str, dict] = {}
    for meta in installed(KIND_THEMES):
        path = item_dir(KIND_THEMES, meta["id"]) / "theme.json"
        with contextlib.suppress(OSError, ValueError):
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("colors"), dict):
                data.setdefault("name", meta.get("name", meta["id"]))
                data.setdefault("description", meta.get("description", ""))
                out[meta["id"]] = data
    return out


def active_icon_pack() -> str:
    return str(_section().get("icon_pack") or "")


def set_icon_pack(pack_id: str) -> None:
    if pack_id and not (item_dir(KIND_ICONS, pack_id) / "item.json").is_file():
        raise ShopError("Ce pack d'icônes n'est pas installé.")
    section = _section()
    section["icon_pack"] = pack_id
    _save_section(section)
    _bump()


def icon_file(name: str) -> Path | None:
    """SVG du pack actif pour l'icône `name` (sans « mdi: »), ou None."""
    global _icon_cache
    pack = active_icon_pack()
    if not pack:
        return None
    if _icon_cache is None or _icon_cache[0] != _generation or _icon_cache[1] != pack:
        folder = item_dir(KIND_ICONS, pack)
        files = {p.stem: p for p in folder.rglob("*.svg")} if folder.is_dir() else {}
        _icon_cache = (_generation, pack, files)
    return _icon_cache[2].get(name)


def active_styles() -> list[str]:
    return [s for s in _section().get("styles", []) if isinstance(s, str)]


def set_style_enabled(style_id: str, enabled: bool) -> None:
    section = _section()
    current = [s for s in section.get("styles", []) if s != style_id]
    section["styles"] = [*current, style_id] if enabled else current
    _save_section(section)
    _bump()


def extra_stylesheet() -> str:
    """QSS des styles activés (ajouté après le thème et avant les styles des plugins)."""
    parts = []
    for style_id in active_styles():
        folder = item_dir(KIND_STYLES, style_id)
        for path in sorted(folder.glob("*.qss")) if folder.is_dir() else []:
            with contextlib.suppress(OSError):
                text = path.read_text(encoding="utf-8")
                if not _BAD_QSS.search(text):
                    parts.append(text)
    return "\n".join(parts)


def generation() -> int:
    return _generation
