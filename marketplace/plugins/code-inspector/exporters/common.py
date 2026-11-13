"""Briques communes : échappement, dessin SVG d'une vue mise en page, tableaux Markdown."""

from __future__ import annotations

from html import escape

from ..services import layout as layout_mod

KIND_COLORS = {"dir": "#4f6bed", "file": "#3b82a0", "class": "#9b59b6", "struct": "#9b59b6", "trait": "#c0792b", "enum": "#8e6bbf",
               "function": "#2e9e6b", "method": "#24867a", "macro": "#b5651d", "external": "#7a7f8a", "unknown": "#b04a4a",
               "module": "#3b82a0"}
LANG_COLORS = {"python": "#3776ab", "rust": "#c7561e", "javascript": "#c9a600", "typescript": "#2f74c0", "cpp": "#00599c",
               "c": "#5c6bc0"}
CERT_STYLE = {"certain": ("", 1.6, 0.85), "probable": ("7 4", 1.4, 0.8), "inconnu": ("2 4", 1.2, 0.75)}
CERT_LABEL = {"certain": "certain", "probable": "probable", "inconnu": "inconnu"}


def esc(text) -> str:
    return escape(str(text), quote=True)


def md_table(headers: list[str], rows: list[list]) -> str:
    def cell(v):
        return str(v).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def short(text: str, n: int = 26) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


def node_fill(n: dict) -> str:
    return LANG_COLORS.get(n.get("lang", ""), "") if n["kind"] in ("file", "dir") and n.get("lang") in LANG_COLORS \
        else KIND_COLORS.get(n["kind"], "#4f6bed")


def svg_view(view: dict, lay: dict | None = None, dark: bool = False, title: bool = True) -> str:
    lay = lay or layout_mod.layout(view)
    pos, nw, nh = lay["pos"], lay["node_w"], lay["node_h"]
    pad = 30
    w, h = lay["width"] + 2 * pad, lay["height"] + 2 * pad + (24 if title else 0)
    bg, fg, line = ("#1e1e2e", "#e6e6f0", "#8a8fa3") if dark else ("#ffffff", "#1c1f2b", "#6b7088")
    top = pad + (24 if title else 0)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}" '
           f'font-family="Segoe UI, DejaVu Sans, sans-serif" font-size="12">',
           f'<rect width="100%" height="100%" fill="{bg}"/>',
           f'<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
           f'<path d="M0,0 L10,5 L0,10 z" fill="{line}"/></marker></defs>']
    if title:
        out.append(f'<text x="{pad}" y="24" fill="{fg}" font-size="15" font-weight="600">{esc(view["title"])}</text>')
    for e in view["edges"]:
        if e["src"] not in pos or e["dst"] not in pos:
            continue
        (x1, y1), (x2, y2) = pos[e["src"]], pos[e["dst"]]
        sx, sy = x1 + nw / 2 + pad, y1 + top - pad + (nh if y2 > y1 else 0)
        tx, ty = x2 + nw / 2 + pad, y2 + top - pad + (0 if y2 > y1 else nh)
        dash, width, op = CERT_STYLE.get(e["certainty"], CERT_STYLE["inconnu"])
        my = (sy + ty) / 2
        color = "#c7561e" if e["kind"] == "ffi" else line
        if e["src"] == e["dst"]:
            continue
        out.append(f'<path d="M{sx:.1f},{sy:.1f} C{sx:.1f},{my:.1f} {tx:.1f},{my:.1f} {tx:.1f},{ty:.1f}" fill="none" stroke="{color}" '
                   f'stroke-width="{width}" stroke-opacity="{op}"' + (f' stroke-dasharray="{dash}"' if dash else "")
                   + ' marker-end="url(#ar)"/>')
        if e.get("count", 1) > 1:
            out.append(f'<text x="{(sx + tx) / 2:.1f}" y="{my:.1f}" fill="{fg}" font-size="10" text-anchor="middle">{e["count"]}</text>')
    for n in view["nodes"]:
        if n["id"] not in pos:
            continue
        x, y = pos[n["id"]]
        x, y = x + pad, y + top - pad
        fill = node_fill(n)
        out.append(f'<g><title>{esc(n["id"])}</title><rect x="{x:.1f}" y="{y:.1f}" width="{nw}" height="{nh}" rx="8" fill="{fill}" '
                   f'fill-opacity="0.9" stroke="{fg}" stroke-opacity="0.25"/>'
                   f'<text x="{x + nw / 2:.1f}" y="{y + (18 if n.get("sub") else 27):.1f}" fill="#fff" text-anchor="middle" '
                   f'font-weight="600">{esc(short(n["label"], 24))}</text>'
                   + (f'<text x="{x + nw / 2:.1f}" y="{y + 34:.1f}" fill="#fff" fill-opacity="0.85" text-anchor="middle" '
                      f'font-size="10">{esc(short(n["sub"], 30))}</text>' if n.get("sub") else "") + "</g>")
    ly = h - 14
    out.append(f'<g font-size="10" fill="{fg}"><text x="{pad}" y="{ly}">— certain</text>'
               f'<text x="{pad + 90}" y="{ly}">- - probable</text><text x="{pad + 190}" y="{ly}">· · inconnu</text></g>')
    out.append("</svg>")
    return "\n".join(out)
