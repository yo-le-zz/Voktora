"""Mise en page en couches (Sugiyama simplifié, Python pur) : suppression des cycles, couches par plus long chemin,
ordre par barycentre. Entrée : View ; sortie : positions {id: (x, y)} + taille."""

from __future__ import annotations

from collections import defaultdict

NODE_W, NODE_H, GAP_X, GAP_Y = 190, 44, 36, 70


def layout(view: dict, horizontal: bool = False, max_row: int = 10) -> dict:
    ids = [n["id"] for n in view["nodes"]]
    if not ids:
        return {"pos": {}, "width": 0, "height": 0, "node_w": NODE_W, "node_h": NODE_H}
    idset = set(ids)
    succ: dict[str, set[str]] = defaultdict(set)
    pred: dict[str, set[str]] = defaultdict(set)
    for e in view["edges"]:
        if e["src"] in idset and e["dst"] in idset and e["src"] != e["dst"]:
            succ[e["src"]].add(e["dst"])
            pred[e["dst"]].add(e["src"])
    # 1. retirer les arcs de retour (DFS itératif)
    state: dict[str, int] = {}
    back: set[tuple[str, str]] = set()
    for root in ids:
        if state.get(root):
            continue
        stack = [(root, iter(sorted(succ[root])))]
        state[root] = 1
        while stack:
            node, it = stack[-1]
            for nxt in it:
                if state.get(nxt) == 1:
                    back.add((node, nxt))
                elif not state.get(nxt):
                    state[nxt] = 1
                    stack.append((nxt, iter(sorted(succ[nxt]))))
                    break
            else:
                state[node] = 2
                stack.pop()
    dag_succ = {n: {m for m in succ[n] if (n, m) not in back} for n in ids}
    dag_pred: dict[str, set[str]] = defaultdict(set)
    for n, ms in dag_succ.items():
        for m in ms:
            dag_pred[m].add(n)
    # 2. couches : plus long chemin depuis les sources (ordre topologique de Kahn)
    indeg = {n: len(dag_pred[n]) for n in ids}
    layer = {n: 0 for n in ids}
    queue = [n for n in ids if indeg[n] == 0]
    while queue:
        n = queue.pop(0)
        for m in sorted(dag_succ[n]):
            layer[m] = max(layer[m], layer[n] + 1)
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    layers: dict[int, list[str]] = defaultdict(list)
    for n in ids:
        layers[layer[n]].append(n)
    # 3. barycentres (quelques balayages)
    order = {n: i for lst in layers.values() for i, n in enumerate(lst)}
    for _ in range(4):
        for lv in sorted(layers):
            if lv:
                layers[lv].sort(key=lambda n: (sum(order[p] for p in dag_pred[n]) / len(dag_pred[n])) if dag_pred[n] else order[n])
                for i, n in enumerate(layers[lv]):
                    order[n] = i
        for lv in sorted(layers, reverse=True):
            layers[lv].sort(key=lambda n: (sum(order[s] for s in dag_succ[n]) / len(dag_succ[n])) if dag_succ[n] else order[n])
            for i, n in enumerate(layers[lv]):
                order[n] = i
    rows: list[list[str]] = []
    for lv in sorted(layers):                       # une couche trop large est répartie sur plusieurs rangées
        lst = layers[lv]
        for k in range(0, len(lst), max_row):
            rows.append(lst[k:k + max_row])
    widest = max(len(r) for r in rows)
    pos: dict[str, tuple[float, float]] = {}
    for ri, lst in enumerate(rows):
        offset = (widest - len(lst)) * (NODE_W + GAP_X) / 2
        for i, n in enumerate(lst):
            x, y = offset + i * (NODE_W + GAP_X), ri * (NODE_H + GAP_Y)
            pos[n] = (y, x) if horizontal else (x, y)
    width = max(x for x, _ in pos.values()) + NODE_W
    height = max(y for _, y in pos.values()) + NODE_H
    return {"pos": pos, "width": width, "height": height, "node_w": NODE_W, "node_h": NODE_H, "back_edges": sorted(back)}
