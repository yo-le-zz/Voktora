"""Export HTML autonome : diagrammes SVG interactifs (zoom, glisser, recherche, filtre de certitude), sans CDN."""

from __future__ import annotations

import json

from ..services import layout, views
from .common import esc, svg_view
from .md_x import report_md  # noqa: F401  (réutilisé pour le texte brut des fiches)

PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{--bg:#fff;--fg:#1c1f2b;--mut:#6b7088;--card:#f3f4f8;--line:#d9dbe6}
@media(prefers-color-scheme:dark){:root{--bg:#1e1e2e;--fg:#e6e6f0;--mut:#9a9fb5;--card:#27283a;--line:#3a3c52}}
body{margin:0;font:14px system-ui,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:14px 20px;border-bottom:1px solid var(--line)}h1{margin:0;font-size:18px}
nav{display:flex;gap:6px;padding:8px 20px;flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--line)}
nav button,nav label{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:5px 10px;cursor:pointer}
nav button.on{background:#4f6bed;color:#fff}nav input[type=search]{padding:5px 8px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg)}
.view{display:none;overflow:hidden;height:calc(100vh - 150px);position:relative}.view.on{display:block}
.view svg{width:100%;height:100%;cursor:grab}.dim{opacity:.12}.hit rect{stroke:#ffb300;stroke-width:3}
main{padding:0}.panel{padding:16px 20px;max-width:1100px}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
.cert-probable path[stroke-dasharray]{}.hide-probable path[stroke-dasharray="7 4"],.hide-inconnu path[stroke-dasharray="2 4"]{display:none}
code{background:var(--card);padding:1px 4px;border-radius:4px}
</style></head><body><header><h1>__TITLE__</h1><div style="color:var(--mut)">__SUB__</div></header>
<nav id="tabs"></nav><main id="main">__VIEWS__</main>
<script>
const V=document.querySelectorAll('.view'),T=document.getElementById('tabs');
V.forEach((v,i)=>{const b=document.createElement('button');b.textContent=v.dataset.title;b.onclick=()=>show(i);T.appendChild(b)});
function show(i){V.forEach((v,j)=>v.classList.toggle('on',i===j));[...T.querySelectorAll('button')].forEach((b,j)=>b.classList.toggle('on',i===j))}
const q=document.createElement('input');q.type='search';q.placeholder='Rechercher…';T.appendChild(q);
q.oninput=()=>{const s=q.value.toLowerCase();document.querySelectorAll('.view.on g').forEach(g=>{const t=(g.querySelector('title')||{}).textContent||'';const m=s&&t.toLowerCase().includes(s);g.classList.toggle('hit',!!m)})};
['probable','inconnu'].forEach(c=>{const l=document.createElement('label');l.innerHTML='<input type="checkbox" checked> '+c;l.firstChild.onchange=e=>V.forEach(v=>v.classList.toggle('hide-'+c,!e.target.checked));T.appendChild(l)});
V.forEach(v=>{const s=v.querySelector('svg');if(!s)return;const vb=s.viewBox.baseVal;let x=vb.x,y=vb.y,w=vb.width,h=vb.height,d=null;
const set=()=>s.setAttribute('viewBox',`${x} ${y} ${w} ${h}`);
s.addEventListener('wheel',e=>{e.preventDefault();const k=e.deltaY<0?.85:1.18;const r=s.getBoundingClientRect();const px=x+(e.clientX-r.left)/r.width*w,py=y+(e.clientY-r.top)/r.height*h;w*=k;h*=k;x=px-(e.clientX-r.left)/r.width*w;y=py-(e.clientY-r.top)/r.height*h;set()},{passive:false});
s.onmousedown=e=>{d=[e.clientX,e.clientY]};window.addEventListener('mouseup',()=>d=null);
window.addEventListener('mousemove',e=>{if(!d)return;const r=s.getBoundingClientRect();x-=(e.clientX-d[0])/r.width*w;y-=(e.clientY-d[1])/r.height*h;d=[e.clientX,e.clientY];set()})});
show(0);
</script></body></html>"""


def _table(headers, rows):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def render(a) -> str:
    r, g = a.report, a.graph
    vs = [("Architecture", views.architecture(g)), ("Fichiers", views.files(g)), ("Classes", views.classes(g, include_external=False)),
          ("Appels", views.calls(g))]
    ffi = views.ffi(g)
    if ffi["edges"]:
        vs.append(("Python × Rust", ffi))
    parts = []
    for name, v in vs:
        svg = svg_view(v, layout.layout(v), title=False) if v["nodes"] else "<p style='padding:20px'>Rien à afficher.</p>"
        parts.append(f'<section class="view" data-title="{esc(name)}">{svg}</section>')
    summary = _table(["Langage", "Fichiers", "Lignes", "Part"], [[x["name"], x["files"], x["loc"], f"{x['share']} %"] for x in r["languages"]])
    issues = _table(["Gravité", "Code", "Fichier:ligne", "Problème"], [[i.severity, i.code, f"{i.file}:{i.line}", i.title] for i in a.issues[:300]])
    funcs = [s for s in g.nodes.values() if s.kind in ("function", "method")][:500]
    cards = _table(["Fonction", "Fichier:ligne", "Signature", "Appelée par", "Appelle"],
                   [[s.name, f"{s.file}:{s.line}", s.signature,
                     ", ".join(e.src.split("::")[-1] for e in g.callers(s.id))[:150], ", ".join(e.dst.split("::")[-1] for e in g.callees(s.id))[:150]]
                    for s in funcs])
    parts.append(f'<section class="view" data-title="Résumé"><div class="panel">{summary}<h3>Problèmes</h3>{issues}</div></section>')
    parts.append(f'<section class="view" data-title="Fonctions"><div class="panel" style="overflow:auto;height:100%">{cards}</div></section>')
    sub = f"{r['graph']['nodes']} éléments · {r['graph']['edges']} relations · analysé le {esc(r['analyzed_at'])}"
    return PAGE.replace("__TITLE__", "Code Inspector — " + esc(a.root.rsplit("/", 1)[-1])).replace("__SUB__", sub).replace("__VIEWS__", "".join(parts))


def export(a, path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(a))


def data_json(a) -> str:
    return json.dumps(a.report, ensure_ascii=False)
