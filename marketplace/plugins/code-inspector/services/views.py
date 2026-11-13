"""Vues du graphe : chacune renvoie un `View` (nœuds + arêtes agrégées) que layout/exporteurs/interface savent afficher."""

from __future__ import annotations

from collections import defaultdict

from ..core.model import (
    CALLABLE_KINDS,
    CALLS,
    DECORATES,
    EXTERNAL,
    FFI,
    IMPLEMENTS,
    IMPORTS,
    INHERITS,
    RANK,
    REFERENCES,
    TYPE_KINDS,
    UNKNOWN_NODE,
)

VIEWS = {"architecture": "Architecture globale", "tree": "Arborescence détaillée", "files": "Dépendances entre fichiers",
         "classes": "Relations entre classes", "calls": "Graphe des appels", "chains": "Chaînes d'exécution",
         "ffi": "Ponts Python × Rust"}
CALL_KINDS = {CALLS, REFERENCES, FFI, DECORATES}


def view(title: str, nodes: list[dict], edges: list[dict], notes: str = "") -> dict:
    return {"title": title, "nodes": nodes, "edges": edges, "notes": notes}


def _node(graph, nid, label=None, group="", extra=None) -> dict:
    s = graph.nodes.get(nid)
    return {"id": nid, "label": label or (s.name if s else nid), "kind": s.kind if s else "?", "lang": s.lang if s else "",
            "file": s.file if s else "", "line": s.line if s else 0, "group": group, **(extra or {})}


def _agg(edges: list[tuple[str, str, str, str]]) -> list[dict]:
    """[(src, dst, kind, certainty)] → arêtes agrégées {src,dst,kind,certainty (la plus faible), count}."""
    bucket: dict[tuple, dict] = {}
    for src, dst, kind, cert in edges:
        b = bucket.setdefault((src, dst, kind), {"src": src, "dst": dst, "kind": kind, "certainty": cert, "count": 0})
        b["count"] += 1
        if RANK[cert] < RANK[b["certainty"]]:
            b["certainty"] = cert
    return list(bucket.values())


def group_of(path: str, depth: int) -> str:
    parts = path.split("/")
    return "/".join(parts[:depth]) if len(parts) > depth else (parts[0] if len(parts) > 1 else "(racine)")


def architecture(graph, depth: int = 2, include_external: bool = True, min_certainty: str = "inconnu") -> dict:
    """Une boîte par dossier (profondeur `depth`) ; flèches = nombre de dépendances (imports et appels) entre dossiers."""
    groups: dict[str, dict] = {}
    for s in graph.nodes.values():
        if s.kind == "file":
            g = group_of(s.file, depth)
            d = groups.setdefault(g, {"files": 0, "loc": 0, "langs": defaultdict(int)})
            d["files"] += 1
            d["loc"] += s.meta.get("loc", 0)
            d["langs"][s.lang] += 1
    raw = []
    for e in graph.edges:
        if e.kind not in (IMPORTS, CALLS, FFI, INHERITS) or RANK[e.certainty] < RANK[min_certainty]:
            continue
        a = graph.nodes.get(e.src)
        b = graph.nodes.get(e.dst)
        if a is None or b is None or not a.file:
            continue
        ga = group_of(a.file, depth)
        if b.kind == EXTERNAL:
            if include_external and e.kind == IMPORTS:
                raw.append((ga, "ext:" + b.name, IMPORTS, e.certainty))
            continue
        if not b.file:
            continue
        gb = group_of(b.file, depth)
        if ga != gb:
            raw.append((ga, gb, FFI if e.kind == FFI else IMPORTS if e.kind == IMPORTS else CALLS, e.certainty))
    nodes = [{"id": g, "label": g, "kind": "dir", "lang": max(d["langs"], key=d["langs"].get) if d["langs"] else "",
              "file": "", "line": 0, "group": g, "sub": f"{d['files']} fichiers · {d['loc']} lignes"} for g, d in sorted(groups.items())]
    ext_used = {dst for _, dst, _, _ in raw if dst.startswith("ext:")}
    nodes += [{"id": x, "label": x[4:], "kind": "external", "lang": "", "file": "", "line": 0, "group": "externe"}
              for x in sorted(ext_used)]
    return view("Architecture globale", nodes, _agg(raw),
                "Chaque boîte est un dossier ; une flèche indique des fichiers qui en importent/appellent d'autres (le nombre est affiché).")


def tree(graph, with_symbols: bool = True) -> list[dict]:
    """Arborescence aplatie : [{depth, id, label, kind, info}] dossiers → fichiers → classes → méthodes."""
    rows: list[dict] = []

    def walk(parent: str, depth: int) -> None:
        kids = [s for s in graph.nodes.values() if s.parent == parent and s.kind in ("dir", "file") or
                (with_symbols and s.parent == parent and s.kind not in ("external", "unknown"))]
        kids.sort(key=lambda s: (s.kind != "dir", s.kind != "file", s.line, s.name.lower()))
        for s in kids:
            info = ""
            if s.kind == "file":
                info = f"{s.lang} · {s.meta.get('loc', 0)} lignes"
            elif s.kind in CALLABLE_KINDS:
                info = s.signature
            elif s.kind in TYPE_KINDS:
                info = f"ligne {s.line}"
            rows.append({"depth": depth, "id": s.id, "label": s.name, "kind": s.kind, "info": info, "file": s.file, "line": s.line})
            walk(s.id, depth + 1)
    walk("", 0)
    return rows


def files(graph, min_certainty: str = "inconnu", include_external: bool = False, focus: str = "", depth: int = 2) -> dict:
    nodes, raw = {}, []
    for e in graph.edges:
        if e.kind != IMPORTS or RANK[e.certainty] < RANK[min_certainty]:
            continue
        a, b = graph.nodes.get(e.src), graph.nodes.get(e.dst)
        if a is None or b is None or a.kind != "file":
            continue
        if b.kind == EXTERNAL and not include_external:
            continue
        nodes[a.id] = _node(graph, a.id, group=group_of(a.file, 1))
        nodes[b.id] = _node(graph, b.id, group="externe" if b.kind == EXTERNAL else group_of(b.file, 1))
        raw.append((a.id, b.id, IMPORTS, e.certainty))
    edges = _agg(raw)
    if focus and focus in nodes:
        keep = {focus}
        frontier = {focus}
        for _ in range(depth):
            nxt = set()
            for e in edges:
                if e["src"] in frontier:
                    nxt.add(e["dst"])
                if e["dst"] in frontier:
                    nxt.add(e["src"])
            keep |= nxt
            frontier = nxt
        nodes = {k: v for k, v in nodes.items() if k in keep}
        edges = [e for e in edges if e["src"] in keep and e["dst"] in keep]
    return view("Dépendances entre fichiers", list(nodes.values()), edges)


def classes(graph, min_certainty: str = "inconnu", include_external: bool = True) -> dict:
    nodes, raw = {}, []
    for s in graph.nodes.values():
        if s.kind in TYPE_KINDS:
            n_methods = len([c for c in graph.children(s.id) if c.kind == "method"])
            nodes[s.id] = _node(graph, s.id, group=group_of(s.file, 1), extra={"sub": f"{n_methods} méthodes"})
    for e in graph.edges:
        if e.kind not in (INHERITS, IMPLEMENTS) or RANK[e.certainty] < RANK[min_certainty] or e.src not in nodes:
            continue
        dst = graph.nodes.get(e.dst)
        if dst is None:
            continue
        if dst.kind == EXTERNAL:
            if not include_external:
                continue
            nodes[dst.id] = _node(graph, dst.id, group="externe")
        elif dst.id not in nodes:
            continue
        raw.append((e.src, e.dst, e.kind, e.certainty))
    return view("Relations entre classes", list(nodes.values()), _agg(raw), "Flèche : « hérite de » / « implémente ».")


def calls(graph, focus: str = "", depth: int = 2, direction: str = "both", min_certainty: str = "inconnu", max_nodes: int = 120,
          include_unknown: bool = True) -> dict:
    """Graphe d'appels. Sans `focus` : les fonctions les plus connectées ; avec : voisinage à `depth` (appelants/appelés)."""
    def ok(nid):
        s = graph.nodes.get(nid)
        return s is not None and (s.kind in CALLABLE_KINDS or s.kind == "class" or (include_unknown and s.kind == UNKNOWN_NODE)
                                  or s.kind in TYPE_KINDS) and (s.kind != EXTERNAL)
    keep: set[str] = set()
    if focus and focus in graph.nodes:
        keep = {focus}
        frontier = {focus}
        for _ in range(depth):
            nxt = set()
            for n in frontier:
                if direction in ("both", "out"):
                    nxt |= {e.dst for e in graph.out_edges(n, CALL_KINDS, min_certainty) if ok(e.dst)}
                if direction in ("both", "in"):
                    nxt |= {e.src for e in graph.in_edges(n, CALL_KINDS, min_certainty) if ok(e.src)}
            keep |= nxt
            frontier = nxt
            if len(keep) > max_nodes:
                break
    else:
        degree: dict[str, int] = defaultdict(int)
        for e in graph.edges:
            if e.kind in CALL_KINDS and RANK[e.certainty] >= RANK[min_certainty] and ok(e.src) and ok(e.dst):
                degree[e.src] += 1
                degree[e.dst] += 1
        keep = set(sorted(degree, key=lambda k: -degree[k])[:max_nodes])
    if len(keep) > max_nodes:
        keep = set(sorted(keep, key=lambda k: (k != focus, -(len(graph.callers(k)) + len(graph.callees(k)))))[:max_nodes])
    nodes = {k: _node(graph, k, group=group_of(graph.nodes[k].file, 1) if graph.nodes[k].file else "?") for k in keep if k in graph.nodes}
    raw = [(e.src, e.dst, e.kind, e.certainty) for e in graph.edges
           if e.kind in CALL_KINDS and e.src in keep and e.dst in keep and RANK[e.certainty] >= RANK[min_certainty]]
    notes = "Traits pleins : certain · tirets : probable · pointillés : inconnu."
    return view("Graphe des appels" + (f" — {graph.nodes[focus].name}" if focus in graph.nodes else ""), list(nodes.values()),
                _agg(raw), notes)


def chains(graph, entries: list[dict], max_depth: int = 7, min_certainty: str = "probable", per_entry: int = 6) -> list[dict]:
    """Chaînes principales : pour chaque point d'entrée, les plus longs chemins d'appels (sans cycle)."""
    out = []
    for ent in entries:
        sid = ent["symbol"]
        if sid not in graph.nodes or graph.nodes[sid].kind not in (*CALLABLE_KINDS, "file"):
            continue
        paths = graph.chains(sid, max_depth, min_certainty, 300)
        paths.sort(key=lambda p: (-len(p), min(RANK[e.certainty] for e in p) * -1))
        shown = []
        for p in paths[:per_entry]:
            shown.append({"steps": [sid, *[e.dst for e in p]], "certainties": [e.certainty for e in p],
                          "weakest": min((e.certainty for e in p), key=lambda c: RANK[c])})
        if shown:
            out.append({"entry": sid, "kind": ent["kind"], "file": ent["file"], "chains": shown,
                        "reachable": len(graph.reachable(sid, min_certainty))})
    return out


def ffi(graph) -> dict:
    nodes, raw = {}, []
    for e in graph.edges:
        if e.kind != FFI:
            continue
        for nid in (e.src, e.dst):
            s = graph.nodes.get(nid)
            if s:
                nodes[nid] = _node(graph, nid, group=s.lang or "?")
        raw.append((e.src, e.dst, FFI, e.certainty))
    edges = _agg(raw)
    for ed in edges:
        notes = sorted({x.note for x in graph.out_edges(ed["src"], {FFI}) if x.dst == ed["dst"] and x.note})
        ed["note"] = "; ".join(notes)
    return view("Ponts Python × Rust", list(nodes.values()), edges,
                "Les notes indiquent la direction (python→rust / rust→python) et le mécanisme (PyO3, ctypes, sous-processus).")
