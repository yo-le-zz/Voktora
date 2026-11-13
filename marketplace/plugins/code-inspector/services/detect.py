"""Langages, frameworks, points d'entrée, fichiers de test — déduits des résultats d'analyse (aucune heuristique cachée)."""

from __future__ import annotations

from collections import defaultdict

from ..core.model import FILE
from .deps_audit import ADV, norm

LANG_NAMES = {"python": "Python", "rust": "Rust", "javascript": "JavaScript", "typescript": "TypeScript", "c": "C", "cpp": "C++",
              "config": "Configuration"}
TEST_HINTS = ("test_", "_test.", "/tests/", "/test/", "conftest", ".spec.", ".test.", "tests/")


def languages(files: dict) -> list[dict]:
    loc, count = defaultdict(int), defaultdict(int)
    for fr in files.values():
        loc[fr.lang] += fr.loc
        count[fr.lang] += 1
    total = sum(v for k, v in loc.items() if k != "config") or 1
    rows = [{"lang": k, "name": LANG_NAMES.get(k, k), "files": count[k], "loc": loc[k],
             "share": round(100 * loc[k] / total, 1) if k != "config" else 0.0} for k in loc]
    rows.sort(key=lambda r: -r["loc"])
    return rows


def frameworks(deps: list[dict], graph) -> list[str]:
    found = set()
    table = ADV["frameworks"]
    for d in deps:
        label = table.get(d["ecosystem"], {}).get(norm(d["name"])) or table.get(d["ecosystem"], {}).get(d["name"].lower())
        if label:
            found.add(label)
    for n in graph.nodes.values():
        if n.kind == "external":
            root = n.name.split(".")[0].split("/")[0].lower()
            for eco in ("pypi", "npm", "crates"):
                label = table.get(eco, {}).get(root)
                if label and n.lang in {"pypi": "python", "npm": "javascript", "crates": "rust"}[eco]:
                    found.add(label)
            if n.lang in ("c", "cpp"):
                low = n.name.lower()
                for key, label in table["cmake"].items():
                    if low.startswith(key) or key in low.split("/")[0]:
                        found.add(label)
                if low.startswith(("qt", "qapplication", "qwidget")) or "/q" in low:
                    found.add("Qt")
    return sorted(found)


def entry_points(files: dict, graph) -> list[dict]:
    out = []
    for path, fr in files.items():
        e = fr.info.get("entry")
        if e:
            sym = next((s for s in fr.symbols if s.meta.get("entry")), None)
            out.append({"file": path, "symbol": sym.id if sym else path, "kind": e, "line": fr.info.get("main_line", 1),
                        "lang": fr.lang})
        for ent in fr.info.get("entries", []):
            out.append({"file": path, "symbol": path, "kind": ent["kind"], "line": 1, "lang": fr.lang, "name": ent.get("name", ""),
                        "target": ent.get("target", "")})
        for s in fr.symbols:
            if s.meta.get("bridge") in ("tokio::main", "async_std::main"):
                out.append({"file": path, "symbol": s.id, "kind": s.meta["bridge"], "line": s.line, "lang": "rust"})
    seen, rows = set(), []
    for r in out:
        key = (r["file"], r["kind"], r.get("name", ""), r["symbol"])
        if key not in seen:
            seen.add(key)
            rows.append(r)
    # cibles de console_scripts « paquet.module:fonction » → symbole
    for r in rows:
        if r["kind"] == "console_script" and ":" in r.get("target", ""):
            mod, _, fn = r["target"].partition(":")
            for s in graph.nodes.values():
                if s.name == fn and s.kind == "function" and s.file[:-3].replace("/", ".").endswith(mod):
                    r["symbol"], r["line"] = s.id, s.line
                    break
    return rows


def test_files(files: dict) -> list[str]:
    return sorted(p for p in files if any(h in p.lower() for h in TEST_HINTS))


__all__ = ["FILE"]
