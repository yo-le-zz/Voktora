"""Validation d'un workflow : blocs et ports connus, paramètres requis, liens valides, cycles, blocs inaccessibles, boucles et parallèles bien formés."""

from __future__ import annotations

from . import blocks, cron
from . import expr as ex

TRIGGER_KINDS = ("manual", "on_start", "on_open", "file_change", "git_head", "github_poll", "http_in", "interval", "cron")


def new_workflow(name: str = "Nouveau workflow") -> dict:
    return {"schema": 1, "name": name, "description": "", "nodes": [{"id": "start", "type": "start", "label": "Démarrage", "params": {}, "options": {}, "x": 0, "y": 0}],
            "edges": [], "triggers": [{"kind": "manual"}], "enabled": True}


def validate(wf: dict) -> dict:
    """Retourne {"errors": [...], "warnings": [...]}."""
    errors: list[str] = []
    warnings: list[str] = []
    nodes = {n.get("id"): n for n in wf.get("nodes", [])}
    if len(nodes) != len(wf.get("nodes", [])):
        errors.append("Identifiants de blocs en double.")
    if not wf.get("name", "").strip():
        errors.append("Le workflow n'a pas de nom.")
    starts = [n for n in nodes.values() if n.get("type") == "start"]
    if len(starts) != 1:
        errors.append(f"Il faut exactement un bloc « Démarrage » (trouvé : {len(starts)}).")
    for n in nodes.values():
        b = blocks.REGISTRY.get(n.get("type"))
        if not b:
            errors.append(f"Bloc « {n.get('id')} » : type inconnu ({n.get('type')}).")
            continue
        params = n.get("params", {})
        for q in b.params:
            if q.required and str(params.get(q.name, q.default)).strip() == "":
                errors.append(f"Bloc « {n['id']} » : paramètre « {q.name} » requis.")
            if q.kind == "expr" and q.name in params:
                try:
                    ex.parse_expression(str(params[q.name]))
                except ex.ExprError as exc:
                    errors.append(f"Bloc « {n['id']} » : expression « {q.name} » invalide ({exc}).")
            if q.kind == "int" and q.name in params:
                try:
                    int(params[q.name])
                except (TypeError, ValueError):
                    errors.append(f"Bloc « {n['id']} » : « {q.name} » doit être un nombre entier.")
        for e in (params or {}).values():
            if isinstance(e, str) and "{{" in e:
                for frag in ex.TEMPLATE.findall(e):
                    try:
                        ex.parse_expression(frag)
                    except ex.ExprError as exc:
                        errors.append(f"Bloc « {n['id']} » : modèle {{{{{frag.strip()}}}}} invalide ({exc}).")
    out: dict[str, list] = {i: [] for i in nodes}
    seen_ports = set()
    for e in wf.get("edges", []):
        s, d, port = e.get("src"), e.get("dst"), e.get("port", "out")
        if s not in nodes or d not in nodes:
            errors.append(f"Lien vers un bloc inexistant : {s} → {d}")
            continue
        b = blocks.REGISTRY.get(nodes[s].get("type"))
        if b and port not in b.ports:
            errors.append(f"Bloc « {s} » : le port « {port} » n'existe pas (ports : {', '.join(b.ports) or 'aucun'}).")
        if s == d:
            errors.append(f"Bloc « {s} » relié à lui-même.")
        if nodes[d].get("type") == "start":
            errors.append("Aucun lien ne peut aboutir au bloc « Démarrage ».")
        if (s, d, port) in seen_ports:
            warnings.append(f"Lien en double : {s} → {d}")
        seen_ports.add((s, d, port))
        out[s].append((port, d))
    # cycles
    state: dict[str, int] = {}

    def dfs(n) -> bool:
        state[n] = 1
        for _p, d in out.get(n, []):
            if state.get(d) == 1 or (state.get(d) is None and dfs(d)):
                return True
        state[n] = 2
        return False
    if any(state.get(n) is None and dfs(n) for n in nodes):
        errors.append("Le workflow contient un cycle : utilisez un bloc de boucle plutôt qu'un lien en retour.")
    # accessibilité
    if len(starts) == 1:
        reach, stack = set(), [starts[0]["id"]]
        while stack:
            n = stack.pop()
            if n in reach:
                continue
            reach.add(n)
            stack += [d for _p, d in out.get(n, [])]
        warnings += [f"Bloc « {i} » inaccessible depuis le démarrage." for i in nodes if i not in reach]
    for n in nodes.values():
        t = n.get("type")
        ports = {p for p, _d in out.get(n.get("id"), [])}
        if t in ("loop_for", "loop_while") and "body" not in ports:
            warnings.append(f"Boucle « {n['id']} » : rien n'est relié au port « body ».")
        if t == "parallel" and len(out.get(n["id"], [])) < 2:
            warnings.append(f"Parallèle « {n['id']} » : moins de deux branches.")
        if t == "if" and not ({"true", "false"} & ports):
            warnings.append(f"Condition « {n['id']} » : aucune branche reliée.")
    for tr in wf.get("triggers", []):
        k = tr.get("kind")
        if k not in TRIGGER_KINDS:
            errors.append(f"Déclencheur inconnu : {k}")
        elif k == "cron":
            try:
                cron.parse(tr.get("expr", ""))
            except ValueError as exc:
                errors.append(f"Déclencheur cron invalide : {exc}")
        elif k == "interval" and float(tr.get("seconds", 0) or 0) < 1:
            errors.append("Intervalle : au moins 1 seconde.")
        elif k == "http_in" and len(str(tr.get("token", ""))) < 16:
            errors.append("Déclencheur HTTP entrant : un jeton d'au moins 16 caractères est obligatoire.")
        elif k == "file_change" and not tr.get("pattern"):
            errors.append("Déclencheur de fichiers : motif requis.")
    return {"errors": errors, "warnings": warnings}
