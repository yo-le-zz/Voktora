"""Documentation d'API interne (Markdown) générée depuis les symboles publics."""

from __future__ import annotations


def module_doc(rel: str, f: dict) -> str:
    syms = [s for s in f["symbols"] if s["public"] and s["kind"] != "heading"]
    if not syms:
        return ""
    out = [f"### `{rel}`", "", f"_{f['role']} · {f['lang']} · {f['loc']} lignes_", ""]
    for s in syms:
        indent = "  " if s["parent"] else ""
        doc = f" — {s['doc']}" if s["doc"] else ""
        out.append(f"{indent}- `{s['signature']}` (ligne {s['line']}){doc}")
    out.append("")
    return "\n".join(out)


def api_markdown(index, only_roles: tuple = ("code", "service", "modèle", "utilitaire", "interface", "entrée")) -> str:
    parts = ["# Documentation de l'API interne", "", "_Générée automatiquement depuis les symboles publics ; les docstrings (Python) fournissent les descriptions._", ""]
    parts += [m for rel, f in sorted(index.files.items()) if f["role"] in only_roles if (m := module_doc(rel, f))]
    return "\n".join(parts)
