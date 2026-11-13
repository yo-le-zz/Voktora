"""Diagramme de dépendances en SVG (couches par profondeur d'import ; dossiers groupés en nœuds si le graphe est grand)."""

from __future__ import annotations

from html import escape

PALETTE = ["#4f6bed", "#2e9e6b", "#c7561e", "#9b59b6", "#3b82a0", "#b5651d", "#8e6bbf", "#24867a"]
NW, NH, GX, GY = 170, 34, 26, 56


def group_edges(files: list[str], edges: list[tuple[str, str]], max_nodes: int = 60, depth: int = 1) -> tuple[list[str], list[tuple[str, str]]]:
    if len(files) <= max_nodes:
        return files, edges

    def g(p):
        parts = p.split("/")
        return "/".join(parts[:depth]) if len(parts) > depth else "(racine)"
    nodes = sorted({g(f) for f in files})
    ed = sorted({(g(a), g(b)) for a, b in edges if g(a) != g(b)})
    if len(nodes) > max_nodes and depth < 4:
        return group_edges(files, edges, max_nodes, depth + 1)
    return nodes, ed


def layers(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    out_deg = {n: [] for n in nodes}
    for a, b in edges:
        if a in out_deg and b in out_deg:
            out_deg[a].append(b)
    level: dict[str, int] = {}
    visiting: set[str] = set()

    def depth(n: str) -> int:
        if n in level:
            return level[n]
        if n in visiting:
            return 0                                   # cycle : on coupe
        visiting.add(n)
        lv = 1 + max((depth(c) for c in out_deg[n]), default=-1)
        visiting.discard(n)
        level[n] = lv
        return lv
    for n in nodes:
        depth(n)
    return level


def svg(files: list[str], edges: list[tuple[str, str]], title: str = "Dépendances") -> str:
    nodes, ed = group_edges(files, edges)
    if not nodes:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="60"><text x="10" y="35">{escape(title)} : rien à afficher</text></svg>'
    lv = layers(nodes, ed)
    top = max(lv.values())
    rows: dict[int, list[str]] = {}
    for n in nodes:
        rows.setdefault(top - lv[n], []).append(n)          # les modules « feuilles » en bas
    pos = {}
    width = 0
    per_row = 8
    y = 40
    for r in sorted(rows):
        names = sorted(rows[r])
        for k in range(0, len(names), per_row):
            part = names[k:k + per_row]
            for i, n in enumerate(part):
                pos[n] = (20 + i * (NW + GX), y)
            width = max(width, 40 + len(part) * (NW + GX))
            y += NH + GY
    h = y + 10
    dirs = sorted({n.split("/")[0] for n in nodes})
    color = {d: PALETTE[i % len(PALETTE)] for i, d in enumerate(dirs)}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h}" width="{width}" height="{h}" font-family="sans-serif" font-size="11">',
           '<rect width="100%" height="100%" fill="#fff"/>',
           '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z" fill="#6b7088"/></marker></defs>',
           f'<text x="20" y="22" font-size="14" font-weight="600">{escape(title)}</text>']
    for a, b in ed:
        if a in pos and b in pos and a != b:
            (x1, y1), (x2, y2) = pos[a], pos[b]
            sy, ty = (y1 + NH, y2) if y2 > y1 else (y1, y2 + NH)
            sx, tx = x1 + NW / 2, x2 + NW / 2
            my = (sy + ty) / 2
            out.append(f'<path d="M{sx:.0f},{sy} C{sx:.0f},{my:.0f} {tx:.0f},{my:.0f} {tx:.0f},{ty}" fill="none" stroke="#6b7088" stroke-opacity=".55" marker-end="url(#a)"/>')
    for n, (x, yy) in pos.items():
        label = n if len(n) <= 26 else "…" + n[-25:]
        out.append(f'<g><title>{escape(n)}</title><rect x="{x}" y="{yy}" width="{NW}" height="{NH}" rx="6" fill="{color[n.split("/")[0]]}"/>'
                   f'<text x="{x + NW / 2}" y="{yy + 21}" fill="#fff" text-anchor="middle">{escape(label)}</text></g>')
    out.append("</svg>")
    return "\n".join(out)
