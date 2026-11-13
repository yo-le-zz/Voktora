"""Listes de noms (fonctions dynamiques, méthodes courantes…) lues dans resources/names.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def names() -> dict:
    return json.loads((Path(__file__).resolve().parent.parent / "resources" / "names.json").read_text(encoding="utf-8"))
