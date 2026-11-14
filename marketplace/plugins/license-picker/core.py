"""License Picker — logique pure : textes de licence, année/titulaire, en-têtes SPDX par type de fichier."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

_DATA: dict | None = None

COMMENT_STYLES = {
    "Python / Shell / YAML / TOML": ("# ", ""), "C / C++ / Java / JS / TS / Rust / Go": ("// ", ""),
    "HTML / XML / Markdown": ("<!-- ", " -->"), "SQL / Lua / Haskell": ("-- ", ""), "CSS": ("/* ", " */"),
}


def licenses() -> dict:
    global _DATA
    if _DATA is None:
        _DATA = json.loads((Path(__file__).parent / "resources" / "licenses.json").read_text(encoding="utf-8"))
    return _DATA


def has_text(key: str) -> bool:
    return "text" in licenses()[key]


def render(key: str, holder: str, year: str | int | None = None) -> str:
    """Texte complet de la licence, prêt à écrire dans LICENSE (ValueError si seul un lien officiel est fourni)."""
    entry = licenses()[key]
    if "text" not in entry:
        raise ValueError(f"{entry['name']} : le texte officiel est long — utilisez le lien {entry['url']}")
    holder = (holder or "").strip() or "Les auteurs"
    return entry["text"].replace("{year}", str(year or date.today().year)).replace("{holder}", holder)


def spdx_id(key: str) -> str:
    return licenses()[key].get("spdx", key)


def spdx_header(key: str, style: str, holder: str = "", year: str | int | None = None) -> str:
    prefix, suffix = COMMENT_STYLES[style]
    lines = []
    if holder.strip():
        lines.append(f"Copyright (c) {year or date.today().year} {holder.strip()}")
    lines.append(f"SPDX-License-Identifier: {spdx_id(key)}")
    return "\n".join(prefix + line + suffix for line in lines) + "\n"


def detect(text: str) -> str | None:
    """Reconnaît une licence déjà présente (d'après sa première ligne) : clé du catalogue ou None."""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "").lower()
    table = {"mit license": "MIT", "bsd 2-clause license": "BSD-2-Clause", "bsd 3-clause license": "BSD-3-Clause",
             "isc license": "ISC", "this is free and unencumbered software released into the public domain.": "Unlicense",
             "apache license": "Apache-2.0", "mozilla public license version 2.0": "MPL-2.0"}
    for head, key in table.items():
        if first.startswith(head):
            return key
    if "gnu general public license" in first:
        return "GPL-3.0-or-later"
    if "gnu lesser general public license" in first:
        return "LGPL-3.0-or-later"
    if "gnu affero general public license" in first:
        return "AGPL-3.0-or-later"
    return None
