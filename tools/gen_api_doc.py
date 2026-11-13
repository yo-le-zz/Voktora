#!/usr/bin/env python3
"""Génère doc/plugins/API_REFERENCE.md et ICONS.md depuis le code (AST) : la doc ne peut pas dériver de l'API.

    python tools/gen_api_doc.py            # écrit les fichiers
    python tools/gen_api_doc.py --check    # échoue si les fichiers sont périmés (CI)
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "voktora" / "plugins"
OUT = ROOT / "doc" / "plugins"
FILES = [("runtime.py", "PluginAPI", "Base"), ("api_ext.py", "ExtendedAPI", "Extensions (API 2–4)"),
         ("api_more.py", "MoreAPI", "API 5 — fichiers, journal, tâches, dialogues, IA, boutiques"),
         ("options.py", "PluginOptions", "Options (api.options)")]


def methods(path: Path, cls: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for f in node.body:
                if isinstance(f, ast.FunctionDef) and not f.name.startswith("_"):
                    yield f


def signature(f: ast.FunctionDef) -> str:
    args = ast.unparse(f.args)
    args = re.sub(r"^self,?\s*", "", args)
    return f"{f.name}({args})"


def permission(f: ast.FunctionDef) -> str:
    for n in ast.walk(f):
        if (isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_require" and n.args
                and isinstance(n.args[0], ast.Constant)):
            return str(n.args[0].value)
    return ""


def reference() -> str:
    out = ["# Référence de l'API des plugins", "",
           "> Fichier GÉNÉRÉ par `tools/gen_api_doc.py` depuis le code : ne le modifiez pas à la main.", "",
           "En Python : `api.nom(...)`. En JavaScript : `voktora.nomEnCamelCase(...)`. En Rust : `api.call(\"nom_en_snake\", ...)` "
           "ou les raccourcis du SDK. La colonne *Permission* est **détectée automatiquement** à partir de votre code.", ""]
    total = 0
    for filename, cls, title in FILES:
        path = PLUGINS / filename
        items = sorted(methods(path, cls), key=lambda f: f.name) if path.is_file() else []
        if not items:
            continue
        out += [f"## {title}", "", "| Méthode | Permission | Description |", "|---|---|---|"]
        for f in items:
            doc = (ast.get_docstring(f) or "").splitlines()
            summary = doc[0].replace("|", "\\|") if doc else ""
            out.append(f"| `{signature(f)}` | {permission(f) or '—'} | {summary} |")
            total += 1
        out.append("")
    out.insert(2, f"**{total} méthodes.**\n")
    return "\n".join(out)


def icons_doc() -> str:
    sys.path.insert(0, str(ROOT / "voktora"))
    import icon_catalog
    entries = icon_catalog.all_entries()
    out = ["# Icônes", "", "> Fichier GÉNÉRÉ par `tools/gen_api_doc.py`.", "",
           "Partout où un plugin accepte `icon=`, donnez l'identifiant d'une icône (ci-dessous), un emoji (converti "
           "automatiquement) ou le chemin d'un `.svg` de votre plugin. Un pack d'icônes de boutique remplace le rendu "
           "sans changer ces identifiants.", "", f"**{len(entries)} icônes.**", "", "| Identifiant | Nom |", "|---|---|"]
    out += [f"| `{e.id}` | {e.label} |" for e in sorted(entries, key=lambda e: e.id)]
    return "\n".join(out) + "\n"


def main() -> int:
    docs = {"API_REFERENCE.md": reference() + "\n", "ICONS.md": icons_doc()}
    bad = []
    for name, text in docs.items():
        target = OUT / name
        if "--check" in sys.argv:
            if not target.is_file() or target.read_text(encoding="utf-8") != text:
                bad.append(name)
        else:
            OUT.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    if bad:
        print("Périmé : " + ", ".join(bad) + " — relancez tools/gen_api_doc.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
