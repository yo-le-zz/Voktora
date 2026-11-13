"""Exports de la connaissance : Markdown, HTML (une page), PDF (Qt) et site statique (pages + recherche côté client, sans CDN)."""

from __future__ import annotations

import json
from pathlib import Path

from . import apidoc, text
from .wiki import Wiki, md_to_html, slug

CSS = ("body{font:15px/1.55 system-ui,sans-serif;margin:0;display:flex;color:#1c1f2b;background:#fff}nav{width:260px;padding:16px;border-right:1px solid #ddd;"
       "position:sticky;top:0;height:100vh;overflow:auto;box-sizing:border-box}main{padding:24px 40px;max-width:900px}nav a{display:block;padding:3px 0;color:#2f4fd0;text-decoration:none}"
       "a.broken{color:#c0392b}code{background:#f0f1f6;padding:1px 4px;border-radius:4px}pre{background:#f0f1f6;padding:10px;overflow:auto}table{border-collapse:collapse}"
       "td,th{border:1px solid #ddd;padding:4px 8px}#q{width:100%;padding:6px;margin-bottom:8px;box-sizing:border-box}"
       "@media(prefers-color-scheme:dark){body{background:#1e1e2e;color:#e6e6f0}nav{border-color:#3a3c52}nav a{color:#8fa4ff}code,pre{background:#2a2b3d}td,th{border-color:#3a3c52}}")


def to_markdown(wiki: Wiki, project: str, index=None) -> str:
    parts = [f"# {project} — connaissance du projet", ""]
    for name in sorted(wiki.pages, key=lambda n: (n != "Vue d'ensemble", n)):
        body = wiki.pages[name]["text"]
        parts += [f"<!-- page : {name} -->", body if body.lstrip().startswith("#") else f"## {name}\n\n{body}", ""]
    if index is not None and "API interne" not in wiki.pages:
        parts.append(apidoc.api_markdown(index))
    return "\n".join(parts) + "\n"


def page_html(wiki: Wiki, name: str, anchor: bool = False) -> str:
    exists = {n.lower() for n in wiki.pages}
    href = (lambda n: "#" + slug(n)) if anchor else (lambda n: slug(n) + ".html")
    return md_to_html(wiki.pages[name]["text"], href, lambda n: n.lower() in exists)


def to_html(wiki: Wiki, project: str, svg: str = "") -> str:
    sections = "\n".join(f'<section id="{slug(n)}">{page_html(wiki, n, True)}</section>' for n in sorted(wiki.pages, key=lambda n: (n != "Vue d'ensemble", n)))
    nav = "".join(f'<a href="#{slug(n)}">{n}</a>' for n in sorted(wiki.pages, key=lambda n: (n != "Vue d'ensemble", n)))
    html = f"<!doctype html><meta charset='utf-8'><title>{project}</title><style>{CSS}</style><nav><strong>{project}</strong>{nav}</nav><main>{sections}"
    if svg:
        html += f"<section><h2>Diagramme</h2>{svg}</section>"
    return html + "</main>"


def to_pdf(wiki: Wiki, project: str, path, svg: str = "") -> None:
    from PySide6.QtCore import QByteArray, QMarginsF, QSizeF
    from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextDocument
    from PySide6.QtSvg import QSvgRenderer
    doc = QTextDocument()
    doc.setMarkdown(to_markdown(wiki, project).replace("[[", "").replace("]]", ""))
    if svg:
        r = QSvgRenderer(QByteArray(svg.encode()))
        size = r.defaultSize()
        sc = min(1.0, 1400 / max(size.width(), 1))
        img = QImage(max(int(size.width() * sc), 1), max(int(size.height() * sc), 1), QImage.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        r.render(p)
        p.end()
        doc.addResource(3, "dep.png", img)
        from PySide6.QtGui import QTextCursor
        cur = QTextCursor(doc)
        cur.movePosition(QTextCursor.End)
        cur.insertHtml("<h2>Diagramme de dépendances</h2><img src='dep.png' width='620'>")
    w = QPdfWriter(str(path))
    w.setPageSize(QPageSize(QPageSize.A4))
    w.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
    w.setTitle(project)
    doc.setPageSize(QSizeF(w.width(), w.height()))
    doc.print_(w)


SEARCH_JS = ("""const idx=__IDX__;const q=document.getElementById('q'),out=document.getElementById('res');
q.oninput=()=>{const t=q.value.toLowerCase().split(/\\W+/).filter(x=>x.length>1);out.innerHTML='';if(!t.length)return;
const hits=idx.map(p=>({p,s:t.reduce((a,w)=>a+(p.t.includes(w)?1:0)+(p.n.toLowerCase().includes(w)?3:0),0)})).filter(x=>x.s>0).sort((a,b)=>b.s-a.s).slice(0,15);
out.innerHTML=hits.map(h=>`<a href="${h.p.u}">${h.p.n}</a>`).join('')};""")


def to_site(wiki: Wiki, project: str, folder, svg: str = "") -> list[str]:
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    names = sorted(wiki.pages, key=lambda n: (n != "Vue d'ensemble", n))
    nav = "".join(f'<a href="{slug(n)}.html">{n}</a>' for n in names)
    idx = [{"n": n, "u": slug(n) + ".html", "t": " ".join(dict.fromkeys(text.tokens(wiki.pages[n]["text"])))[:6000]} for n in names]
    written = []
    for n in names:
        body = page_html(wiki, n) + (f"<h2>Diagramme</h2>{svg}" if svg and n == "Dépendances" else "")
        back = wiki.backlinks(n)
        foot = ("<hr><p>Pages liées : " + ", ".join(f'<a href="{slug(b)}.html">{b}</a>' for b in back) + "</p>") if back else ""
        (root / f"{slug(n)}.html").write_text(
            f"<!doctype html><html lang='fr'><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>{n} — {project}</title><style>{CSS}</style>"
            f"<nav><strong>{project}</strong><input id='q' type='search' placeholder='Rechercher…'><div id='res'></div>{nav}</nav><main>{body}{foot}</main>"
            f"<script src='search.js'></script></html>", encoding="utf-8")
        written.append(f"{slug(n)}.html")
    (root / "search.js").write_text(SEARCH_JS.replace("__IDX__", json.dumps(idx, ensure_ascii=False)), encoding="utf-8")
    first = slug(names[0]) if names else "page"
    (root / "index.html").write_text(f"<!doctype html><meta http-equiv='refresh' content='0;url={first}.html'><a href='{first}.html'>{project}</a>", encoding="utf-8")
    return [*written, "search.js", "index.html"]
