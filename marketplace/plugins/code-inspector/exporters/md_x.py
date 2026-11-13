"""Export Markdown : rapport + architecture + diagrammes Mermaid + chaînes d'exécution + index des fonctions."""

from __future__ import annotations

from ..core.model import CALLABLE_KINDS, RANK
from ..services import views
from .common import md_table

CERT_ARROW = {"certain": "-->", "probable": "-.->", "inconnu": "-.-"}


def mermaid(view: dict, max_nodes: int = 60) -> str:
    ids = {}
    lines = ["```mermaid", "graph LR"]
    for n in view["nodes"][:max_nodes]:
        ids[n["id"]] = f"n{len(ids)}"
        label = n["label"].replace('"', "'")
        lines.append(f'  {ids[n["id"]]}["{label}"]')
    for e in view["edges"]:
        if e["src"] in ids and e["dst"] in ids:
            lines.append(f'  {ids[e["src"]]} {CERT_ARROW.get(e["certainty"], "-.->")} {ids[e["dst"]]}')
    lines.append("```")
    return "\n".join(lines)


def report_md(a, with_functions: bool = True, max_functions: int = 400) -> str:
    r, g = a.report, a.graph
    out = [f"# Rapport Code Inspector — {a.root.rsplit('/', 1)[-1]}", "",
           f"_Analysé le {r['analyzed_at']} en {r['duration']} s — {r['graph']['nodes']} éléments, {r['graph']['edges']} relations._", "",
           "## Résumé", "",
           md_table(["Langage", "Fichiers", "Lignes", "Part"], [[x["name"], x["files"], x["loc"], f"{x['share']} %"] for x in r["languages"]]),
           ""]
    if r["frameworks"]:
        out += ["**Frameworks / bibliothèques clés** : " + ", ".join(r["frameworks"]), ""]
    c = r["graph"]["certainties"]
    out += [f"**Fiabilité des relations** : {c['certain']} certaines, {c['probable']} probables, {c['inconnu']} inconnues "
            "(rien n'est inventé : ce qui ne peut pas être établi est marqué « inconnu »).", ""]
    out += ["## Points d'entrée", ""]
    out += [md_table(["Type", "Fichier", "Ligne", "Détail"], [[e["kind"], e["file"], e.get("line", ""), e.get("name", e.get("target", ""))]
                                                            for e in r["entry_points"]]) if r["entry_points"] else "_Aucun point d'entrée détecté._", ""]
    out += ["## Architecture globale", "", mermaid(views.architecture(g)), ""]
    classes = views.classes(g, include_external=False)
    if classes["edges"]:
        out += ["## Relations entre classes", "", mermaid(classes), ""]
    ffi = views.ffi(g)
    if ffi["edges"]:
        out += ["## Ponts Python × Rust", "", mermaid(ffi), "",
                md_table(["De", "Vers", "Certitude", "Détail"], [[x["src"], x["dst"], x["certainty"], x.get("note", "")] for x in ffi["edges"]]), ""]
    chains = views.chains(g, r["entry_points"])
    if chains:
        out += ["## Chaînes d'exécution principales", ""]
        for ch in chains:
            out += [f"### {ch['entry'].split('::')[-1]} ({ch['kind']}) — {ch['reachable']} éléments atteignables", ""]
            for p in ch["chains"]:
                out.append("- " + " → ".join(f"`{s.split('::')[-1]}`" for s in p["steps"]) + f"  _(maillon le plus faible : {p['weakest']})_")
            out.append("")
    out += ["## Problèmes détectés", "", f"{r['issues']['total']} au total : " + ", ".join(f"{v} {k}" for k, v in r["issues"]["by_severity"].items()), ""]
    out += [md_table(["Gravité", "Code", "Fichier:ligne", "Problème", "Piste"],
                     [[i.severity, i.code, f"{i.file}:{i.line}", i.title, i.hint] for i in a.issues[:200]]), ""]
    if r["hotspots"]:
        out += ["## Points chauds (complexité)", "", md_table(["Fonction", "Fichier:ligne", "Complexité", "Lignes"],
                                                           [[h["name"], f"{h['file']}:{h['line']}", h["complexity"], h["lines"]] for h in r["hotspots"]]), ""]
    if r["dependencies"]:
        out += ["## Dépendances", "", md_table(["Nom", "Écosystème", "Contrainte", "Utilisée ?", "Remarques"],
                                              [[d["name"], d["ecosystem"], d.get("spec", ""), {True: "oui", False: "non trouvée", None: "?"}[d["used"]],
                                                ", ".join(d["problems"])] for d in r["dependencies"]]), ""]
    if r["dead_code"]:
        out += ["## Fonctions jamais appelées dans le projet", "",
                "_Candidats seulement : une fonction peut servir par import externe, rappel dynamique ou point d'entrée non détecté._", "",
                md_table(["Fonction", "Fichier:ligne"], [[d["name"], f"{d['file']}:{d['line']}"] for d in r["dead_code"][:100]]), ""]
    if with_functions:
        out += ["## Index des fonctions", ""]
        funcs = sorted((s for s in g.nodes.values() if s.kind in CALLABLE_KINDS), key=lambda s: (s.file, s.line))[:max_functions]
        for s in funcs:
            callers = [e for e in g.callers(s.id) if RANK[e.certainty] >= 1][:8]
            callees = [e for e in g.callees(s.id) if RANK[e.certainty] >= 1][:8]
            out += [f"### `{s.name}`", f"- Fichier : `{s.file}:{s.line}`", f"- Signature : `{s.signature}`"]
            if s.doc:
                out.append(f"- Rôle : {s.doc}")
            out.append("- Appelée par : " + (", ".join(f"`{e.src.split('::')[-1]}` ({e.certainty})" for e in callers) or "—"))
            out.append("- Appelle : " + (", ".join(f"`{e.dst.split('::')[-1]}` ({e.certainty})" for e in callees) or "—"))
            out.append("")
    return "\n".join(out) + "\n"


def export(analysis, path, **kw) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(report_md(analysis, **kw))
