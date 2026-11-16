"""
Voktora — catalog_search (1.1.4) : recherche « intelligente » pour les marketplaces (plugins, thèmes, icônes, styles).
Logique pure (sans Qt), conçue pour des milliers d'éléments : l'index met en minuscules une seule fois ; une requête ne parcourt
que des chaînes déjà préparées.

Syntaxe (tout est optionnel, les mots sont combinés en ET) :
  mot            contient « mot » (nom, id, description, étiquettes, auteur) — tolère une faute de frappe pour les mots ≥ 5 lettres
  "deux mots"    expression exacte
  -mot           exclut
  tag:sombre     étiquette (ou #sombre)             lang:rust       langage (python, js, rust)
  auteur:nom     auteur                              perm:network    permission demandée
  is:installed | is:new | is:update | is:active | is:community | is:official
  sort:name | sort:recent | sort:relevance          limit:50
"""

from __future__ import annotations

import difflib
import re
import shlex
from collections import Counter
from dataclasses import dataclass, field

FIELDS = {"tag": "tags", "tags": "tags", "lang": "lang", "langage": "lang", "auteur": "author", "author": "author",
          "perm": "perms", "permission": "perms"}
STATES = {"installed": "installed", "installe": "installed", "installé": "installed", "new": "new", "nouveau": "new",
          "update": "update", "maj": "update", "active": "active", "actif": "active", "community": "community",
          "communaute": "community", "officiel": "official", "official": "official"}
SORTS = ("relevance", "name", "recent")


@dataclass
class Query:
    words: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    filters: dict[str, list[str]] = field(default_factory=dict)       # tags, lang, author, perms (OU dans un champ, ET entre champs)
    states: set[str] = field(default_factory=set)
    sort: str = "relevance"
    limit: int = 0

    @property
    def empty(self) -> bool:
        return not (self.words or self.phrases or self.excluded or self.filters or self.states)


def parse(text: str) -> Query:
    q = Query()
    try:
        tokens = shlex.split(text or "", posix=True)
    except ValueError:                                  # guillemet non fermé : on tolère
        tokens = (text or "").replace('"', " ").split()
    for tok in tokens:
        low = tok.casefold().strip()
        if not low:
            continue
        if low.startswith("-") and len(low) > 1:
            q.excluded.append(low[1:])
        elif low.startswith("#") and len(low) > 1:
            q.filters.setdefault("tags", []).append(low[1:])
        elif ":" in low and low.split(":", 1)[0] in FIELDS | {"is": 1, "sort": 1, "limit": 1, "est": 1, "tri": 1}.keys():
            key, value = low.split(":", 1)
            if not value:
                continue
            if key in ("is", "est"):
                if value in STATES:
                    q.states.add(STATES[value])
            elif key in ("sort", "tri"):
                q.sort = {"nom": "name", "recent": "recent", "récent": "recent", "name": "name"}.get(value, "relevance")
            elif key == "limit":
                q.limit = int(value) if value.isdigit() else 0
            else:
                q.filters.setdefault(FIELDS[key], []).append(value)
        elif " " in tok.strip():
            q.phrases.append(low)
        else:
            q.words.append(low)
    return q


@dataclass
class Doc:
    key: str
    name: str = ""
    desc: str = ""
    tags: tuple[str, ...] = ()
    author: str = ""
    lang: str = ""
    perms: tuple[str, ...] = ()
    states: frozenset[str] = frozenset()
    order: int = 0                                      # position d'origine (tri « récent » = ordre du catalogue inversé)
    payload: object = None
    hay: str = ""
    name_l: str = ""
    tokens: frozenset[str] = frozenset()


def make_doc(key: str, *, name: str = "", description: str = "", tags=(), author: str = "", lang: str = "", perms=(),
             states=(), order: int = 0, payload=None) -> Doc:
    d = Doc(key, name, description, tuple(str(t).casefold() for t in tags), author.casefold(), lang.casefold(),
            tuple(str(p).casefold() for p in perms), frozenset(states), order, payload)
    d.name_l = name.casefold()
    d.hay = " ".join([key.casefold(), d.name_l, description.casefold(), " ".join(d.tags), d.author])
    d.tokens = frozenset(re.findall(r"\w+", d.hay))
    return d


class Index:
    def __init__(self, docs: list[Doc] | None = None):
        self.docs: list[Doc] = list(docs or [])

    def add(self, doc: Doc) -> None:
        self.docs.append(doc)

    # ── agrégats pour les filtres (puces) ───────────────────────────────────
    def facets(self, field_name: str = "tags", top: int = 24) -> list[tuple[str, int]]:
        counter: Counter = Counter()
        for d in self.docs:
            value = getattr(d, field_name)
            counter.update([value] if isinstance(value, str) and value else value if isinstance(value, tuple) else [])
        return counter.most_common(top)

    def suggest(self, prefix: str, limit: int = 8) -> list[str]:
        """Complétions pour le mot en cours de frappe : `tag:so` → `tag:sombre`, `ru` → `lang:rust`…"""
        prefix = prefix.casefold()
        out: list[str] = []
        if ":" in prefix:
            key, value = prefix.split(":", 1)
            names = {"tag": "tags", "lang": "lang", "auteur": "author", "author": "author", "perm": "perms"}
            if key in names:
                counter = dict(self.facets(names[key], 500))
                out = [f"{key}:{v}" for v in counter if v.startswith(value)]
            elif key == "is":
                out = [f"is:{s}" for s in ("installed", "new", "update", "active", "community", "official") if s.startswith(value)]
        elif prefix:
            out = [f"tag:{t}" for t, _ in self.facets("tags", 500) if t.startswith(prefix)]
            out += [f"lang:{lang}" for lang, _ in self.facets("lang", 10) if lang.startswith(prefix)]
        return out[:limit]

    # ── recherche ───────────────────────────────────────────────────────────
    def search(self, text: str | Query, limit: int = 0) -> list[Doc]:
        q = parse(text) if isinstance(text, str) else text
        results: list[tuple[float, Doc]] = []
        for d in self.docs:
            score = self._score(d, q)
            if score is not None:
                results.append((score, d))
        if q.sort == "name":
            results.sort(key=lambda r: r[1].name_l)
        elif q.sort == "recent":
            results.sort(key=lambda r: -r[1].order)
        else:
            results.sort(key=lambda r: (-r[0], r[1].name_l))
        cap = q.limit or limit
        docs = [d for _, d in results]
        return docs[:cap] if cap else docs

    @staticmethod
    def _score(d: Doc, q: Query) -> float | None:
        if q.states and not q.states <= d.states:
            return None
        for key, wanted in q.filters.items():
            have = getattr(d, key)
            have = (have,) if isinstance(have, str) else have
            if not any(any(w == h or (len(w) >= 3 and h.startswith(w)) for h in have) for w in wanted):
                return None
        for bad in q.excluded:
            if bad in d.hay:
                return None
        score = 0.0
        for phrase in q.phrases:
            if phrase not in d.hay:
                return None
            score += 6 if phrase in d.name_l else 3
        for word in q.words:
            if word in d.name_l:
                score += 10 if d.name_l.startswith(word) else 7
            elif word in d.tags:
                score += 6
            elif word in d.hay:
                score += 3
            elif len(word) >= 5 and difflib.get_close_matches(word, d.tokens, n=1, cutoff=0.8):
                score += 1.5                                   # faute de frappe
            else:
                return None
        return score
