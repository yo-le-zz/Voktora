"""Résolution JavaScript / TypeScript : modules relatifs, imports nommés/par défaut/espace de noms, this/super, new."""

from __future__ import annotations

import posixpath

from ..data import names
from ..model import CALLS, CERTAIN, IMPLEMENTS, IMPORTS, INHERITS, PROBABLE, UNKNOWN

EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
SKIP_METHODS = set(names()["skip_js"])
GLOBALS = {"require", "setTimeout", "setInterval", "clearTimeout", "clearInterval", "fetch", "parseInt", "parseFloat", "String",
           "Number", "Boolean", "Array", "Object", "Promise", "Map", "Set", "Date", "Error", "JSON", "Math", "RegExp", "Symbol",
           "console", "alert", "isNaN", "encodeURIComponent", "decodeURIComponent", "structuredClone", "Buffer", "process", "super",
           "queueMicrotask", "requestAnimationFrame", "BigInt", "WeakMap", "WeakSet", "Proxy", "Reflect", "URL", "Intl", "Uint8Array"}


class JsResolver:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.files = {p: f for p, f in ctx.files.items() if f.lang in ("javascript", "typescript")}
        self._scope: dict[str, dict] = {}
        self.class_bases: dict[str, list[str | None]] = {}

    def module_file(self, spec: str, from_path: str) -> str | None:
        if spec.startswith((".", "/")):
            base = posixpath.normpath(posixpath.join(posixpath.dirname(from_path), spec))
        elif spec.startswith(("@/", "~/")):
            tail = spec[2:]
            hits = [p for p in self.files if p.startswith("src/") and posixpath.splitext(p[4:])[0] == posixpath.splitext(tail)[0]]
            return hits[0] if len(hits) == 1 else None
        else:
            return None
        stem = posixpath.splitext(base)[0] if base.endswith(EXTS) else base
        for cand in [base, *[stem + e for e in EXTS], *[posixpath.join(base, "index" + e) for e in EXTS]]:
            if cand in self.files:
                return cand
        return None

    def exported(self, target: str, name: str):
        top = self.ctx.top.get(target, {})
        if name == "default":
            dflt = [sid for sid in top.values() if self.ctx.symbols[sid].meta.get("default")]
            if len(dflt) == 1:
                return dflt[0], CERTAIN
            ex = [sid for sid in top.values() if self.ctx.symbols[sid].meta.get("exported")]
            if len(ex) == 1:
                return ex[0], CERTAIN
            return (next(iter(top.values())), PROBABLE) if len(top) == 1 else (None, PROBABLE)
        if name in top:
            return top[name], CERTAIN
        for imp in self.files[target].imports:                      # export { x } from './y'
            if imp.get("reexport") and any(n == name for n, _ in imp["names"]):
                t2 = self.module_file(imp["module"], target)
                if t2 and t2 != target:
                    return self.exported(t2, name)
        return None, CERTAIN

    def scope(self, path: str) -> dict:
        if path in self._scope:
            return self._scope[path]
        out: dict[str, tuple] = {}
        for imp in self.files[path].imports:
            if imp.get("reexport"):
                continue
            target = self.module_file(imp["module"], path)
            if target is None:
                for name, alias in imp["names"]:
                    out[alias or name] = ("ext", imp["module"])
                if imp["alias"]:
                    out[imp["alias"]] = ("ext", imp["module"])
                continue
            if imp["alias"]:
                out[imp["alias"]] = ("mod", target)
            for name, alias in imp["names"]:
                if imp.get("require") and name != "default" and not alias:
                    alias = name
                sid, cert = self.exported(target, name)
                bind = alias or name
                if name == "default" and not alias:
                    continue
                out[bind] = ("sym", sid, cert) if sid else ("mod", target) if name == "default" else ("missing", target, name)
        self._scope[path] = out
        return out

    def member(self, class_id: str, name: str, depth: int = 0):
        found = self.ctx.members.get(class_id, {}).get(name)
        if found:
            return found, False
        ext = False
        if depth < 8:
            for base in self.class_bases.get(class_id, []):
                if base is None:
                    ext = True
                    continue
                f, e = self.member(base, name, depth + 1)
                if f:
                    return f, False
                ext = ext or e
        return None, ext

    def lookup(self, path: str, parts: list[str]):
        head = parts[0]
        top = self.ctx.top.get(path, {})
        entry = None
        if head in top:
            entry = ("sym", top[head], CERTAIN)
        elif head in self.scope(path):
            entry = self.scope(path)[head]
        if entry is None:
            return None
        if entry[0] == "ext":
            return ("ext", entry[1] + ("." + parts[1] if len(parts) > 1 else ""), CERTAIN)
        if entry[0] == "mod":
            if len(parts) == 1:
                return ("mod", entry[1], CERTAIN)
            sid, cert = self.exported(entry[1], parts[1])
            if sid:
                return self._descend(sid, parts[2:], cert)
            return None
        if entry[0] == "sym":
            return self._descend(entry[1], parts[1:], entry[2])
        return None

    def _descend(self, sid: str, rest: list[str], cert: str):
        sym = self.ctx.symbols.get(sid)
        if sym is None:
            return None
        if not rest:
            return ("class" if sym.kind in ("class", "trait") else "func", sid, cert)
        if sym.kind == "class":
            found, ext = self.member(sid, rest[0])
            if found:
                return ("func", found, cert)
            return ("ext", f"{sym.name}.{rest[0]}", cert) if ext else None
        return None


def link(ctx) -> None:
    r = JsResolver(ctx)
    if not r.files:
        return
    g = ctx.graph
    for path, fr in r.files.items():
        for ref in fr.refs:
            if ref.kind == "inherits":
                entry = r.lookup(path, ref.expr.split("."))
                kind = INHERITS
                if entry and entry[0] == "class":
                    r.class_bases.setdefault(ref.src, []).append(entry[1])
                    ctx.edge(ref.src, entry[1], kind, entry[2], ref.line, path)
                else:
                    r.class_bases.setdefault(ref.src, []).append(None)
                    ctx.edge(ref.src, g.ensure_external(ref.expr, "javascript"), kind, CERTAIN if entry else PROBABLE, ref.line, path)
            elif ref.kind == "implements":
                entry = r.lookup(path, ref.expr.split("."))
                if entry and entry[0] == "class":
                    ctx.edge(ref.src, entry[1], IMPLEMENTS, entry[2], ref.line, path)
    for path, fr in r.files.items():
        for imp in fr.imports:
            target = r.module_file(imp["module"], path)
            if target:
                ctx.edge(path, target, IMPORTS, CERTAIN if not imp.get("dynamic") else PROBABLE, imp["line"], path,
                         "import dynamique" if imp.get("dynamic") else "")
            elif not imp["module"].startswith((".", "/")):
                pkg = "/".join(imp["module"].split("/")[:2 if imp["module"].startswith("@") else 1])
                ctx.edge(path, g.ensure_external(pkg, "javascript"), IMPORTS, CERTAIN, imp["line"], path)
        for ref in fr.refs:
            if ref.kind != "call":
                continue
            caller = ctx.symbols.get(ref.src)
            parts = ref.expr.split(".")
            head = parts[0]
            cls = caller.parent if caller is not None and caller.kind == "method" else None
            if head in ("this", "super") and cls and len(parts) >= 2:
                target_cls = cls
                if head == "super":
                    bases = [b for b in r.class_bases.get(cls, []) if b]
                    target_cls = bases[0] if bases else None
                if target_cls and len(parts) == 2:
                    found, ext = r.member(target_cls, parts[1])
                    if found:
                        ctx.edge(ref.src, found, CALLS, CERTAIN, ref.line, path)
                    elif not ext and parts[1] not in SKIP_METHODS:
                        for dst, cert, note in ctx.fallback_methods(parts[1]):
                            ctx.edge(ref.src, dst, CALLS, cert, ref.line, path, note)
                elif len(parts) >= 3 and parts[-1] not in SKIP_METHODS:
                    for dst, cert, note in ctx.fallback_methods(parts[-1]):
                        ctx.edge(ref.src, dst, CALLS, cert, ref.line, path, note)
                continue
            if head == "super" and len(parts) == 1 and cls:                    # super(…) → constructeur de la base
                bases = [b for b in r.class_bases.get(cls, []) if b]
                if bases:
                    init, _ = r.member(bases[0], "constructor")
                    if init:
                        ctx.edge(ref.src, init, CALLS, CERTAIN, ref.line, path, "super()")
                continue
            if ref.expr.startswith("?."):
                if parts[-1] not in SKIP_METHODS:
                    for dst, cert, note in ctx.fallback_methods(parts[-1]):
                        ctx.edge(ref.src, dst, CALLS, cert, ref.line, path, note)
                continue
            entry = r.lookup(path, parts)
            if entry is None and caller is not None:                          # fonction imbriquée dans l'appelant
                nested = f"{path}::{caller.id.split('::', 1)[1]}.{head}"
                if nested in ctx.symbols and len(parts) == 1:
                    entry = ("func", nested, CERTAIN)
            if entry:
                if entry[0] == "ext":
                    ctx.edge(ref.src, g.ensure_external(entry[1], "javascript"), CALLS, CERTAIN, ref.line, path)
                elif entry[0] == "class":
                    ctx.edge(ref.src, entry[1], CALLS, entry[2], ref.line, path, "new" if ref.extra.get("new") else "")
                    ctor, _ = r.member(entry[1], "constructor")
                    if ctor:
                        ctx.edge(ref.src, ctor, CALLS, entry[2], ref.line, path, "constructeur")
                elif entry[0] == "func":
                    ctx.edge(ref.src, entry[1], CALLS, entry[2], ref.line, path)
                continue
            if len(parts) == 1:
                if head in GLOBALS or (caller is not None and any(p["name"].lstrip(".") == head for p in caller.params)):
                    if caller is not None and any(p["name"].lstrip(".") == head for p in caller.params):
                        g.ensure_unknown("param:" + head, "paramètre appelé : cible dépendante de l'appelant")
                        ctx.edge(ref.src, "unknown:param:" + head, CALLS, UNKNOWN, ref.line, path, "paramètre appelé")
                    continue
                g.ensure_unknown(head, "nom non résolu (global, import dynamique ou fonction locale à une closure)")
                ctx.edge(ref.src, "unknown:" + head, CALLS, UNKNOWN, ref.line, path, "nom non résolu")
                continue
            if head in GLOBALS or parts[-1] in SKIP_METHODS:
                continue
            for dst, cert, note in ctx.fallback_methods(parts[-1]):
                ctx.edge(ref.src, dst, CALLS, cert, ref.line, path, note)
