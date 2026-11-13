"""Python × Rust : PyO3 / maturin / ctypes-cffi / sous-processus. Ajoute des arêtes `ffi` (direction dans la note).

  python → rust : import du module natif puis appel d'une #[pyfunction] / d'une #[pyclass] (certain) ; méthode d'une
                  instance dont le type vient d'un constructeur natif (probable) ; ctypes/cffi vers `extern "C"` ; subprocess
  rust → python : `py.import("m")`, `.getattr("f")`, `.call_method("m", …)` avec nom littéral (probable si la cible existe,
                  sinon inconnu) ; rappels Python reçus en paramètre : inconnu."""

from __future__ import annotations

import posixpath
import re

from ..core.model import CALLS, CERTAIN, FFI, PROBABLE, UNKNOWN


def native_modules(files) -> dict:
    """{nom importable: {"crate_dir", "functions": {py_name: id}, "classes": {py_name: id}, "methods": {class_id: {name: id}}}}"""
    mods: dict[str, dict] = {}
    cargo_dirs = {posixpath.dirname(p): f.info["cargo"] for p, f in files.items() if p.endswith("Cargo.toml") and f.info.get("cargo")}
    maturin = {posixpath.dirname(p): f.info["maturin"] for p, f in files.items() if f.info.get("maturin")}
    for path, fr in files.items():
        if fr.lang != "rust":
            continue
        pyo3_syms = [s for s in fr.symbols if s.meta.get("pyo3")]
        if not pyo3_syms:
            continue
        cdir = next((d for d in sorted(cargo_dirs, key=len, reverse=True) if not d or path.startswith(d + "/")), "")
        names = {s.meta.get("py_name", s.name) for s in pyo3_syms if s.meta["pyo3"] == "pymodule"}
        info = cargo_dirs.get(cdir, {})
        if info.get("lib_name"):
            names.add(info["lib_name"])
        mt = maturin.get(cdir) or next((v for d, v in maturin.items() if d and cdir.startswith(d)), None)
        if mt and mt.get("module_name"):
            names.add(mt["module_name"].split(".")[-1])
        for n in names:
            m = mods.setdefault(n, {"crate_dir": cdir, "functions": {}, "classes": {}, "methods": {}, "files": set()})
            m["files"].add(path)
            for s in pyo3_syms:
                if s.meta["pyo3"] == "pyfunction":
                    m["functions"][s.meta.get("py_name", s.name)] = s.id
                elif s.meta["pyo3"] == "pyclass":
                    m["classes"][s.meta.get("py_name", s.name)] = s.id
            for s in fr.symbols:
                if s.kind == "method" and s.meta.get("pyo3") == "pymethod":
                    m["methods"].setdefault(s.parent, {})[s.meta.get("py_name", s.name)] = s.id
    return mods


def link(ctx) -> dict:
    files, g = ctx.files, ctx.graph
    py_files = {p: f for p, f in files.items() if f.lang == "python"}
    rs_files = {p: f for p, f in files.items() if f.lang == "rust"}
    result = {"native_modules": [], "python_to_rust": 0, "rust_to_python": 0, "extern_c": 0, "subprocess": 0}
    if not py_files or not rs_files:
        return result
    mods = native_modules(files)
    result["native_modules"] = sorted(mods)
    # pymodule → éléments exposés
    for path, fr in rs_files.items():
        for reg in fr.info.get("py_registers", []):
            for fn in reg["functions"]:
                for sid in ctx.funcs_by_name.get(fn, []):
                    if ctx.symbols[sid].file == path or ctx.symbols[sid].meta.get("pyo3"):
                        ctx.edge(reg["fn"], sid, FFI, CERTAIN, 0, path, "exposé à Python (add_function)")
            for cl in reg["classes"]:
                for sid in ctx.types_by_name.get(cl, []):
                    ctx.edge(reg["fn"], sid, FFI, CERTAIN, 0, path, "classe exposée à Python (add_class)")
    ext_cls: dict[str, str] = {}
    for mname, m in mods.items():
        for cname, cid in m["classes"].items():
            ext_cls[f"{mname}.{cname}"] = cid
    # python → rust (modules natifs)
    for path, fr in py_files.items():
        alias_member: dict[str, tuple[str, str]] = {}            # nom lié → (module natif, membre|"")
        for imp in fr.imports:
            parts = [p for p in imp["module"].split(".") if p]
            native = next((n for n in mods if n in parts[-1:]), None)
            if native and imp["names"]:
                for name, alias in imp["names"]:
                    alias_member[alias or name] = (native, name)
            elif native:
                alias_member[imp["alias"] or imp["module"].split(".")[0]] = (native, "")
                alias_member[imp["module"]] = (native, "")
            elif not imp["module"] and imp["level"]:
                for name, alias in imp["names"]:
                    if name in mods:
                        alias_member[alias or name] = (name, "")
        if not alias_member:
            continue
        for ref in fr.refs:
            if ref.kind != "call":
                continue
            parts = ref.expr.split(".")
            head = parts[0]
            if head not in alias_member and ref.expr not in alias_member:
                caller = ctx.symbols.get(ref.src)
                if caller is not None and len(parts) == 2 and head in (caller.meta.get("local_types") or {}):
                    ctor = caller.meta["local_types"][head]
                    cparts = ctor.split(".")
                    entry = alias_member.get(cparts[0])
                    if entry:
                        mod, member = entry
                        cname = cparts[1] if (not member and len(cparts) > 1) else (member or "")
                        cid = mods[mod]["classes"].get(cname)
                        mid = mods[mod]["methods"].get(cid, {}).get(parts[1]) if cid else None
                        if mid:
                            ctx.edge(ref.src, mid, FFI, PROBABLE, ref.line, path,
                                     f"python→rust : méthode de {cname} (type déduit de {ctor}(…))")
                            result["python_to_rust"] += 1
                continue
            mod, member = alias_member.get(head, (None, ""))
            if mod is None:
                continue
            m = mods[mod]
            if member:                                              # from native import f / Classe
                if len(parts) == 1:
                    sid = m["functions"].get(member)
                    cid = m["classes"].get(member)
                    if sid:
                        ctx.edge(ref.src, sid, FFI, CERTAIN, ref.line, path, "python→rust : #[pyfunction]")
                        result["python_to_rust"] += 1
                    elif cid:
                        ctx.edge(ref.src, cid, FFI, CERTAIN, ref.line, path, "python→rust : #[pyclass] (constructeur)")
                        result["python_to_rust"] += 1
                elif len(parts) == 2 and (cid := m["classes"].get(member)):
                    mid = m["methods"].get(cid, {}).get(parts[1])
                    if mid:
                        ctx.edge(ref.src, mid, FFI, CERTAIN, ref.line, path, "python→rust : méthode statique/de classe")
                        result["python_to_rust"] += 1
            elif len(parts) >= 2:                                   # module.f / module.Classe
                sid = m["functions"].get(parts[1])
                cid = m["classes"].get(parts[1])
                if sid:
                    ctx.edge(ref.src, sid, FFI, CERTAIN, ref.line, path, "python→rust : #[pyfunction]")
                    result["python_to_rust"] += 1
                elif cid:
                    ctx.edge(ref.src, cid, FFI, CERTAIN, ref.line, path, "python→rust : #[pyclass] (constructeur)")
                    result["python_to_rust"] += 1
                elif parts[1] not in ("__name__", "__file__"):
                    nid = g.ensure_unknown(f"{mod}.{parts[1]}", "attribut du module natif non trouvé parmi les #[pyfunction]/#[pyclass]")
                    ctx.edge(ref.src, nid, FFI, UNKNOWN, ref.line, path, "python→rust : cible introuvable")
    # ctypes / cffi → extern "C"
    cdylibs = {f.info["cargo"]["lib_name"]: p for p, f in files.items() if p.endswith("Cargo.toml")
               and "cdylib" in (f.info.get("cargo", {}).get("crate_type") or [])}
    extern_c = {s.name: s for fr in rs_files.values() for s in fr.symbols if s.meta.get("extern_c")}
    for path, fr in py_files.items():
        for load in fr.info.get("native_loads", []):
            stem = re.sub(r"^lib|\.(so|dll|dylib)(\.\d+)*$", "", posixpath.basename(load["lib"]))
            known = stem.replace("-", "_") in cdylibs
            var = load["var"]
            for ref in fr.refs:
                if ref.kind == "call" and var and ref.expr.startswith(var + ".") and ref.expr.count(".") == 1:
                    fn = extern_c.get(ref.expr.split(".")[1])
                    if fn is not None:
                        ctx.edge(ref.src, fn.id, FFI, CERTAIN if known else PROBABLE, ref.line, path,
                                 "python→rust : ctypes/cffi vers extern \"C\"" + ("" if known else " (bibliothèque non identifiée)"))
                        result["extern_c"] += 1
        bins = {b: p for p, f in files.items() if p.endswith("Cargo.toml") for b in (f.info.get("cargo", {}).get("bins") or [])}
        for call in fr.info.get("subprocess_cmds", []):
            name = posixpath.basename(call["cmd"])
            if name in bins:
                mains = [s for s in ctx.symbols.values() if s.name == "main" and s.lang == "rust" and s.file.startswith(posixpath.dirname(bins[name]))]
                if mains:
                    ctx.edge(call["owner"], mains[0].id, FFI, PROBABLE, call["line"], path, "python→rust : sous-processus vers le binaire")
                    result["subprocess"] += 1
    # rust → python
    for path, fr in rs_files.items():
        calls = fr.info.get("python_calls", [])
        lines = fr.info.get("python_callbacks", [])
        funcs = [s for s in fr.symbols if s.kind in ("function", "method") and s.end_line]
        for entry in calls:
            owner = next((s for s in funcs if s.line <= entry["line"] <= s.end_line), None)
            if owner is None:
                continue
            target = _python_target(ctx, py_files, entry)
            if target:
                ctx.edge(owner.id, target[0], FFI, target[1], entry["line"], path, f"rust→python : {entry['kind']}(\"{entry['name']}\")")
            else:
                nid = g.ensure_unknown(f"python:{entry['name']}", "nom Python utilisé par Rust, non trouvé dans le projet")
                ctx.edge(owner.id, nid, FFI, UNKNOWN, entry["line"], path, f"rust→python : {entry['kind']}(\"{entry['name']}\")")
            result["rust_to_python"] += 1
        for ln in lines:
            owner = next((s for s in funcs if s.line <= ln <= s.end_line), None)
            if owner is not None and not any(e.src == owner.id and e.kind == FFI and e.dst.startswith("unknown:python") for e in g.out_edges(owner.id)):
                nid = g.ensure_unknown("python:callback", "code Python appelé depuis Rust : la cible dépend de l'objet reçu à l'exécution")
                ctx.edge(owner.id, nid, FFI, UNKNOWN, ln, path, "rust→python : appel d'un objet Python (GIL)")
                result["rust_to_python"] += 1
    return result


def _python_target(ctx, py_files, entry):
    name = entry["name"]
    if entry["kind"] in ("import", "import_bound"):
        dotted = name
        for p in py_files:
            stem = p[:-3].replace("/", ".").removesuffix(".__init__")
            if stem == dotted or stem.endswith("." + dotted):
                return p, PROBABLE
        return None
    cands = [sid for sid in ctx.funcs_by_name.get(name, []) + ctx.methods_by_name.get(name, []) if ctx.symbols[sid].lang == "python"]
    return (cands[0], PROBABLE) if len(cands) == 1 else None


__all__ = ["CALLS", "link", "native_modules"]
