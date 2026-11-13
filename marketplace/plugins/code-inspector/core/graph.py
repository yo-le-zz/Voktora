"""Graphe du projet : nœuds (symboles), arêtes typées avec certitude, index entrants/sortants, parcours."""

from __future__ import annotations

from collections import defaultdict, deque

from .model import (
    CALLABLE_KINDS,
    CALLS,
    CERTAIN,
    CERTAINTIES,
    DIR,
    EXTERNAL,
    FILE,
    RANK,
    UNKNOWN,
    UNKNOWN_NODE,
    Edge,
    Symbol,
)


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Symbol] = {}
        self.edges: list[Edge] = []
        self._seen: set[tuple] = set()
        self._out: dict[str, list[Edge]] | None = None
        self._in: dict[str, list[Edge]] | None = None
        self.meta: dict = {}

    # -- construction -----------------------------------------------------------------------------
    def add_node(self, sym: Symbol) -> Symbol:
        return self.nodes.setdefault(sym.id, sym)

    def ensure_external(self, name: str, lang: str = "") -> str:
        nid = f"ext:{name}"
        if nid not in self.nodes:
            self.nodes[nid] = Symbol(nid, EXTERNAL, name, "", 0, 0, lang)
        return nid

    def ensure_unknown(self, label: str, note: str = "") -> str:
        nid = f"unknown:{label}"
        if nid not in self.nodes:
            self.nodes[nid] = Symbol(nid, UNKNOWN_NODE, label, "", 0, 0, "", doc=note)
        return nid

    def add_edge(self, src: str, dst: str, kind: str, certainty: str = CERTAIN, line: int = 0, file: str = "",
                 note: str = "") -> Edge | None:
        if src == dst and kind != CALLS:
            return None
        key = (src, dst, kind, line)
        if key in self._seen:
            return None
        self._seen.add(key)
        edge = Edge(src, dst, kind, certainty, line, file, note)
        self.edges.append(edge)
        self._out = self._in = None
        return edge

    # -- index ------------------------------------------------------------------------------------
    def _index(self) -> None:
        self._out, self._in = defaultdict(list), defaultdict(list)
        for e in self.edges:
            self._out[e.src].append(e)
            self._in[e.dst].append(e)

    def out_edges(self, node: str, kinds: set[str] | None = None, min_certainty: str = UNKNOWN) -> list[Edge]:
        if self._out is None:
            self._index()
        return [e for e in self._out.get(node, []) if (kinds is None or e.kind in kinds) and RANK[e.certainty] >= RANK[min_certainty]]

    def in_edges(self, node: str, kinds: set[str] | None = None, min_certainty: str = UNKNOWN) -> list[Edge]:
        if self._in is None:
            self._index()
        return [e for e in self._in.get(node, []) if (kinds is None or e.kind in kinds) and RANK[e.certainty] >= RANK[min_certainty]]

    def children(self, node: str) -> list[Symbol]:
        return sorted((s for s in self.nodes.values() if s.parent == node), key=lambda s: (s.line, s.name))

    # -- requêtes ---------------------------------------------------------------------------------
    def callers(self, node: str, min_certainty: str = UNKNOWN) -> list[Edge]:
        return self.in_edges(node, {CALLS, "references", "ffi"}, min_certainty)

    def callees(self, node: str, min_certainty: str = UNKNOWN) -> list[Edge]:
        return self.out_edges(node, {CALLS, "references", "ffi"}, min_certainty)

    def function_card(self, node: str) -> dict:
        s = self.nodes[node]
        return {"id": s.id, "kind": s.kind, "name": s.name, "file": s.file, "line": s.line, "end_line": s.end_line,
                "signature": s.signature, "params": s.params, "returns": s.returns, "decorators": s.decorators, "doc": s.doc,
                "complexity": s.complexity, "lang": s.lang,
                "callers": [{"id": e.src, "certainty": e.certainty, "line": e.line, "file": e.file, "note": e.note}
                            for e in self.callers(node)],
                "callees": [{"id": e.dst, "certainty": e.certainty, "line": e.line, "note": e.note} for e in self.callees(node)],
                "dependencies": sorted({e.dst for e in self.out_edges(self.owner_file(node), {"imports"})})}

    def owner_file(self, node: str) -> str:
        s = self.nodes.get(node)
        return s.file if s and s.file else node

    def search(self, text: str, kinds: set[str] | None = None, limit: int = 200) -> list[Symbol]:
        t = text.lower().strip()
        if not t:
            return []
        out = [s for s in self.nodes.values() if (kinds is None or s.kind in kinds) and s.kind not in (EXTERNAL, UNKNOWN_NODE)
               and (t in s.name.lower() or t in s.id.lower())]
        out.sort(key=lambda s: (s.name.lower() != t, not s.name.lower().startswith(t), len(s.name), s.id))
        return out[:limit]

    def chains(self, start: str, max_depth: int = 8, min_certainty: str = "probable", max_paths: int = 200) -> list[list[Edge]]:
        """Chemins d'exécution depuis `start` (parcours en profondeur borné, sans cycle) : listes d'arêtes d'appel."""
        paths: list[list[Edge]] = []

        def walk(node: str, path: list[Edge], seen: set[str]) -> None:
            if len(paths) >= max_paths:
                return
            nxt = [e for e in self.callees(node, min_certainty) if self.nodes.get(e.dst) and self.nodes[e.dst].kind in CALLABLE_KINDS
                   and e.dst not in seen]
            if not nxt or len(path) >= max_depth:
                if path:
                    paths.append(list(path))
                return
            for e in nxt[:12]:
                walk(e.dst, [*path, e], seen | {e.dst})
        walk(start, [], {start})
        return paths

    def reachable(self, start: str, min_certainty: str = "probable") -> set[str]:
        seen, queue = {start}, deque([start])
        while queue:
            node = queue.popleft()
            for e in self.callees(node, min_certainty):
                if e.dst not in seen:
                    seen.add(e.dst)
                    queue.append(e.dst)
        return seen

    def stats(self) -> dict:
        by = defaultdict(int)
        for e in self.edges:
            by[f"{e.kind}:{e.certainty}"] += 1
        kinds = defaultdict(int)
        for s in self.nodes.values():
            kinds[s.kind] += 1
        return {"nodes": len(self.nodes), "edges": len(self.edges), "by_kind": dict(kinds), "edges_by": dict(by),
                "certainties": {c: sum(1 for e in self.edges if e.certainty == c) for c in CERTAINTIES}}

    # -- sérialisation ----------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"nodes": [s.to_dict() for s in self.nodes.values()], "edges": [e.to_dict() for e in self.edges], "meta": self.meta}

    @staticmethod
    def from_dict(d: dict) -> Graph:
        g = Graph()
        g.meta = d.get("meta", {})
        for n in d.get("nodes", []):
            g.add_node(Symbol.from_dict(n))
        for e in d.get("edges", []):
            g.add_edge(**{k: e[k] for k in ("src", "dst", "kind", "certainty", "line", "file", "note")})
        return g


__all__ = ["DIR", "FILE", "Graph"]
