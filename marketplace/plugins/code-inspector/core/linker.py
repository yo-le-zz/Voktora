"""Lieur : transforme les FileResult (un par fichier) en un graphe de projet.

Règle d'or — jamais d'invention : une relation est `certain` quand elle découle directement du code (import résolu,
appel d'un nom importé, `self.méthode` trouvée dans la classe ou ses bases), `probable` quand elle repose sur une
inférence raisonnable (un seul candidat portant ce nom, type déduit d'une affectation `x = Classe()`, fonction passée
en rappel), `inconnu` quand le code ne permet pas de trancher (appel dynamique, receveur de type inconnu et
plusieurs candidats, paramètre appelé…)."""

from __future__ import annotations

from collections import defaultdict

from . import graph as graph_mod
from .model import CALLS, CERTAIN, DEFINES, DIR, FILE, METHOD, MODULE, UNKNOWN, FileResult, Symbol

MAX_FALLBACK = 3          # au-delà : un seul nœud « inconnu » au lieu de N arêtes probables


class Context:
    def __init__(self, files: dict[str, FileResult], graph: graph_mod.Graph) -> None:
        self.files, self.graph = files, graph
        self.symbols: dict[str, Symbol] = {}
        self.top: dict[str, dict[str, str]] = defaultdict(dict)          # fichier → nom → id (portée module)
        self.members: dict[str, dict[str, str]] = defaultdict(dict)      # classe/type → nom → id de méthode
        self.methods_by_name: dict[str, list[str]] = defaultdict(list)   # nom de méthode → ids
        self.funcs_by_name: dict[str, list[str]] = defaultdict(list)
        self.types_by_name: dict[str, list[str]] = defaultdict(list)
        self.macros_by_name: dict[str, list[str]] = defaultdict(list)
        self.stats = {"resolved": 0, "unresolved": 0}

    def norm(self, sid: str) -> str:
        return sid.rsplit("::", 1)[0] if sid.endswith("::<module>") else sid

    def edge(self, src, dst, kind, certainty=CERTAIN, line=0, file="", note=""):
        return self.graph.add_edge(self.norm(src), self.norm(dst), kind, certainty, line, file, note)

    def fallback_methods(self, name: str, skip: set[str] | None = None) -> list[tuple[str, str, str]]:
        """Candidats pour `receveur_inconnu.nom()` : [(id, certitude, note)]. Jamais plus de MAX_FALLBACK arêtes."""
        cands = [c for c in self.methods_by_name.get(name, []) if not skip or c not in skip]
        if not cands:
            return []
        if len(cands) == 1:
            return [(cands[0], "probable", "seul candidat portant ce nom ; type du receveur non établi")]
        if len(cands) <= MAX_FALLBACK:
            return [(c, "probable", f"{len(cands)} candidats portent ce nom") for c in cands]
        return [("unknown:" + name, UNKNOWN, f"{len(cands)} méthodes portent le nom « {name} » ; receveur de type inconnu")]


def build(files: dict[str, FileResult], dirs_only_files: bool = True) -> graph_mod.Graph:
    from .resolvers import cpp, js, python, rust
    g = graph_mod.Graph()
    ctx = Context(files, g)
    # dossiers et fichiers
    for path, fr in sorted(files.items()):
        parts = path.split("/")
        for i in range(len(parts) - 1):
            did = "/".join(parts[:i + 1])
            if did not in g.nodes:
                g.add_node(Symbol(did, DIR, parts[i], "", 0, 0, "", "/".join(parts[:i]) if i else ""))
        g.add_node(Symbol(path, FILE, parts[-1], path, 1, fr.loc, fr.lang, "/".join(parts[:-1]), meta={"loc": fr.loc,
                                                                                                    "info": {k: v for k, v in fr.info.items() if k != "dependencies"}}))
    for path, fr in files.items():
        for s in fr.symbols:
            if s.id.endswith("::<module>"):
                if s.doc:
                    g.nodes[path].doc = s.doc
                continue
            s2 = Symbol(**{**s.to_dict()})
            if s2.parent.endswith("::<module>"):
                s2.parent = path
            g.add_node(s2)
            ctx.symbols[s2.id] = s2
    for s in list(ctx.symbols.values()):
        g.add_edge(s.parent or s.file, s.id, DEFINES, CERTAIN, s.line, s.file)
        if s.kind == METHOD:
            ctx.members[s.parent][s.name] = s.id
            ctx.methods_by_name[s.name].append(s.id)
        elif s.kind in ("function", "macro"):
            ctx.funcs_by_name[s.name].append(s.id)
        if s.kind in ("class", "struct", "enum", "trait"):
            ctx.types_by_name[s.name].append(s.id)
        if s.parent == s.file and s.kind != MODULE:
            ctx.top[s.file].setdefault(s.name, s.id)
    for path in files:
        g.add_edge(path.rsplit("/", 1)[0] if "/" in path else "", path, DEFINES, CERTAIN, 0, path) if "/" in path else None
    for d in [n for n in g.nodes.values() if n.kind == DIR]:
        if d.parent:
            g.add_edge(d.parent, d.id, DEFINES, CERTAIN, 0, "")
    for resolver in (python, rust, js, cpp):
        resolver.link(ctx)
    from ..services import ffi
    g.meta["ffi"] = ffi.link(ctx)
    return g


__all__ = ["CALLS", "Context", "build"]
