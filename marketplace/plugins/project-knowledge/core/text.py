"""Découpage en mots (camelCase, snake_case, accents) et mots vides."""

from __future__ import annotations

import re
import unicodedata

WORD = re.compile(r"[A-Za-z0-9_]+")
CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
STOP = frozenset(["le", "la", "les", "un", "une", "des", "du", "de", "et", "en", "au", "aux", "ce", "ces", "cet", "est", "sont", "pour", "par", "sur", "dans", "avec", "sans", "que", "qui", "ne", "pas", "plus", "ou", "où", "se", "sa", "son", "ses", "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "is", "are", "be", "as", "at", "by", "it", "this", "that", "from", "not", "if", "else", "return", "self", "def", "class", "fn", "let", "var", "const"])


def fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def tokens(text: str, keep_stop: bool = False) -> list[str]:
    out: list[str] = []
    for w in WORD.findall(fold(text)):
        parts = [p for p in re.split(r"_+", w) if p]
        for p in parts:
            pieces = [x.lower() for x in CAMEL.findall(p)]
            if len(pieces) > 1:
                out.append(p.lower())
            out += pieces or [p.lower()]
    return out if keep_stop else [t for t in out if t not in STOP and len(t) > 1]
