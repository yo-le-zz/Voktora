"""Variables `{{nom}}` : environnement actif, collection, valeurs extraites des réponses (chaînage), variables intégrées."""

from __future__ import annotations

import re
import time
import uuid

PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_.\-$]+)\s*\}\}")


def builtins() -> dict:
    return {"$timestamp": str(int(time.time())), "$uuid": str(uuid.uuid4()), "$isoTimestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def substitute(text: str, *scopes: dict) -> tuple[str, list[str]]:
    """Remplace `{{x}}` en cherchant dans les portées (la première gagne). Retourne (texte, variables introuvables)."""
    missing: list[str] = []
    live = builtins()

    def repl(m):
        name = m.group(1)
        for scope in (*scopes, live):
            if name in scope:
                return str(scope[name])
        missing.append(name)
        return m.group(0)
    out = PATTERN.sub(repl, text or "")
    return out, list(dict.fromkeys(missing))


def used(text: str) -> set[str]:
    return set(PATTERN.findall(text or ""))
