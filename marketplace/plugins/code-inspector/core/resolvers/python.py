"""Résolution des imports, héritages, décorateurs et appels pour Python."""

from __future__ import annotations

import os
import sys
from collections import defaultdict

from ..data import names
from ..model import CALLS, CERTAIN, DECORATES, IMPORTS, INHERITS, PROBABLE, REFERENCES, UNKNOWN, FileResult

STDLIB = set(sys.stdlib_module_names)
BUILTINS = set(names()["builtins"])
SKIP_METHODS = set(names()["skip_py"])


class PyResolver:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.files: dict[str, FileResult] = {p: f for p, f in ctx.files.items() if f.lang == "python"}
        self.full: dict[str, str] = {}
        self.suffix: dict[str, list[str]] = defaultdict(list)
        for path in self.files:
            parts = path[:-3].split("/") if path.endswith(".py") else path[:-4].split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if not parts:
                continue
            self.full[".".join(parts)] = path
            for k in range(len(parts)):
                self.suffix[".".join(parts[k:])].append(path)
        self._scope: dict[str, dict] = {}
        self._building: set[str] = set()
        self.class_bases: dict[str, list[tuple[str | None, str]]] = {}
        self._star: dict[str, list[str]] = {}
        self._modules_imported: dict[str, list[tuple[str, str | None]]] = {}

    # -- modules ---------------------------------------------------------------------------------
    def module_file(self, dotted: str, from_path: str, level: int = 0) -> tuple[str | None, str]:
        """(fichier | None, certitude). None = module externe (stdlib, paquet installé)."""
        if level:
            base = from_path.split("/")[:-1]
            if level > 1:
                base = base[:len(base) - (level - 1)]
            rel = "/".join([*base, *dotted.split(".")]) if dotted else "/".join(base)
            for cand in (f"{rel}.py", f"{rel}/__init__.py", f"{rel}.pyi"):
                if cand in self.files:
                    return cand, CERTAIN
            return None, CERTAIN
        if not dotted:
            return None, CERTAIN
        if dotted in self.full:
            return self.full[dotted], CERTAIN
        cands = self.suffix.get(dotted, [])
        first = dotted.split(".")[0]
        if cands and first in STDLIB:                    # `import json` ne doit pas viser un « json.py » lointain
            near = [c for c in cands if c.rsplit("/", 1)[0] == from_path.rsplit("/", 1)[0] or "/" not in c]
            cands = near
        if len(cands) == 1:
            return cands[0], CERTAIN
        if cands:
            def shared(c):
                return len(os.path.commonprefix([c.split("/"), from_path.split("/")]))
            best = max(shared(c) for c in cands)
            top = [c for c in cands if shared(c) == best]
            return (top[0], PROBABLE if len(top) > 1 or len(cands) > 1 else CERTAIN)
        return None, CERTAIN

    # -- portée d'un fichier ------------------------------------------------------------------------
    def scope(self, path: str) -> dict:
        if path in self._scope:
            return self._scope[path]
        if path in self._building:
            return {}
        self._building.add(path)
        scope: dict[str, tuple] = {}
        mods: list[tuple[str, str | None]] = []
        star: list[str] = []
        for imp in self.files[path].imports:
            module, level = imp["module"], imp["level"]
            target, cert = self.module_file(module, path, level)
            if not imp["names"]:                                                 # import a.b.c [as x]
                if imp["alias"]:
                    scope[imp["alias"]] = ("mod", target, module, cert)
                else:
                    head = module.split(".")[0]
                    htarget, hcert = self.module_file(head, path, 0)
                    scope[head] = ("mod", htarget, head, hcert)
                mods.append((module, target))
                continue
            for name, alias in imp["names"]:
                bind = alias or name
                if name == "*":
                    if target:
                        star.append(target)
                    continue
                if target and name in self.ctx.top.get(target, {}):
                    scope[bind] = ("sym", self.ctx.top[target][name], cert)
                    continue
                sub, subcert = self.module_file(f"{module}.{name}" if module else name, path, level)
                if target and sub and sub != target:
                    scope[bind] = ("mod", sub, f"{module}.{name}", subcert)
                    continue
                if target and target != path:                                    # ré-exportation par le paquet
                    inner = self.scope(target).get(name)
                    if inner:
                        scope[bind] = inner
                        continue
                if target is None and not (level and not module):
                    scope[bind] = ("ext", f"{module}.{name}" if module else name)
                elif target:
                    scope[bind] = ("name", target, name, cert)               # nom absent du module (dynamique/généré)
        self._scope[path] = scope
        self._modules_imported[path] = mods
        self._star[path] = star
        self._building.discard(path)
        return scope

    # -- types / classes -------------------------------------------------------------------------------
    def resolve_class(self, path: str, expr: str) -> str | None:
        entry = self.lookup_name(path, expr)
        return entry[1] if entry and entry[0] == "class" else None

    def lookup_name(self, path: str, expr: str, caller=None):
        """expr pointée → ("class"|"func"|"method"|"ext"|"mod", cible, certitude)|None."""
        parts = expr.split(".")
        head = parts[0]
        scope = self.scope(path)
        top = self.ctx.top.get(path, {})
        sid = None
        if caller is not None:                                                     # fonctions imbriquées de l'appelant
            qual = caller.id.split("::", 1)[1].split(".")
            for k in range(len(qual), 0, -1):
                cand = f"{path}::{'.'.join([*qual[:k], head])}"
                if cand in self.ctx.symbols and cand != caller.id:
                    sid = cand
                    break
        if sid is None and head in top:
            sid = top[head]
        cert = CERTAIN
        if sid is None and head in scope:
            entry = scope[head]
            if entry[0] == "sym":
                sid, cert = entry[1], entry[2]
            elif entry[0] == "mod":
                return self._through_module(entry, parts[1:], path)
            elif entry[0] == "ext":
                return ("ext", entry[1] + ("." + ".".join(parts[1:]) if len(parts) > 1 else ""), CERTAIN)
            elif entry[0] == "name":
                return None
        if sid is None:
            for star in self._star.get(path, []):
                if head in self.ctx.top.get(star, {}):
                    sid = self.ctx.top[star][head]
                    break
        if sid is None:
            return None
        return self._descend(sid, parts[1:], cert)

    def _descend(self, sid: str, rest: list[str], cert: str):
        sym = self.ctx.symbols.get(sid)
        if sym is None:
            return None
        if not rest:
            return ("class" if sym.kind == "class" else "func" if sym.kind == "function" else "method", sid, cert)
        if sym.kind == "class":
            found, ext = self.member(sid, rest[0])
            if found:
                return ("method", found, cert)
            return ("ext", f"{sym.name}.{rest[0]}", cert) if ext else None
        return None

    def _through_module(self, entry, rest: list[str], path: str):
        _, target, dotted, cert = entry
        if target is None:                                                         # module externe
            return ("ext", dotted + ("." + ".".join(rest[:2]) if rest else ""), CERTAIN)
        if not rest:
            return ("mod", target, cert)
        name = rest[0]
        if name in self.ctx.top.get(target, {}):
            return self._descend(self.ctx.top[target][name], rest[1:], cert)
        sub, subcert = self.module_file(f"{dotted}.{name}", path, 0)
        if sub and sub != target:
            return self._through_module(("mod", sub, f"{dotted}.{name}", subcert), rest[1:], path)
        inner = self.scope(target).get(name)                                        # ré-exportation
        if inner and inner[0] == "sym":
            return self._descend(inner[1], rest[1:], cert)
        return None

    def prefix_module(self, path: str, parts: list[str]):
        """`import a.b.c` puis `a.b.c.f()` : plus long préfixe pointé importé comme module."""
        best = None
        for dotted, target in self._modules_imported.get(path, []):
            segs = dotted.split(".")
            if parts[:len(segs)] == segs and (best is None or len(segs) > len(best[0])):
                best = (segs, target, dotted)
        return best

    def member(self, class_id: str, name: str, depth: int = 0) -> tuple[str | None, bool]:
        """(id de la méthode, base externe rencontrée). Cherche la classe puis ses bases résolues."""
        found = self.ctx.members.get(class_id, {}).get(name)
        if found:
            return found, False
        ext = False
        if depth < 8:
            for base_id, _ in self.class_bases.get(class_id, []):
                if base_id is None:
                    ext = True
                    continue
                f, e = self.member(base_id, name, depth + 1)
                if f:
                    return f, False
                ext = ext or e
        return None, ext

    def resolve_bases(self) -> None:
        for path, fr in self.files.items():
            for ref in fr.refs:
                if ref.kind != "inherits":
                    continue
                cid = ref.src
                entry = self.lookup_name(path, ref.expr)
                if entry and entry[0] == "class":
                    self.class_bases.setdefault(cid, []).append((entry[1], ref.expr))
                    self.ctx.edge(cid, entry[1], INHERITS, entry[2], ref.line, path)
                else:
                    ext_name = entry[1] if entry and entry[0] == "ext" else ref.expr
                    self.class_bases.setdefault(cid, []).append((None, ext_name))
                    ext = self.ctx.graph.ensure_external(ext_name, "python")
                    self.ctx.edge(cid, ext, INHERITS, CERTAIN if entry else PROBABLE, ref.line, path,
                                  "" if entry else "base non résolue (externe ou générée)")

    # -- appels -------------------------------------------------------------------------------------
    def resolve_call(self, path: str, caller, expr: str):
        """Liste de (dst, certitude, note) ; liste vide = rien à relier (builtin, bibliothèque…)."""
        g = self.ctx.graph
        if expr.startswith("?."):
            name = expr[2:]
            return [] if name in SKIP_METHODS else self.ctx.fallback_methods(name)
        if "()." in expr:                                                   # Classe().méthode()
            ctor, _, meth = expr.partition("().")
            tcls = self.resolve_class(path, ctor)
            if tcls:
                found, ext = self.member(tcls, meth.split(".")[0])
                if found:
                    return [(found, PROBABLE, f"méthode appelée sur le résultat de {ctor}(…)")]
                if ext:
                    return []
            return [] if meth in SKIP_METHODS else self.ctx.fallback_methods(meth.split(".")[0])
        parts = expr.split(".")
        head = parts[0]
        cls = caller.parent if caller is not None and caller.kind == "method" else None
        # self.x / cls.x
        if cls and head in ("self", "cls") and len(parts) >= 2:
            if len(parts) == 2:
                found, ext = self.member(cls, parts[1])
                if found:
                    return [(found, CERTAIN, "")]
                if ext:
                    return []                                                       # hérité d'une classe externe
                return [] if parts[1] in SKIP_METHODS else self.ctx.fallback_methods(parts[1]) or \
                    [("unknown:self." + parts[1], UNKNOWN, "méthode introuvable dans la classe et ses bases")]
            ctor = (self.ctx.symbols[cls].meta.get("attr_types") or {}).get(parts[1]) if cls in self.ctx.symbols else None
            if ctor and len(parts) == 3:
                tcls = self.resolve_class(path, ctor)
                if tcls:
                    found, _ = self.member(tcls, parts[2])
                    if found:
                        return [(found, PROBABLE, f"type de self.{parts[1]} déduit de {ctor}(…)")]
            return [] if parts[-1] in SKIP_METHODS else self.ctx.fallback_methods(parts[-1])
        # variable locale dont le type vient d'un constructeur
        if caller is not None and head in (caller.meta.get("local_types") or {}) and len(parts) == 2:
            tcls = self.resolve_class(path, caller.meta["local_types"][head])
            if tcls:
                found, ext = self.member(tcls, parts[1])
                if found:
                    return [(found, PROBABLE, f"type de {head} déduit de {caller.meta['local_types'][head]}(…)")]
                if ext:
                    return []
        # paramètre appelé : `callback(x)`
        if caller is not None and len(parts) == 1 and any(p["name"] == head for p in caller.params):
            return [("unknown:param:" + head, UNKNOWN, f"« {head} » est un paramètre : la cible dépend de l'appelant")]
        pm = self.prefix_module(path, parts)
        if pm and len(parts) > len(pm[0]):
            segs, target, dotted = pm
            if target is None:
                return [(g.ensure_external(".".join(parts[:len(segs) + 1]), "python"), CERTAIN, "")]
            entry = self._through_module(("mod", target, dotted, CERTAIN), parts[len(segs):], path)
        else:
            entry = self.lookup_name(path, expr, caller)
        if entry:
            kind = entry[0]
            if kind == "ext":
                return [(g.ensure_external(".".join(entry[1].split(".")[:3]), "python"), CERTAIN, "")]
            if kind == "class":
                out = [(entry[1], entry[2], "constructeur")]
                init, _ = self.member(entry[1], "__init__")
                if init:
                    out.append((init, entry[2], "constructeur"))
                return out
            if kind in ("func", "method"):
                return [(entry[1], entry[2], "")]
            return []
        if len(parts) == 1:
            if head in BUILTINS:
                return []
            return [("unknown:" + head, UNKNOWN, "nom non résolu (import *, injection ou définition dynamique)")]
        if parts[-1] in SKIP_METHODS:
            return []
        if head in self.scope(path) and self.scope(path)[head][0] == "ext":
            return []
        return self.ctx.fallback_methods(parts[-1])


def link(ctx) -> None:
    r = PyResolver(ctx)
    if not r.files:
        return
    g = ctx.graph
    for path in r.files:
        r.scope(path)
    r.resolve_bases()
    for path, fr in r.files.items():
        for imp in fr.imports:                                                      # arêtes d'import (fichier → fichier)
            target, cert = r.module_file(imp["module"], path, imp["level"])
            if target is None and imp["level"] == 0:
                if imp["module"]:
                    ext = g.ensure_external(imp["module"].split(".")[0], "python")
                    ctx.edge(path, ext, IMPORTS, CERTAIN, imp["line"], path)
                continue
            if target is not None:
                ctx.edge(path, target, IMPORTS, cert, imp["line"], path)
            for name, _ in imp["names"]:
                sub, subcert = r.module_file(f"{imp['module']}.{name}" if imp["module"] else name, path, imp["level"])
                if sub and sub != target:
                    ctx.edge(path, sub, IMPORTS, subcert, imp["line"], path)
        by_line_call = {(ref.src, ref.expr, ref.line) for ref in fr.refs if ref.kind == "call"}
        for ref in fr.refs:
            caller = ctx.symbols.get(ref.src)
            if ref.kind == "call":
                for dst, cert, note in r.resolve_call(path, caller, ref.expr):
                    if dst.startswith("unknown:"):
                        g.ensure_unknown(dst[8:], note)
                    ctx.edge(ref.src, dst, CALLS, cert, ref.line, path, note)
            elif ref.kind == "dynamic":
                label = ref.extra.get("dynamic", ref.expr)
                nid = g.ensure_unknown("dynamique:" + label, "appel construit à l'exécution : cible indéterminable statiquement")
                ctx.edge(ref.src, nid, CALLS, UNKNOWN, ref.line, path, f"appel dynamique ({label})")
            elif ref.kind == "ref" and (ref.src, ref.expr, ref.line) not in by_line_call:
                entry = r.lookup_name(path, ref.expr, caller) if not ref.expr.startswith(("self.", "cls.")) else None
                if ref.expr.startswith(("self.", "cls.")) and caller is not None and caller.kind == "method" and ref.expr.count(".") == 1:
                    found, _ = r.member(caller.parent, ref.expr.split(".")[1])
                    entry = ("method", found, CERTAIN) if found else None
                if entry and entry[0] in ("func", "method") and entry[1] != ref.src:
                    ctx.edge(ref.src, entry[1], REFERENCES, PROBABLE, ref.line, path, "référence sans appel (rappel possible)")
            elif ref.kind == "decorates":
                entry = r.lookup_name(path, ref.expr)
                if entry and entry[0] in ("func", "method", "class"):
                    ctx.edge(entry[1], ref.src, DECORATES, entry[2], ref.line, path)
    ctx.python_resolver = r
