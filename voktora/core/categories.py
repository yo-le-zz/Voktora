"""
Voktora — core.categories
Catégories de projets créées et gérées par l'utilisateur.

Une catégorie est un objet {name, emoji, color}. Un projet appartient à
au plus une catégorie (champ `category` = nom) ; pour classer selon plusieurs
critères, les tags restent disponibles. La comparaison des noms ignore la
casse (« Web » et « web » désignent la même catégorie).
"""

from __future__ import annotations

import copy
from pathlib import Path

from . import config_store, constants, organize

_FORBIDDEN_CHARS = frozenset("\x00\r\n\t")


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("Le nom de la catégorie ne peut pas être vide.")
    if len(name) > constants.MAX_CATEGORY_NAME_LENGTH:
        raise ValueError(
            f"Le nom de la catégorie est trop long ({len(name)} caractères, "
            f"maximum {constants.MAX_CATEGORY_NAME_LENGTH})."
        )
    if any(ch in _FORBIDDEN_CHARS for ch in name):
        raise ValueError("Le nom de la catégorie contient des caractères non autorisés.")
    return name


def _index_of(categories: list[dict], name: str) -> int:
    lowered = name.strip().lower()
    for i, cat in enumerate(categories):
        if cat["name"].lower() == lowered:
            return i
    return -1


def _clean_color(color: str | None) -> str:
    color = (color or "").strip()
    if color and not (len(color) in (4, 7) and color.startswith("#")
                      and all(c in "0123456789abcdefABCDEF" for c in color[1:])):
        raise ValueError(f"Couleur invalide : {color!r} (attendu : #RGB ou #RRGGBB).")
    return color


def list_categories() -> list[dict]:
    """Catégories dans l'ordre choisi par l'utilisateur (copie : modifiable sans effet)."""
    return copy.deepcopy(config_store._load_config().get("categories", []))


def get_category(name: str) -> dict | None:
    categories = config_store._load_config().get("categories", [])
    i = _index_of(categories, name)
    return copy.deepcopy(categories[i]) if i >= 0 else None


def add_category(name: str, emoji: str = "", color: str = "") -> dict:
    name, color = _clean_name(name), _clean_color(color)
    cfg = config_store._load_config()
    if _index_of(cfg["categories"], name) >= 0:
        raise ValueError(f"La catégorie « {name} » existe déjà.")
    cat = {"name": name, "emoji": (emoji or "").strip(), "color": color}
    cfg["categories"].append(cat)
    config_store._save_config(cfg)
    return copy.deepcopy(cat)


def ensure_category(name: str) -> dict:
    """Retourne la catégorie `name`, en la créant si elle n'existe pas encore."""
    existing = get_category(name)
    return existing if existing else add_category(name)


def update_category(name: str, *, new_name: str | None = None,
                    emoji: str | None = None, color: str | None = None) -> dict:
    """Modifie une catégorie ; un renommage est répercuté sur tous ses projets."""
    cfg = config_store._load_config()
    i = _index_of(cfg["categories"], name)
    if i < 0:
        raise KeyError(f"Catégorie introuvable : {name}")
    cat = cfg["categories"][i]
    old_name = cat["name"]

    if new_name is not None:
        new_name = _clean_name(new_name)
        clash = _index_of(cfg["categories"], new_name)
        if clash >= 0 and clash != i:
            raise ValueError(f"La catégorie « {new_name} » existe déjà.")
        cat["name"] = new_name
        for entry in cfg["projects"]:
            if (entry.get("category") or "").lower() == old_name.lower():
                entry["category"] = new_name
    if emoji is not None:
        cat["emoji"] = emoji.strip()
    if color is not None:
        cat["color"] = _clean_color(color)
    config_store._save_config(cfg)
    return copy.deepcopy(cat)


def delete_category(name: str) -> int:
    """Supprime une catégorie ; ses projets deviennent « sans catégorie ». Retourne leur nombre."""
    cfg = config_store._load_config()
    i = _index_of(cfg["categories"], name)
    if i < 0:
        return 0
    removed = cfg["categories"].pop(i)["name"].lower()
    cleared = 0
    for entry in cfg["projects"]:
        if (entry.get("category") or "").lower() == removed:
            entry["category"] = None
            cleared += 1
    config_store._save_config(cfg)
    return cleared


def move_category(name: str, offset: int) -> None:
    """Décale une catégorie vers le haut (offset < 0) ou le bas (offset > 0)."""
    cfg = config_store._load_config()
    categories = cfg["categories"]
    i = _index_of(categories, name)
    if i < 0:
        raise KeyError(f"Catégorie introuvable : {name}")
    j = max(0, min(len(categories) - 1, i + offset))
    if i != j:
        categories.insert(j, categories.pop(i))
        config_store._save_config(cfg)


def assign_category(paths: list[Path | str], category: str | None) -> int:
    """Affecte `category` (créée au besoin ; None = retirer) aux projets donnés.

    Retourne le nombre de projets modifiés.
    """
    canonical = ensure_category(category)["name"] if category and category.strip() else None
    cfg = config_store._load_config()
    wanted = {str(p) for p in paths}
    changed = 0
    for entry in cfg["projects"]:
        if entry["path"] in wanted and entry.get("category") != canonical:
            entry["category"] = canonical
            changed += 1
    if changed:
        config_store._save_config(cfg)
    return changed


def category_counts() -> dict[str, int]:
    """Nombre de projets par catégorie (nom → n) ; « None » regroupe les non classés."""
    counts: dict = {}
    for entry in config_store._load_config()["projects"]:
        key = entry.get("category") or None
        counts[key] = counts.get(key, 0) + 1
    return counts


def categorize_by_github_owner(only_uncategorized: bool = True) -> dict[str, int]:
    """Classe les projets d'après le propriétaire GitHub de leur dépôt.

    Pour chaque projet lié à un dépôt GitHub, la catégorie portant le nom du
    propriétaire (compte ou organisation) est créée si besoin puis attribuée.
    Retourne {propriétaire: nombre de projets classés}.
    """
    cfg = config_store._load_config()
    assigned: dict[str, int] = {}
    for entry in cfg["projects"]:
        owner = organize.github_owner(entry.get("github_repo"))
        if not owner or (only_uncategorized and entry.get("category")):
            continue
        i = _index_of(cfg["categories"], owner)
        if i < 0:
            cfg["categories"].append({"name": owner[: constants.MAX_CATEGORY_NAME_LENGTH],
                                      "emoji": "🐙", "color": ""})
            i = len(cfg["categories"]) - 1
        name = cfg["categories"][i]["name"]
        if entry.get("category") != name:
            entry["category"] = name
            assigned[name] = assigned.get(name, 0) + 1
    if assigned:
        config_store._save_config(cfg)
    return assigned
