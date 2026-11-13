"""Résolution Rust : arbre de modules (mod x;), `use`, chemins crate::/self::/super::/Self::, impl/traits, macros."""

from __future__ import annotations

import posixpath
from collections import defaultdict

from ..model import CALLS, CERTAIN, IMPLEMENTS, IMPORTS, INHERITS, PROBABLE, UNKNOWN

STD_ROOTS = {"std", "core", "alloc", "proc_macro", "test"}
STD_MACROS = {"println!", "print!", "eprintln!", "eprint!", "format!", "vec!", "panic!", "assert!", "assert_eq!", "assert_ne!",
              "debug_assert!", "debug_assert_eq!", "write!", "writeln!", "unreachable!", "unimplemented!", "todo!", "matches!",
              "dbg!", "env!", "include_str!", "include_bytes!", "concat!", "stringify!", "line!", "file!", "cfg!", "format_args!",
              "thread_local!", "wrap_pyfunction!", "wrap_pymodule!", "json!", "bail!", "ensure!", "anyhow!", "info!", "warn!",
              "error!", "debug!", "trace!", "lazy_static!", "bitflags!", "try!", "compile_error!", "column!", "module_path!"}
SKIP_METHODS = {
    "iter", "iter_mut", "into_iter", "map", "filter", "collect", "unwrap", "expect", "unwrap_or", "unwrap_or_else", "unwrap_or_default",
    "clone", "to_string", "to_owned", "as_str", "as_ref", "as_mut", "len", "is_empty", "push", "pop", "insert", "remove", "get",
    "get_mut", "contains", "contains_key", "extend", "join", "split", "trim", "parse", "ok", "err", "ok_or", "ok_or_else", "map_err",
    "and_then", "or_else", "is_some", "is_none", "is_ok", "is_err", "take", "replace", "borrow", "borrow_mut", "lock", "read", "write",
    "send", "recv", "first", "last", "enumerate", "zip", "rev", "skip", "chain", "flat_map", "fold", "any", "all", "find", "position",
    "count", "sum", "min", "max", "sort", "sort_by", "sort_by_key", "dedup", "retain", "drain", "clear", "keys", "values", "entry",
    "or_insert", "or_insert_with", "or_default", "into", "from", "try_into", "as_bytes", "bytes", "chars", "lines", "starts_with",
    "ends_with", "to_vec", "to_lowercase", "to_uppercase", "write_all", "read_to_string", "flush", "spawn", "await", "poll", "downcast",
    "add", "sub", "mul", "div", "eq", "cmp", "partial_cmp", "hash", "fmt", "default", "new", "with_capacity", "abs", "pow", "sqrt",
    "bind", "call", "call1", "call_method", "getattr", "setattr", "extract", "add_function", "add_class", "add_submodule", "into_py",
    "unbind", "is_instance_of", "downcast_into", "import", "as_any", "boxed", "step_by", "windows", "chunks",
    "to_str", "to_string_lossy", "display", "exists", "is_file", "is_dir", "file_name", "extension", "parent", "set", "load", "store",
}


class RustResolver:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.files = {p: f for p, f in ctx.files.items() if f.lang == "rust"}
        self.cargo = {p: f for p, f in ctx.files.items() if p.endswith("Cargo.toml") and f.info.get("cargo")}
        self.crate_of: dict[str, str] = {}                 # fichier .rs → racine de caisse (dossier du Cargo.toml)
        self.crates: dict[str, dict] = {}                  # nom de caisse (_) → {"dir", "root"}
        self.modpath: dict[str, tuple[str, ...]] = {}      # fichier → chemin de module (dans sa caisse)
        self.items: dict[tuple, dict[str, str]] = defaultdict(dict)    # (caisse, modpath) → nom → id
        self.submods: dict[tuple, dict[str, str]] = defaultdict(dict)  # (caisse, modpath) → nom → fichier du module enfant
        self.modfile: dict[tuple, str] = {}                # (caisse, modpath) → fichier
        self.trait_impls: dict[str, list[str]] = defaultdict(list)   # id de type → ids de traits (internes)
        self._scope: dict[str, dict] = {}

    # -- structure des caisses -------------------------------------------------------------------------
    def build_crates(self) -> None:
        for cpath, fr in self.cargo.items():
            cdir = posixpath.dirname(cpath)
            info = fr.info["cargo"]
            name = (info.get("lib_name") or info.get("package", "")).replace("-", "_")
            if not name:
                continue
            for cand in ("src/lib.rs", "src/main.rs"):
                root = posixpath.join(cdir, cand) if cdir else cand
                if root in self.files:
                    self.crates.setdefault(name, {"dir": cdir, "root": root})
                    break
            for b in (info.get("bins") or []):
                broot = posixpath.join(cdir, "src/bin", b + ".rs") if cdir else f"src/bin/{b}.rs"
                if broot in self.files:
                    self.crates.setdefault(b.replace("-", "_"), {"dir": cdir, "root": broot})
        # chaque fichier .rs → sa caisse la plus proche
        crate_dirs = sorted(((c["dir"], n) for n, c in self.crates.items()), key=lambda x: -len(x[0]))
        for path in self.files:
            for cdir, name in crate_dirs:
                if not cdir or path.startswith(cdir + "/"):
                    self.crate_of[path] = name
                    break
            else:
                self.crate_of[path] = "<racine>"
        # arbre de modules par `mod x;`
        roots = [(n, c["root"]) for n, c in self.crates.items()]
        if not roots:                                         # pas de Cargo.toml : tout fichier non déclaré est une racine
            declared = {self._child(p, imp["module"]) for p, f in self.files.items() for imp in f.imports if imp.get("mod_decl")}
            roots = [("<racine>", p) for p in self.files if p not in declared and p.rsplit("/", 1)[-1] in
                     ("lib.rs", "main.rs", "mod.rs")] or [("<racine>", p) for p in sorted(self.files)[:1]]
        seen = set()
        for crate, root in roots:
            self._walk(crate, root, (), seen)
        for path in self.files:                              # fichiers orphelins : chemin déduit du dossier
            if path not in self.modpath:
                crate = self.crate_of.get(path, "<racine>")
                cdir = self.crates.get(crate, {}).get("dir", "")
                rel = path[len(cdir) + 1:] if cdir and path.startswith(cdir + "/") else path
                rel = rel.removeprefix("src/").removesuffix(".rs").removesuffix("/mod")
                self.modpath[path] = tuple(p for p in rel.split("/") if p)
                self.modfile.setdefault((crate, self.modpath[path]), path)
        for path, fr in self.files.items():
            crate, mp = self.crate_of[path], self.modpath[path]
            for s in fr.symbols:
                if s.id.endswith("::<module>"):
                    continue
                q = s.id.split("::", 1)[1].split(".")
                if s.kind in ("function", "struct", "enum", "trait", "macro", "module") and not s.meta.get("impl_type"):
                    self.items[(crate, (*mp, *q[:-1]))].setdefault(s.name, s.id)

    def _child(self, path: str, name: str) -> str | None:
        d, base = posixpath.dirname(path), posixpath.basename(path)
        stem = base[:-3]
        folder = d if base in ("lib.rs", "main.rs", "mod.rs") or path in {c["root"] for c in self.crates.values()} \
            else posixpath.join(d, stem)
        for cand in (posixpath.join(folder, name + ".rs"), posixpath.join(folder, name, "mod.rs")):
            if cand in self.files:
                return cand
        return None

    def _walk(self, crate: str, path: str, mp: tuple, seen: set) -> None:
        if path in seen or path not in self.files:
            return
        seen.add(path)
        self.modpath[path] = mp
        self.modfile[(crate, mp)] = path
        self.crate_of[path] = crate
        for imp in self.files[path].imports:
            if imp.get("mod_decl"):
                child = self._child(path, imp["module"])
                if child:
                    self.submods[(crate, mp)][imp["module"]] = child
                    self._walk(crate, child, (*mp, imp["module"]), seen)

    # -- résolution de chemins -----------------------------------------------------------------------------
    def scope(self, path: str) -> dict[str, tuple[str, ...]]:
        """Nom lié par `use` → chemin complet (liste de segments)."""
        if path in self._scope:
            return self._scope[path]
        out: dict[str, tuple[str, ...]] = {}
        for imp in self.files[path].imports:
            if not imp.get("rust") or imp.get("mod_decl"):
                continue
            base = tuple(s for s in imp["module"].split("::") if s)
            for name, alias in imp["names"]:
                if name == "*":
                    out.setdefault("*" + "::".join(base), base)
                    continue
                out[alias or name] = (*base, name)
        self._scope[path] = out
        return out

    def _module_items(self, crate: str, mp: tuple) -> dict[str, str]:
        return self.items.get((crate, mp), {})

    def resolve_path(self, path: str, segs: list[str], caller=None, depth: int = 0):
        """→ (kind, valeur, certitude) : ("item", id) | ("module", (caisse, chemin)) | ("ext", texte) | None."""
        if not segs or depth > 6:
            return None
        crate, mp = self.crate_of.get(path, "<racine>"), self.modpath.get(path, ())
        head, rest = segs[0], segs[1:]
        if head == "crate":
            return self._walk_segments(crate, (), rest, caller)
        if head == "self":
            return self._walk_segments(crate, mp, rest, caller)
        if head == "super":
            up = mp[:-1] if mp else mp
            while rest and rest[0] == "super":
                up, rest = up[:-1], rest[1:]
            return self._walk_segments(crate, up, rest, caller)
        if head == "Self":
            tid = self._impl_type_id(caller)
            return self._on_type(tid, rest) if tid else None
        if head in STD_ROOTS:
            return ("ext", "::".join(segs[:3]), CERTAIN)
        scope = self.scope(path)
        if head in scope and scope[head] != tuple(segs[:1]) and not (len(scope[head]) == 1 and scope[head][0] == head):
            return self.resolve_path(path, [*scope[head], *rest], caller, depth + 1)
        here = self._module_items(crate, mp)
        if head in here:
            return self._after_item(here[head], rest)
        if (crate, (*mp, head)) in self.modfile or head in self.submods.get((crate, mp), {}):
            return self._walk_segments(crate, (*mp, head), rest, caller)
        if head in self.crates:                                   # autre caisse du dépôt (dépendance de chemin)
            return self._walk_segments(head, (), rest, caller)
        for star in (k for k in scope if k.startswith("*")):       # use x::*;
            base = list(scope[star])
            res = self.resolve_path(path, [*base, *segs], caller, depth + 1)
            if res and res[0] != "ext":
                return res
        if rest or head[:1].islower():
            return ("ext", "::".join(segs[:3]), PROBABLE) if head not in self.ctx.top.get(path, {}) and not rest else None
        return None

    def _walk_segments(self, crate: str, mp: tuple, rest: list[str], caller):
        while rest:
            name = rest[0]
            items = self._module_items(crate, mp)
            if name in items:
                return self._after_item(items[name], rest[1:])
            if (crate, (*mp, name)) in self.modfile:
                mp, rest = (*mp, name), rest[1:]
                continue
            # ré-exportation `pub use` dans le module visé
            mf = self.modfile.get((crate, mp))
            if mf and mf in self.files:
                scope = self.scope(mf)
                if name in scope and scope[name] != (name,):
                    return self.resolve_path(mf, [*scope[name], *rest[1:]], caller, 1)
            return None
        return ("module", (crate, mp), CERTAIN)

    def _after_item(self, sid: str, rest: list[str]):
        sym = self.ctx.symbols.get(sid)
        if not rest:
            return ("item", sid, CERTAIN)
        if sym and sym.kind in ("struct", "enum", "trait"):
            return self._on_type(sid, rest)
        return None

    def _on_type(self, tid: str, rest: list[str]):
        if not rest:
            return ("item", tid, CERTAIN)
        m = self.ctx.members.get(tid, {}).get(rest[0])
        if m:
            return ("item", m, CERTAIN)
        for trait in self.trait_impls.get(tid, []):              # méthode par défaut d'un trait implémenté
            m = self.ctx.members.get(trait, {}).get(rest[0])
            if m:
                return ("item", m, PROBABLE)
        return None

    def _impl_type_id(self, caller) -> str | None:
        if caller is None or caller.kind != "method":
            return None
        p = caller.parent
        return p if p in self.ctx.symbols else self._type_in_file(caller.file, caller.meta.get("impl_type", ""))

    def _type_in_file(self, path: str, name: str) -> str | None:
        crate, mp = self.crate_of.get(path, "<racine>"), self.modpath.get(path, ())
        for cand in (self._module_items(crate, mp).get(name),):
            if cand:
                return cand
        res = self.resolve_path(path, [name])
        if res and res[0] == "item":
            return res[1]
        cands = self.ctx.types_by_name.get(name, [])
        return cands[0] if len(cands) == 1 else None


def link(ctx) -> None:
    r = RustResolver(ctx)
    if not r.files:
        return
    g = ctx.graph
    r.build_crates()
    # types propriétaires des méthodes : le symbole méthode a `parent` = id « fichier::Type » (peut ne pas exister ici)
    for path, fr in r.files.items():
        for s in fr.symbols:
            if s.kind == "method" and s.parent not in ctx.symbols:
                tid = r._type_in_file(path, s.meta.get("impl_type", ""))
                if tid:
                    old = s.parent
                    ctx.members[tid][s.name] = s.id
                    ctx.members.get(old, {}).pop(s.name, None)
                    g.nodes[s.id].parent = tid
                    ctx.symbols[s.id].parent = tid
                    s.parent = tid
                    g.edges[:] = [e for e in g.edges if not (e.dst == s.id and e.kind == "defines")]
                    g.add_edge(tid, s.id, "defines", CERTAIN, s.line, path)
    for path, fr in r.files.items():                                        # implémentations de traits
        for ref in fr.refs:
            if ref.kind == "implements":
                tid = r._type_in_file(path, ref.extra.get("type", ""))
                res = r.resolve_path(path, ref.expr.split("::"))
                if tid and res and res[0] == "item":
                    r.trait_impls[tid].append(res[1])
                    ctx.edge(tid, res[1], IMPLEMENTS, CERTAIN, ref.line, path)
                elif tid:
                    ext = g.ensure_external(ref.expr, "rust")
                    ctx.edge(tid, ext, IMPLEMENTS, CERTAIN if res else PROBABLE, ref.line, path)
            elif ref.kind == "inherits":
                res = r.resolve_path(path, ref.expr.split("::"))
                if res and res[0] == "item":
                    ctx.edge(ref.src, res[1], INHERITS, CERTAIN, ref.line, path, "supertrait")
    for path, fr in r.files.items():
        # arêtes d'import
        for imp in fr.imports:
            if imp.get("mod_decl"):
                child = r._child(path, imp["module"])
                if child:
                    ctx.edge(path, child, IMPORTS, CERTAIN, imp["line"], path, "mod")
                continue
            if not imp.get("rust"):
                continue
            segs = [s for s in imp["module"].split("::") if s]
            for name, _ in imp["names"]:
                res = r.resolve_path(path, [*segs, name]) if segs else r.resolve_path(path, [name])
                if res and res[0] == "item":
                    ctx.edge(path, ctx.symbols[res[1]].file, IMPORTS, res[2], imp["line"], path)
                elif res and res[0] == "module":
                    target = r.modfile.get(res[1])
                    if target and target != path:
                        ctx.edge(path, target, IMPORTS, CERTAIN, imp["line"], path)
                elif segs and segs[0] not in ("crate", "self", "super", "Self"):
                    root = segs[0]
                    if root in r.crates:
                        continue
                    ext = g.ensure_external(root, "rust")
                    ctx.edge(path, ext, IMPORTS, CERTAIN, imp["line"], path)
        for ref in fr.refs:
            if ref.kind != "call":
                continue
            caller = ctx.symbols.get(ref.src)
            expr = ref.expr
            if expr.endswith("!"):                                           # macros
                if expr in STD_MACROS:
                    continue
                local = [m for m in ctx.funcs_by_name.get(expr, []) if ctx.symbols[m].kind == "macro"]
                if len(local) == 1:
                    ctx.edge(ref.src, local[0], CALLS, PROBABLE if ctx.symbols[local[0]].file != path else CERTAIN, ref.line, path,
                             "macro_rules!")
                elif len(local) > 1:
                    g.ensure_unknown(expr, "plusieurs macros portent ce nom")
                    ctx.edge(ref.src, "unknown:" + expr, CALLS, UNKNOWN, ref.line, path, "plusieurs macros du même nom")
                continue
            if "." in expr or expr.startswith("?"):
                parts = expr.split(".")
                if parts[0] == "self" and caller is not None and caller.kind == "method" and len(parts) == 2:
                    tid = r._impl_type_id(caller)
                    res = r._on_type(tid, [parts[1]]) if tid else None
                    if res:
                        ctx.edge(ref.src, res[1], CALLS, res[2], ref.line, path)
                        continue
                    if parts[1] in SKIP_METHODS:
                        continue
                if parts[-1] in SKIP_METHODS:
                    continue
                for dst, cert, note in ctx.fallback_methods(parts[-1]):
                    ctx.edge(ref.src, dst, CALLS, cert, ref.line, path, note)
                continue
            segs = expr.split("::")
            res = r.resolve_path(path, segs, caller)
            if res and res[0] == "item":
                dst = res[1]
                if ctx.symbols[dst].kind in ("struct", "enum", "trait"):
                    continue
                ctx.edge(ref.src, dst, CALLS, res[2], ref.line, path)
            elif res and res[0] == "ext":
                ctx.edge(ref.src, g.ensure_external(res[1], "rust"), CALLS, CERTAIN, ref.line, path)
            elif len(segs) > 1 and segs[0][:1].isupper() and not res:
                # Type::fonction hors projet (std) → ignoré ; Type interne mais fonction introuvable → inconnu
                tid = r._type_in_file(path, segs[0])
                if tid:
                    g.ensure_unknown(expr, "fonction associée introuvable (générée par une macro ou un trait externe)")
                    ctx.edge(ref.src, "unknown:" + expr, CALLS, UNKNOWN, ref.line, path, "associée introuvable")
    ctx.rust_resolver = r
