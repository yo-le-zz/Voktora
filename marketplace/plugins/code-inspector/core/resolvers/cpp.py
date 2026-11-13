"""Résolution C / C++ : #include, héritage, méthodes de classe, fonctions (même fichier / en-tête inclus / unique)."""

from __future__ import annotations

import posixpath

from ..model import CALLS, CERTAIN, IMPORTS, INHERITS, PROBABLE, UNKNOWN

STD_PREFIX = ("std::", "boost::")
SKIP = {"printf", "fprintf", "snprintf", "malloc", "free", "calloc", "realloc", "memcpy", "memset", "strlen", "strcmp", "strncmp",
        "exit", "abort", "assert", "fopen", "fclose", "fread", "fwrite", "puts", "getchar", "push_back", "pop_back", "size",
        "begin", "end", "empty", "clear", "insert", "erase", "find", "c_str", "emplace_back", "at", "front", "back", "swap",
        "move", "make_shared", "make_unique", "get", "reset", "count", "first", "second", "min", "max", "cout", "cin"}


def link(ctx) -> None:
    files = {p: f for p, f in ctx.files.items() if f.lang in ("c", "cpp")}
    if not files:
        return
    g = ctx.graph
    by_base: dict[str, list[str]] = {}
    for p in files:
        by_base.setdefault(posixpath.basename(p), []).append(p)

    def include_target(path: str, spec: str, system: bool) -> str | None:
        rel = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
        if rel in files:
            return rel
        hits = by_base.get(posixpath.basename(spec), [])
        hits = [h for h in hits if h.endswith(spec)] or hits
        return hits[0] if len(hits) == 1 else None

    includes: dict[str, set[str]] = {}
    for path, fr in files.items():
        inc = set()
        for imp in fr.imports:
            t = include_target(path, imp["module"], imp.get("system", False))
            if t:
                inc.add(t)
                ctx.edge(path, t, IMPORTS, CERTAIN, imp["line"], path)
            elif imp.get("system") or "/" not in imp["module"]:
                ctx.edge(path, g.ensure_external(imp["module"], fr.lang), IMPORTS, CERTAIN, imp["line"], path, "include système/externe")
        includes[path] = inc

    def closure(path: str) -> set[str]:
        seen, stack = {path}, [path]
        while stack:
            for t in includes.get(stack.pop(), ()):
                if t not in seen:
                    seen.add(t)
                    stack.append(t)
        return seen
    visible = {p: closure(p) for p in files}
    classes_by_name: dict[str, list[str]] = {}
    for fr in files.values():
        for s in fr.symbols:
            if s.kind in ("class", "struct"):
                classes_by_name.setdefault(s.name, []).append(s.id)
    bases: dict[str, list[str | None]] = {}
    for path, fr in files.items():
        for ref in fr.refs:
            if ref.kind == "inherits":
                name = ref.expr.split("::")[-1]
                cands = classes_by_name.get(name, [])
                vis = [c for c in cands if ctx.symbols[c].file in visible[path]]
                pick = vis or cands
                if len(pick) == 1:
                    bases.setdefault(ref.src, []).append(pick[0])
                    ctx.edge(ref.src, pick[0], INHERITS, CERTAIN if vis else PROBABLE, ref.line, path)
                else:
                    bases.setdefault(ref.src, []).append(None)
                    ctx.edge(ref.src, g.ensure_external(ref.expr, "cpp"), INHERITS, PROBABLE if not pick else UNKNOWN, ref.line, path,
                             "base externe ou ambiguë")

    def member(cls: str, name: str, depth: int = 0):
        f = ctx.members.get(cls, {}).get(name)
        if f:
            return f, False
        ext = False
        if depth < 8:
            for b in bases.get(cls, []):
                if b is None:
                    ext = True
                    continue
                f, e = member(b, name, depth + 1)
                if f:
                    return f, False
                ext = ext or e
        return None, ext

    for path, fr in files.items():
        for ref in fr.refs:
            if ref.kind != "call":
                continue
            caller = ctx.symbols.get(ref.src)
            expr = ref.expr
            if expr.startswith(STD_PREFIX) or expr in SKIP:
                continue
            last = expr.split("::")[-1].split(".")[-1]
            if last in SKIP:
                continue
            cls = caller.parent if caller is not None and caller.kind == "method" else None
            parts = expr.split("::")
            if len(parts) >= 2 and "." not in expr:                           # Classe::fonction
                cname = parts[-2]
                cands = classes_by_name.get(cname, [])
                for c in cands:
                    f, _ = member(c, parts[-1])
                    if f:
                        ctx.edge(ref.src, f, CALLS, CERTAIN if len(cands) == 1 else PROBABLE, ref.line, path)
                        break
                else:
                    fn = [x for x in ctx.funcs_by_name.get(parts[-1], [])]
                    if len(fn) == 1:
                        ctx.edge(ref.src, fn[0], CALLS, PROBABLE, ref.line, path, "espace de noms")
                continue
            if "." in expr:                                                  # obj.méthode / obj->méthode
                recv, _, meth = expr.rpartition(".")
                if recv == "this" and cls:
                    f, ext = member(cls, meth)
                    if f:
                        ctx.edge(ref.src, f, CALLS, CERTAIN, ref.line, path)
                    continue
                for dst, cert, note in ctx.fallback_methods(meth):
                    ctx.edge(ref.src, dst, CALLS, cert, ref.line, path, note)
                continue
            name = expr
            if cls:
                f, ext = member(cls, name)
                if f:
                    ctx.edge(ref.src, f, CALLS, CERTAIN, ref.line, path)
                    continue
            cands = [c for c in ctx.funcs_by_name.get(name, []) if ctx.symbols[c].lang in ("c", "cpp")]
            same = [c for c in cands if ctx.symbols[c].file == path]
            if same:
                ctx.edge(ref.src, same[0], CALLS, CERTAIN, ref.line, path)
                continue
            vis = [c for c in cands if ctx.symbols[c].file in visible[path]]
            if len(vis) == 1:
                ctx.edge(ref.src, vis[0], CALLS, CERTAIN, ref.line, path, "défini dans un en-tête inclus")
            elif len(cands) == 1:
                ctx.edge(ref.src, cands[0], CALLS, PROBABLE, ref.line, path, "seule définition portant ce nom (déclarée via un en-tête)")
            elif len(cands) > 1:
                g.ensure_unknown(name, f"{len(cands)} définitions portent ce nom")
                ctx.edge(ref.src, "unknown:" + name, CALLS, UNKNOWN, ref.line, path, f"{len(cands)} définitions")
            else:
                macro = [c for c in ctx.funcs_by_name.get(name, [])]
                if macro:
                    ctx.edge(ref.src, macro[0], CALLS, PROBABLE, ref.line, path, "macro")
