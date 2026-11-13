"""Exports spécifiques : Python, Rust, projets mixtes Python × Rust (données + rendu Markdown / HTML / JSON)."""

from __future__ import annotations

import json
from collections import defaultdict
from html import escape

from ..core.model import FFI
from .common import md_table


def python_data(a) -> dict:
    g = a.graph
    modules = []
    for path, fr in sorted(a.files.items()):
        if fr.lang != "python":
            continue
        syms = [s for s in fr.symbols if not s.id.endswith("::<module>")]
        internal = sorted({e.dst for e in g.out_edges(path, {"imports"}) if g.nodes[e.dst].kind == "file"})
        external = sorted({g.nodes[e.dst].name for e in g.out_edges(path, {"imports"}) if g.nodes[e.dst].kind == "external"})
        classes = [{"name": s.name, "line": s.line, "bases": [g.nodes[e.dst].name for e in g.out_edges(s.id, {"inherits"})],
                    "decorators": s.decorators, "methods": [m.name for m in syms if m.parent == s.id]} for s in syms if s.kind == "class"]
        funcs = [{"name": s.name, "line": s.line, "signature": s.signature, "decorators": s.decorators, "complexity": s.complexity}
                 for s in syms if s.kind == "function"]
        modules.append({"file": path, "doc": g.nodes[path].doc, "imports_internal": internal, "imports_external": external,
                        "classes": classes, "functions": funcs})
    decorators = defaultdict(list)
    for m in modules:
        for item in [*m["functions"], *m["classes"]]:
            for d in item["decorators"]:
                decorators[d.split("(")[0]].append(f"{m['file']}:{item['name']}")
    deps = [{"from": m["file"], "to": t} for m in modules for t in m["imports_internal"]]
    return {"kind": "python", "modules": modules, "decorators": dict(decorators), "module_dependencies": deps}


def rust_data(a) -> dict:
    g = a.graph
    crates = []
    for path, fr in a.files.items():
        if path.endswith("Cargo.toml") and fr.info.get("cargo"):
            crates.append({"manifest": path, **fr.info["cargo"], "dependencies": [d["name"] for d in fr.info.get("dependencies", [])]})
    files = []
    for path, fr in sorted(a.files.items()):
        if fr.lang != "rust":
            continue
        syms = [s for s in fr.symbols if not s.id.endswith("::<module>")]
        files.append({"file": path,
                      "modules": [s.name for s in syms if s.kind == "module"],
                      "functions": [{"name": s.name, "signature": s.signature, "line": s.line, "unsafe": "unsafe" in s.signature} for s in syms
                                    if s.kind == "function"],
                      "types": [{"name": s.name, "kind": s.kind, "line": s.line} for s in syms if s.kind in ("struct", "enum")],
                      "traits": [{"name": s.name, "line": s.line, "methods": [m.name for m in syms if m.parent == s.id]} for s in syms if s.kind == "trait"],
                      "macros": [s.name for s in syms if s.kind == "macro"],
                      "impls": [{"type": g.nodes[e.src].name, "trait": g.nodes[e.dst].name, "line": e.line} for e in g.edges
                                if e.kind == "implements" and g.nodes.get(e.src) and g.nodes[e.src].file == path]})
    return {"kind": "rust", "crates": crates, "files": files}


def mixed_data(a) -> dict:
    g = a.graph
    bridges = []
    for e in g.edges:
        if e.kind != FFI:
            continue
        s, d = g.nodes.get(e.src), g.nodes.get(e.dst)
        if s and d:
            direction = "rust→python" if s.lang == "rust" and (d.lang == "python" or d.id.startswith("unknown:python")) else \
                "python→rust" if s.lang == "python" else "interne (exposition)"
            bridges.append({"from": e.src, "to": e.dst, "direction": direction, "certainty": e.certainty, "note": e.note, "line": e.line,
                            "file": e.file})
    return {"kind": "mixed", "native_modules": a.report["ffi"].get("native_modules", []), "summary": a.report["ffi"], "bridges": bridges,
            "maturin": [{"file": p, **f.info["maturin"]} for p, f in a.files.items() if f.info.get("maturin")],
            "extern_c": [s.id for s in g.nodes.values() if s.meta.get("extern_c")]}


DATA = {"python": python_data, "rust": rust_data, "mixed": mixed_data}
TITLES = {"python": "Export Python", "rust": "Export Rust", "mixed": "Export Python × Rust"}


def render_md(data: dict) -> str:
    k = data["kind"]
    out = [f"# {TITLES[k]}", ""]
    if k == "python":
        out += [md_table(["Module", "Imports internes", "Imports externes", "Classes", "Fonctions"],
                         [[m["file"], len(m["imports_internal"]), ", ".join(m["imports_external"][:8]), len(m["classes"]), len(m["functions"])]
                          for m in data["modules"]]), ""]
        for m in data["modules"]:
            out += [f"## {m['file']}", m["doc"] or "", ""]
            for c in m["classes"]:
                out.append(f"- **classe `{c['name']}`** (l.{c['line']}) bases : {', '.join(c['bases']) or '—'} ; décorateurs : "
                           f"{', '.join(c['decorators']) or '—'} ; méthodes : {', '.join(c['methods']) or '—'}")
            for f in m["functions"]:
                out.append(f"- `{f['signature']}` (l.{f['line']}, complexité {f['complexity']})")
            out.append("")
        if data["decorators"]:
            out += ["## Décorateurs", "", md_table(["Décorateur", "Utilisé sur"], [[k2, ", ".join(v[:6])] for k2, v in sorted(data["decorators"].items())]), ""]
    elif k == "rust":
        for c in data["crates"]:
            out += [f"## Caisse `{c['package']}` {c['version']}", f"Types : {', '.join(c['crate_type']) or 'lib'} ; dépendances : "
                    f"{', '.join(c['dependencies']) or '—'}", ""]
        for f in data["files"]:
            out += [f"### {f['file']}", ""]
            out += [f"- modules : {', '.join(f['modules']) or '—'}", f"- types : {', '.join(t['name'] for t in f['types']) or '—'}",
                    f"- traits : {', '.join(t['name'] for t in f['traits']) or '—'}", f"- macros : {', '.join(f['macros']) or '—'}"]
            out += [f"- impl `{i['trait']}` pour `{i['type']}` (l.{i['line']})" for i in f["impls"]]
            out += [f"- `{fn['signature']}` (l.{fn['line']})" for fn in f["functions"]]
            out.append("")
    else:
        out += [f"Modules natifs : {', '.join(data['native_modules']) or '—'}", ""]
        out += [md_table(["Direction", "De", "Vers", "Certitude", "Détail"],
                         [[b["direction"], b["from"], b["to"], b["certainty"], b["note"]] for b in data["bridges"]])
                if data["bridges"] else "_Aucun pont détecté._", ""]
        if data["maturin"]:
            out += ["## maturin", "", md_table(["Fichier", "Module", "Manifeste"], [[m["file"], m["module_name"], m["manifest_path"]] for m in data["maturin"]]), ""]
    return "\n".join(out) + "\n"


def render_html(data: dict) -> str:
    md = render_md(data)
    body = "<br>".join(escape(line) for line in md.splitlines())
    return (f"<!doctype html><meta charset='utf-8'><title>{TITLES[data['kind']]}</title>"
            "<style>body{font:14px system-ui;max-width:1000px;margin:2em auto;padding:0 1em;line-height:1.5}</style>"
            f"<pre style='white-space:pre-wrap;font:13px ui-monospace,monospace'>{body}</pre>")


def export(a, kind: str, path, fmt: str = "md") -> None:
    data = DATA[kind](a)
    text = json.dumps(data, ensure_ascii=False, indent=1) if fmt == "json" else render_html(data) if fmt == "html" else render_md(data)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
