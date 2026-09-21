"""
Voktora — core.organize
Recherche, tri et regroupement des projets — logique pure (sans Qt, sans
accès disque hors `read_git_origin`), donc facile à tester et partagée par
les vues liste et grille.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ──────────────────────────────────────────────
# OPTIONS PROPOSÉES À L'UTILISATEUR
# ──────────────────────────────────────────────

SORT_OPTIONS: list[tuple[str, str]] = [
    ("name_asc",  "Nom A → Z"),
    ("name_desc", "Nom Z → A"),
    ("date_desc", "Date (récent)"),
    ("date_asc",  "Date (ancien)"),
    ("lang",      "Langage"),
    ("status",    "Statut"),
    ("category",  "Catégorie"),
    ("manual",    "Ordre manuel"),
]

GROUP_OPTIONS: list[tuple[str, str]] = [
    ("category",     "Par catégorie"),
    ("github_owner", "Par organisation GitHub"),
    ("language",     "Par langage"),
    ("status",       "Par statut"),
    ("none",         "Sans regroupement"),
]

DEFAULT_SORT = "name_asc"
DEFAULT_GROUP = "category"

# ──────────────────────────────────────────────
# URL GITHUB
# ──────────────────────────────────────────────

_GITHUB_URL_RE = re.compile(
    r"""^(?:
        (?:https?|ssh|git)://(?:[^/@\s]+@)?github\.com[/:]   # https://[cred@]github.com/  |  ssh://git@github.com/
      | (?:[^/@\s]+@)?github\.com:                            # git@github.com:
    )(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$""",
    re.VERBOSE | re.IGNORECASE,
)


def parse_github_url(url: str | None) -> tuple[str, str] | None:
    """Extrait (propriétaire, dépôt) d'une URL GitHub (https, ssh ou scp-like)."""
    if not url:
        return None
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        return None
    return match.group("owner"), match.group("repo")


def github_owner(url: str | None) -> str | None:
    """Organisation ou compte propriétaire d'un dépôt GitHub, sinon None."""
    parsed = parse_github_url(url)
    return parsed[0] if parsed else None


def repo_name_from_url(url: str) -> str:
    """Nom du dépôt d'une URL git quelconque (dernier segment sans « .git »)."""
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    return re.split(r"[/:\\]", cleaned)[-1] if cleaned else ""


def strip_url_credentials(url: str) -> str:
    """Retire « user:token@ » d'une URL http(s) — pour ne jamais stocker de secret."""
    return re.sub(r"^(https?://)[^/@\s]+@", r"\1", url.strip())


_REMOTE_HEADER_RE = re.compile(r'^\s*\[remote\s+"origin"\]\s*$')
_ANY_HEADER_RE = re.compile(r"^\s*\[")
_URL_LINE_RE = re.compile(r"^\s*url\s*=\s*(.+?)\s*$")


def read_git_origin(folder: Path) -> tuple[str | None, str | None]:
    """Lit (URL de `origin` sans identifiants, branche courante) depuis `.git`.

    Lecture directe des fichiers : aucune dépendance à l'exécutable git, et
    aucun risque d'exécuter un hook. Retourne (None, None) si absent.
    """
    git_dir = Path(folder) / ".git"
    if not git_dir.is_dir():
        return None, None
    url = branch = None
    try:
        in_origin = False
        for line in (git_dir / "config").read_text(encoding="utf-8", errors="replace").splitlines():
            if _REMOTE_HEADER_RE.match(line):
                in_origin = True
            elif _ANY_HEADER_RE.match(line):
                in_origin = False
            elif in_origin and (m := _URL_LINE_RE.match(line)):
                url = strip_url_credentials(m.group(1))
                break
    except OSError:
        pass
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
        if head.startswith("ref: refs/heads/"):
            branch = head.removeprefix("ref: refs/heads/")
    except OSError:
        pass
    return url, branch


# ──────────────────────────────────────────────
# RECHERCHE
# ──────────────────────────────────────────────

def entry_matches(entry: dict, needle_lower: str) -> bool:
    """Teste si un projet correspond à une recherche (déjà en minuscules).

    Cherche dans le nom, le chemin, la catégorie, l'organisation GitHub et les tags.
    """
    haystack = " ".join([
        entry.get("name") or "",
        entry.get("path") or "",
        entry.get("category") or "",
        github_owner(entry.get("github_repo")) or "",
    ])
    if needle_lower in haystack.lower():
        return True
    return any(needle_lower in tag.lower() for tag in entry.get("tags") or [])


# ──────────────────────────────────────────────
# TRI
# ──────────────────────────────────────────────

def _sort_key(entry: dict, sort: str):
    name = (entry.get("name") or "").lower()
    if sort in ("date_desc", "date_asc"):
        return (entry.get("created") or "", name)
    if sort == "lang":
        return ((entry.get("language") or "~").lower(), name)
    if sort == "status":
        return ((entry.get("status") or "~").lower(), name)
    if sort == "category":
        return ((entry.get("category") or "\uffff").lower(), name)
    return name


def sort_entries(entries: list[dict], sort: str) -> list[dict]:
    """Trie une liste de projets ; « manual » conserve l'ordre stocké."""
    if sort == "manual":
        return list(entries)
    return sorted(entries, key=lambda e: _sort_key(e, sort), reverse=sort in ("name_desc", "date_desc"))


# ──────────────────────────────────────────────
# REGROUPEMENT
# ──────────────────────────────────────────────

@dataclass
class Group:
    """Un groupe de projets affichable (section de liste ou de grille)."""
    key: str | None                 # valeur brute (nom de catégorie, propriétaire…) ; None = sans valeur
    label: str
    entries: list[dict] = field(default_factory=list)
    emoji: str = ""
    color: str = ""


_EMPTY_LABELS = {
    "category":     "Sans catégorie",
    "github_owner": "Sans dépôt GitHub",
    "language":     "Sans langage",
    "status":       "Sans statut",
}


def _value_of(entry: dict, group_by: str) -> str | None:
    if group_by == "category":
        value = entry.get("category")
    elif group_by == "github_owner":
        value = github_owner(entry.get("github_repo"))
    elif group_by == "language":
        value = entry.get("language")
    elif group_by == "status":
        value = entry.get("status")
    else:
        value = None
    return value.strip() if isinstance(value, str) and value.strip() else None


def group_entries(entries: list[dict], group_by: str, *,
                  categories: list[dict] | None = None,
                  status_labels: dict[str, str] | None = None,
                  include_empty_categories: bool = False) -> list[Group]:
    """Répartit les projets en groupes ordonnés.

    Ordre des groupes : catégories dans l'ordre choisi par l'utilisateur ;
    statuts dans l'ordre de déclaration ; organisations et langages par ordre
    alphabétique. Le groupe « sans valeur » est toujours placé en dernier.
    L'ordre des projets à l'intérieur d'un groupe est celui de `entries`
    (déjà trié par l'appelant).
    """
    if group_by == "none" or group_by not in _EMPTY_LABELS:
        return [Group(key=None, label="Tous les projets", entries=list(entries))]

    buckets: dict[str, Group] = {}   # clé en minuscules → groupe
    ordered: list[Group] = []

    def _bucket(value: str, label: str | None = None, emoji: str = "", color: str = "") -> Group:
        lowered = value.lower()
        if lowered not in buckets:
            buckets[lowered] = Group(key=value, label=label or value, emoji=emoji, color=color)
            ordered.append(buckets[lowered])
        return buckets[lowered]

    if group_by == "category":
        for cat in categories or []:
            if include_empty_categories or any(_value_of(e, "category") and
                                               _value_of(e, "category").lower() == cat["name"].lower()
                                               for e in entries):
                _bucket(cat["name"], emoji=cat.get("emoji", ""), color=cat.get("color", ""))
    elif group_by == "status" and status_labels:
        for status_id, label in status_labels.items():
            _bucket(status_id, label=label)

    without_value = Group(key=None, label=_EMPTY_LABELS[group_by])
    for entry in entries:
        value = _value_of(entry, group_by)
        target = without_value if value is None else _bucket(
            value, label=(status_labels or {}).get(value) if group_by == "status" else None)
        target.entries.append(entry)

    if group_by in ("github_owner", "language") or group_by == "status" and not status_labels:
        ordered.sort(key=lambda g: (g.key or "").lower())

    if without_value.entries:
        ordered.append(without_value)
    # Un groupe vide (statut déclaré mais sans projet) n'a pas d'intérêt à l'affichage.
    return [g for g in ordered if g.entries or (group_by == "category" and include_empty_categories and g.key)]
