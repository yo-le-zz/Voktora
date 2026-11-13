"""Dépendances : inutilisées, obsolètes/abandonnées, vulnérables (base locale), et vérification de versions EN LIGNE facultative."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.model import Issue

ADV = json.loads((Path(__file__).resolve().parent.parent / "resources" / "advisories.json").read_text(encoding="utf-8"))


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def version_tuple(text: str) -> tuple:
    nums = re.findall(r"\d+", text.split("+")[0].split("-")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def lower_bound(spec: str) -> tuple[str, str] | None:
    """('==', '2.28.0') | ('>=', '2.0') | ('^', '1.2.3') | None — borne inférieure autorisée par la contrainte."""
    spec = spec.strip().strip('"')
    m = re.search(r"(==|~=|>=|\^|~|=)?\s*v?(\d+(?:\.\d+)*)", spec)
    if not m:
        return None
    op = m.group(1) or "="
    if op == "=" and not re.fullmatch(r"=?\s*v?\d.*", spec):
        return None
    return op, m.group(2)


def imported_roots(graph, files) -> dict[str, set[str]]:
    """Paquets externes réellement importés, par écosystème (depuis les arêtes `imports` vers des nœuds externes)."""
    used = {"pypi": set(), "npm": set(), "crates": set(), "cmake": set(), "go": set()}
    for e in graph.edges:
        if e.kind != "imports" or not e.dst.startswith("ext:"):
            continue
        lang = graph.nodes[e.dst].lang
        name = e.dst[4:]
        if lang == "python":
            used["pypi"].add(norm(name.split(".")[0]))
        elif lang == "javascript" or lang == "typescript":
            used["npm"].add(name)
        elif lang == "rust":
            used["crates"].add(norm(name))
    for fr in files.values():                                                  # include C/C++ et `use` bruts
        for imp in fr.imports:
            if fr.lang == "rust" and imp.get("rust"):
                used["crates"].add(norm(imp["module"].split("::")[0] or (imp["names"][0][0] if imp["names"] else "")))
    return used


def audit(deps: list[dict], graph, files, extra_used: set[str] | None = None) -> tuple[list[dict], list[Issue]]:
    used = imported_roots(graph, files)
    aliases = {norm(k): v for k, v in ADV["aliases"].items()}
    vulns = {(v["ecosystem"], norm(v["name"])): v for v in ADV["vulnerabilities"]}
    deprec = {(d["ecosystem"], norm(d["name"])): d for d in ADV["deprecated"]}
    rows, issues = [], []
    for d in deps:
        eco, name = d["ecosystem"], d["name"]
        key = norm(name)
        row = {**d, "used": None, "problems": []}
        if eco == "pypi":
            roots = {key, norm(aliases.get(key, key)), key.replace("-", "_"), norm(name.split("[")[0])}
            row["used"] = bool(roots & used["pypi"]) or bool({r.lower() for r in roots} & {u.lower() for u in used["pypi"]})
        elif eco == "npm":
            row["used"] = name in used["npm"] or any(u.startswith(name + "/") for u in used["npm"])
        elif eco == "crates":
            crate = norm(d.get("package") or name)
            row["used"] = crate in used["crates"] or key in used["crates"]
        if row["used"] is False and not d.get("dev") and d.get("group") != "dev" and not d.get("path"):
            caveat = {"pypi": "Elle peut être chargée dynamiquement (plugins, backends) ou fournir un outil en ligne de commande.",
                      "npm": "Elle peut servir uniquement dans la configuration/les scripts de build.",
                      "crates": "Elle peut servir via des macros dérivées (#[derive]), build.rs ou des fonctionnalités."}.get(eco, "")
            issues.append(Issue(d.get("file", ""), d.get("line", 1), "info", "UNUSED-DEP", f"Dépendance possiblement inutilisée : {name}",
                                f"Aucun import de « {name} » n'a été trouvé dans le code analysé. {caveat}",
                                "Vérifiez puis retirez-la si elle ne sert pas."))
            row["problems"].append("inutilisée ?")
        dep = deprec.get((eco, key))
        if dep:
            issues.append(Issue(d.get("file", ""), d.get("line", 1), "warn", "DEPRECATED-DEP", f"Dépendance obsolète : {name}",
                                dep["reason"], f"Remplacement conseillé : {dep['replacement']}"))
            row["problems"].append("obsolète")
        vuln = vulns.get((eco, key))
        lb = lower_bound(d.get("spec", "")) if vuln else None
        if vuln and lb:
            op, ver = lb
            if version_tuple(ver) < version_tuple(vuln["fixed"]):
                pinned = op in ("==", "=")
                issues.append(Issue(d.get("file", ""), d.get("line", 1), "error" if pinned else "warn", "VULNERABLE-DEP",
                                    f"{name} {ver} : {vuln['id']}" if pinned else f"{name} autorise la version vulnérable {ver} ({vuln['id']})",
                                    vuln["summary"], f"Exigez au moins {vuln['fixed']} (base d'avis locale, non exhaustive)."))
                row["problems"].append("vulnérable" if pinned else "borne basse vulnérable")
        rows.append(row)
    return rows, issues


def check_online(deps: list[dict], fetch) -> list[dict]:
    """Versions les plus récentes via PyPI / npm / crates.io. `fetch(url) -> bytes` est fourni par l'appelant (permission réseau).
    Retourne [{name, ecosystem, spec, latest, outdated}]."""
    out = []
    for d in deps:
        url = {"pypi": f"https://pypi.org/pypi/{d['name']}/json", "npm": f"https://registry.npmjs.org/{d['name']}/latest",
               "crates": f"https://crates.io/api/v1/crates/{d['name']}"}.get(d["ecosystem"])
        if not url or d.get("path"):
            continue
        try:
            data = json.loads(fetch(url))
            latest = (data.get("info", {}).get("version") if d["ecosystem"] == "pypi" else data.get("version")
                      if d["ecosystem"] == "npm" else data.get("crate", {}).get("max_stable_version"))
        except Exception as exc:  # noqa: BLE001
            out.append({**d, "latest": None, "error": str(exc)[:120], "outdated": None})
            continue
        lb = lower_bound(d.get("spec", ""))
        outdated = bool(latest and lb and lb[0] in ("==", "=") and version_tuple(lb[1]) < version_tuple(latest))
        major = bool(latest and lb and version_tuple(lb[1])[:1] < version_tuple(latest)[:1])
        out.append({**d, "latest": latest, "outdated": outdated, "major_behind": major})
    return out
