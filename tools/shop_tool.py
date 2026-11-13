#!/usr/bin/env python3
"""
Outil des boutiques d'apparence de Voktora (CI et contributeurs) — aucune dépendance, sans lancer l'application.

  python tools/shop_tool.py validate           # vérifie tous les objets (extensions, SVG/QSS, JSON)
  python tools/shop_tool.py build-index        # régénère marketplace/shops/<type>/index.json (empreintes SHA-256)
  python tools/shop_tool.py new themes mon-theme   # modèle d'objet

Un objet = un dossier `marketplace/shops/<type>/items/<id>/` avec `item.json` + ses fichiers (theme.json,
*.svg, *.qss). Les règles de sécurité sont celles de l'application (voktora/shops.py, chargé tel quel).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOPS = ROOT / "marketplace" / "shops"


def _load_shops():
    sys.modules.setdefault("core", types.ModuleType("core"))         # shops.py n'utilise core que dans ses fonctions
    spec = importlib.util.spec_from_file_location("voktora_shops", ROOT / "voktora" / "shops.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["voktora_shops"] = module           # requis par @dataclass
    spec.loader.exec_module(module)
    return module


shops = _load_shops()


def _items(kind: str) -> list[Path]:
    base = SHOPS / kind / "items"
    return sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []


def check_item(kind: str, folder: Path) -> tuple[dict, list[str]]:
    errors: list[str] = []
    try:
        meta = json.loads((folder / "item.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, [f"{folder.name} : item.json illisible ({exc})"]
    if meta.get("id") != folder.name:
        errors.append(f"{folder.name} : « id » doit valoir le nom du dossier.")
    files: dict[str, str] = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name == "item.json":
            continue
        rel = path.relative_to(folder).as_posix()
        try:
            name = shops.safe_name(kind, rel)
            data = path.read_bytes()
            if len(data) > shops.MAX_FILE_BYTES:
                raise shops.ShopError(f"{rel} : trop volumineux")
            shops.check_content(kind, name, data)
            files[name] = hashlib.sha256(data).hexdigest()
        except shops.ShopError as exc:
            errors.append(f"{folder.name} : {exc}")
    if kind == "themes" and "theme.json" not in files:
        errors.append(f"{folder.name} : theme.json manquant.")
    if kind == "themes" and "theme.json" in files:
        colors = json.loads((folder / "theme.json").read_text(encoding="utf-8")).get("colors")
        if not isinstance(colors, dict) or not colors.get("base"):
            errors.append(f"{folder.name} : theme.json doit contenir « colors » avec au moins « base ».")
    if not files:
        errors.append(f"{folder.name} : aucun fichier.")
    meta["files"] = files
    return meta, errors


def build(kind: str) -> tuple[dict, list[str]]:
    entries, errors = [], []
    for folder in _items(kind):
        meta, errs = check_item(kind, folder)
        errors += errs
        if not errs:
            entries.append(meta)
    return {"schema": 1, "kind": kind, "items": entries}, errors


def cmd_validate(_a) -> int:
    bad = 0
    for kind in shops.KINDS:
        _index, errors = build(kind)
        for e in errors:
            print("✗", e)
        bad += len(errors)
    print("OK" if not bad else f"{bad} problème(s)")
    return 1 if bad else 0


def cmd_build(_a) -> int:
    code = 0
    for kind in shops.KINDS:
        index, errors = build(kind)
        for e in errors:
            print("✗", e)
        code |= bool(errors)
        if not errors:
            out = SHOPS / kind / "index.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"✓ {out.relative_to(ROOT)} ({len(index['items'])} objet(s))")
    return code


def cmd_new(a) -> int:
    kind, item_id = a.kind, a.id
    if not shops.ID_RE.match(item_id):
        print("id : minuscules, chiffres et tirets.")
        return 1
    folder = SHOPS / kind / "items" / item_id
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"id": item_id, "name": item_id.replace("-", " ").title(), "version": "1.0.0", "author": "vous",
            "description": "Décrivez votre objet."}
    (folder / "item.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sample = {"themes": ("theme.json", json.dumps({"name": meta["name"], "colors": {
        "base": "#1e1e2e", "text": "#cdd6f4", "blue": "#89b4fa", "mauve": "#cba6f7", "green": "#a6e3a1",
        "red": "#f38ba8", "yellow": "#f9e2af", "primary": "#89b4fa"}}, indent=2) + "\n"),
              "icons": ("folder.svg", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                        'stroke="#a6adc8" stroke-width="1.5"><path d="M3 7h18v11H3z"/></svg>\n'),
              "styles": ("style.qss", "QPushButton { border-radius: 8px; }\n")}[kind]
    (folder / sample[0]).write_text(sample[1], encoding="utf-8")
    print(f"✓ {folder.relative_to(ROOT)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Outil des boutiques d'apparence Voktora")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    sub.add_parser("build-index").set_defaults(fn=cmd_build)
    new = sub.add_parser("new")
    new.add_argument("kind", choices=list(shops.KINDS))
    new.add_argument("id")
    new.set_defaults(fn=cmd_new)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
