#!/usr/bin/env python3
"""Génère les données JSON du site statique (WebSite/data/).

Usage :
    python tools/gen_site_data.py            # écrit plugins.json et changelog.json
    python tools/gen_site_data.py --check    # échoue si les fichiers ne sont plus à jour

Sources (jamais modifiées) :
    marketplace/index.json        -> WebSite/data/plugins.json
    marketplace/shops/*/index.json (compteurs thèmes / icônes / styles)
    CHANGELOG.md                  -> WebSite/data/changelog.json

À relancer après chaque retrait ou ajout de plugin, et à chaque nouvelle entrée du CHANGELOG.
Le site charge ces fichiers au chargement de la page : aucune étape de build.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "WebSite" / "data"
MAX_VERSIONS = 12

_VERSION_RE = re.compile(r"^## \[(?P<v>[^\]]+)\]\s*(?:[—-]\s*(?P<d>\d{4}-\d{2}-\d{2}))?")
_EMOJI_RE = re.compile(r"^[^\w\[(`*]+")


def build_plugins() -> dict:
    data = json.loads((ROOT / "marketplace" / "index.json").read_text(encoding="utf-8"))
    plugins = [
        {
            "id": p["id"],
            "name": p.get("name") or p["id"],
            "lang": p.get("lang", "python"),
            "description": p.get("description", ""),
            "tags": list(p.get("tags", [])),
            "version": p.get("version", ""),
            "tier": p.get("tier", ""),
        }
        for p in data.get("plugins", [])
    ]
    plugins.sort(key=lambda p: p["name"].lower())
    shops = {}
    for kind in ("themes", "icons", "styles"):
        idx = ROOT / "marketplace" / "shops" / kind / "index.json"
        shops[kind] = len(json.loads(idx.read_text(encoding="utf-8")).get("items", [])) if idx.is_file() else 0
    return {"count": len(plugins), "shops": shops, "plugins": plugins}


def build_changelog() -> dict:
    entries: list[dict] = []
    section: dict | None = None
    entry: dict | None = None
    for raw in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        m = _VERSION_RE.match(raw)
        if m:
            if len(entries) >= MAX_VERSIONS:
                break
            entry = {"version": m["v"], "date": m["d"] or "", "sections": []}
            entries.append(entry)
            section = None
            continue
        if entry is None:
            continue
        if raw.startswith("### "):
            title = _EMOJI_RE.sub("", raw[4:]).strip()
            section = {"title": title, "items": []}
            entry["sections"].append(section)
        elif raw.startswith("---"):
            continue
        elif raw.startswith(("- ", "* ")):
            if section is None:
                section = {"title": "", "items": []}
                entry["sections"].append(section)
            section["items"].append(raw[2:].strip())
        elif raw.startswith("  ") and raw.strip() and section and section["items"]:
            section["items"][-1] += " " + raw.strip()
    return {"versions": entries}


def render(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="ne rien écrire, vérifier la fraîcheur")
    args = ap.parse_args(argv)
    targets = {"plugins.json": render(build_plugins()), "changelog.json": render(build_changelog())}
    stale = []
    for name, text in targets.items():
        path = OUT / name
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            OUT.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"écrit {path.relative_to(ROOT)}")
    if stale:
        print("périmé : " + ", ".join(stale) + " (relancez tools/gen_site_data.py)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
