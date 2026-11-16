"""Logique pure (sans Qt) de l'édition des blocs : validation des champs, résumés, paires clé/valeur, variables en amont, copier/coller, réordonnancement, historique."""

from __future__ import annotations

import ast
import copy
import json
import re
import shlex
from dataclasses import dataclass

from . import blocks
from . import expr as ex

NUMERIC = ("int", "number", "duration")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KIND_LABELS = {"str": "Texte court", "text": "Texte multiligne", "code": "Code", "int": "Nombre entier", "number": "Nombre", "duration": "Durée", "bool": "Case à cocher",
               "choice": "Menu", "path": "Chemin", "var": "Variable", "expr": "Expression", "json": "JSON", "pairs": "Liste clé / valeur"}


@dataclass(frozen=True)
class Issue:
    level: str          # "error" | "warning"
    message: str

    @property
    def is_error(self) -> bool:
        return self.level == "error"


def has_template(value) -> bool:
    return isinstance(value, str) and "{{" in value


def param_label(q: blocks.Param) -> str:
    return q.label or q.name


def choice_items(q: blocks.Param) -> list[tuple[str, str]]:
    """[(valeur, libellé)] d'un menu."""
    labels = list(q.choice_labels)
    return [(c, labels[i] if i < len(labels) and labels[i] else (c or "(vide)")) for i, c in enumerate(q.choices)]


def choice_label(q: blocks.Param, value) -> str:
    return dict(choice_items(q)).get(str(value), str(value))


# ------------------------------------------------------------------------------------------------ paires clé / valeur
def parse_pairs(value) -> list[tuple[str, str]]:
    """Accepte un dict, une chaîne JSON {nom: valeur} ou une liste de paires ; lève ValueError si invalide."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise ValueError(f"JSON invalide : {exc}") from exc
    if isinstance(value, dict):
        return [(str(k), "" if v is None else (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))) for k, v in value.items()]
    if isinstance(value, (list, tuple)):
        out = []
        for it in value:
            if isinstance(it, (list, tuple)) and len(it) == 2:
                out.append((str(it[0]), str(it[1])))
            else:
                raise ValueError("Une liste de paires [nom, valeur] est attendue.")
        return out
    raise ValueError("Un objet {nom: valeur} est attendu.")


def dump_pairs(pairs) -> str:
    """Paires -> chaîne JSON {nom: valeur} (format historique) ; les noms vides sont ignorés."""
    return json.dumps({str(k): str(v) for k, v in pairs if str(k).strip()}, ensure_ascii=False)


# ------------------------------------------------------------------------------------------------ nombres
def to_number(q: blocks.Param, value):
    """Convertit en int/float selon le type ; lève ValueError."""
    if isinstance(value, bool):
        raise ValueError("nombre attendu")
    if q.kind == "int":
        f = float(value)
        if f != int(f):
            raise ValueError("entier attendu")
        return int(f)
    return float(value)


# ------------------------------------------------------------------------------------------------ validation d'un champ
def _special(type_: str, q: blocks.Param, value) -> Issue | None:
    text = str(value)
    if has_template(text) or not text.strip():
        return None
    if q.name == "url" and type_ == "http_request" and not re.match(r"^https?://\S+", text.strip(), re.I):
        return Issue("error", "L'adresse doit commencer par http:// ou https://.")
    if q.name == "command" and q.kind == "str":
        try:
            if not shlex.split(text):
                return Issue("error", "Commande vide.")
        except ValueError as exc:
            return Issue("error", f"Commande invalide : {exc}.")
    if q.name == "pattern" and type_ == "project_search":
        try:
            re.compile(text)
        except re.error as exc:
            return Issue("error", f"Expression régulière invalide : {exc}.")
    return None


def validate_param(type_or_block, q: blocks.Param, value, *, strict_range: bool = False) -> Issue | None:
    """Vérifie une valeur selon le schéma. None = valide. Les dépassements de bornes sont des avertissements."""
    type_ = type_or_block if isinstance(type_or_block, str) else type_or_block.type
    empty = value is None or (isinstance(value, str) and not value.strip()) or (q.kind == "pairs" and value in ({}, []))
    if empty:
        if q.kind == "bool" or (q.kind == "choice" and "" in q.choices):
            return None
        return Issue("error", "Ce champ est obligatoire.") if q.required else None
    if has_template(value) and q.templated:
        for frag in ex.TEMPLATE.findall(value):
            try:
                ex.parse_expression(frag)
            except ex.ExprError as exc:
                return Issue("error", f"Le modèle {{{{ {frag.strip()} }}}} est invalide : {exc}.")
        if q.kind in (*NUMERIC, "choice", "bool", "var"):
            return None
    k = q.kind
    if k == "expr":
        try:
            ex.parse_expression(str(value))
        except ex.ExprError as exc:
            return Issue("error", f"Expression invalide : {exc}.")
    elif k in NUMERIC:
        try:
            n = to_number(q, value)
        except (TypeError, ValueError):
            return Issue("error", "Entier attendu." if k == "int" else "Nombre attendu.")
        if q.minimum is not None and n < q.minimum:
            return Issue("error" if strict_range else "warning", f"Valeur trop petite (minimum {_fmt(q.minimum)}{(' ' + q.unit) if q.unit else ''}).")
        if q.maximum is not None and n > q.maximum:
            return Issue("error" if strict_range else "warning", f"Valeur trop grande (maximum {_fmt(q.maximum)}{(' ' + q.unit) if q.unit else ''}).")
    elif k == "choice":
        if q.choices and str(value) not in q.choices:
            return Issue("error", f"Choix inconnu « {value} ». Choisissez parmi : {', '.join(c or '(vide)' for c in q.choices)}.")
    elif k == "var":
        if not IDENT.match(str(value).strip()):
            return Issue("error", "Nom invalide : lettres, chiffres et _ ; ne commence pas par un chiffre.")
    elif k == "json":
        try:
            json.loads(value if isinstance(value, str) else json.dumps(value))
        except ValueError as exc:
            return Issue("error", f"JSON invalide : {exc}.")
    elif k == "pairs":
        try:
            parse_pairs(value)
        except ValueError as exc:
            return Issue("error", str(exc))
    elif k == "code" and q.mode == "python":
        try:
            ast.parse(str(value))
        except SyntaxError as exc:
            return Issue("error", f"Erreur de syntaxe Python ligne {exc.lineno} : {exc.msg}.")
    elif k == "path":
        s = str(value).strip().replace("\\", "/")
        if not has_template(s) and (s.startswith("/") or re.match(r"^[A-Za-z]:/", s) or ".." in s.split("/")):
            return Issue("warning", "Le chemin doit rester dans le projet (relatif, sans « .. »).")
    return _special(type_, q, value)


def _fmt(x) -> str:
    return str(int(x)) if float(x) == int(x) else str(x)


def validate_params(type_: str, params: dict, *, strict_range: bool = False) -> dict[str, Issue]:
    """{nom du paramètre: Issue} pour un bloc ; absent = valide. Les paramètres manquants prennent la valeur par défaut."""
    b = blocks.REGISTRY.get(type_)
    out: dict[str, Issue] = {}
    for q in (b.params if b else []):
        issue = validate_param(type_, q, (params or {}).get(q.name, q.default), strict_range=strict_range)
        if issue:
            out[q.name] = issue
    return out


# ------------------------------------------------------------------------------------------------ valeurs
def get_value(node: dict, q: blocks.Param):
    return (node.get("params") or {}).get(q.name, q.default)


def is_default(node: dict, q: blocks.Param) -> bool:
    return get_value(node, q) == q.default


def reset_param(node: dict, q: blocks.Param) -> None:
    node.setdefault("params", {})[q.name] = copy.deepcopy(q.default)


def set_param(node: dict, name: str, value) -> None:
    node.setdefault("params", {})[name] = value


# ------------------------------------------------------------------------------------------------ résumés
def _short(value, n: int = 48) -> str:
    s = " ".join(str(value).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _display(q: blocks.Param, value) -> str:
    if q.kind == "choice":
        return str(value)
    if q.kind == "bool":
        return "oui" if value else "non"
    if q.kind == "pairs":
        try:
            n = len(parse_pairs(value))
        except ValueError:
            return "?"
        return f"{n} ligne(s)"
    if value is None or str(value).strip() == "":
        return "…"
    return _short(value)


def summary(node: dict) -> str:
    """Résumé lisible : « HTTP GET https://… ». Repli sur le titre du bloc ; ne lève jamais."""
    b = blocks.REGISTRY.get(node.get("type"))
    if not b:
        return "Bloc inconnu"
    params = node.get("params") or {}
    values = {q.name: _display(q, params.get(q.name, q.default)) for q in b.params}
    tpl = b.summary or b.title
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), tpl)


def describe(type_: str) -> str:
    """Aide d'un bloc : description + exemple + sorties."""
    b = blocks.REGISTRY.get(type_)
    if not b:
        return ""
    parts = [b.doc or b.title]
    if b.example:
        parts.append("Exemple : " + b.example)
    if b.outputs:
        parts.append("Sorties : " + ", ".join(f"out.<bloc>.{o}" for o in b.outputs))
    if b.ports and len(b.ports) > 1:
        parts.append("Ports : " + ", ".join(b.ports))
    return "\n".join(parts)


def search_blocks(query: str) -> list[blocks.Block]:
    """Recherche : d'abord dans titre, type et catégorie ; à défaut, dans la description, le résumé et l'exemple (tous les mots doivent correspondre)."""
    words = [w for w in query.lower().split() if w]
    head_hits, full_hits = [], []
    for b in blocks.REGISTRY.values():
        head = f"{b.title} {b.type} {b.category}".lower()
        full = f"{head} {b.doc} {b.summary} {b.example}".lower()
        if all(w in head for w in words):
            head_hits.append(b)
        elif all(w in full for w in words):
            full_hits.append(b)
    return sorted(head_hits or full_hits, key=lambda b: (b.category, b.title))


# ------------------------------------------------------------------------------------------------ graphe
def _incoming(wf: dict) -> dict[str, list[str]]:
    inc: dict[str, list[str]] = {}
    for e in wf.get("edges", []):
        inc.setdefault(e.get("dst"), []).append(e.get("src"))
    return inc


def upstream_ids(wf: dict, node_id: str) -> list[str]:
    inc, seen, stack = _incoming(wf), set(), list(_incoming(wf).get(node_id, []))
    order = []
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        order.append(n)
        stack += inc.get(n, [])
    return order


def known_vars(wf: dict, node_id: str | None = None) -> list[str]:
    """Variables connues : noms définis par les blocs « Définir une variable » en amont (ou dans tout le workflow si node_id est vide)."""
    nodes = {n["id"]: n for n in wf.get("nodes", [])}
    ids = upstream_ids(wf, node_id) if node_id else list(nodes)
    names: list[str] = []
    for i in sorted(ids):
        n = nodes.get(i)
        if n and n.get("type") == "set_var":
            v = str((n.get("params") or {}).get("name", "")).strip()
            if v and IDENT.match(v) and v not in names:
                names.append(v)
    return names


def upstream_outputs(wf: dict, node_id: str) -> list[str]:
    """Références `out.<bloc>.<champ>` disponibles pour ce bloc."""
    nodes = {n["id"]: n for n in wf.get("nodes", [])}
    refs = []
    for i in sorted(upstream_ids(wf, node_id)):
        b = blocks.REGISTRY.get((nodes.get(i) or {}).get("type"))
        refs += [f"out.{i}.{o}" for o in (b.outputs if b else ())]
    return refs


# ------------------------------------------------------------------------------------------------ rétro-compatibilité
def legacy_params(type_: str, params: dict) -> dict:
    """Traduit les anciens noms de paramètres vers le schéma actuel (copie) : write_file « append » -> « mode »."""
    p = dict(params or {})
    if type_ == "write_file" and "mode" not in p and "append" in p:
        p["mode"] = "a" if p.pop("append") else "w"
    return p


def upgrade_node(node: dict) -> dict:
    """Complète un bloc d'un ancien workflow : paramètres manquants -> valeurs par défaut, anciens formats -> format actuel. Modifie et renvoie `node`."""
    node.setdefault("params", {})
    node.setdefault("options", {})
    node.setdefault("x", 0)
    node.setdefault("y", 0)
    b = blocks.REGISTRY.get(node.get("type"))
    if not b:
        return node
    p = node["params"] = legacy_params(node["type"], node["params"])
    for q in b.params:
        if q.name not in p:
            p[q.name] = copy.deepcopy(q.default)
        elif q.kind == "pairs" and isinstance(p[q.name], dict):
            p[q.name] = dump_pairs(p[q.name].items())
        elif q.kind in NUMERIC and isinstance(p[q.name], str):
            try:
                p[q.name] = to_number(q, p[q.name])
            except ValueError:
                pass
    return node


def upgrade_workflow(wf: dict) -> dict:
    for n in wf.get("nodes", []):
        upgrade_node(n)
    wf.setdefault("edges", [])
    wf.setdefault("triggers", [{"kind": "manual"}])
    return wf


# ------------------------------------------------------------------------------------------------ copier / coller / dupliquer
CLIP_KEY = "voktora_forge_blocks"


def copy_nodes(wf: dict, ids) -> dict:
    ids = [i for i in ids]
    nodes = [copy.deepcopy(n) for n in wf.get("nodes", []) if n["id"] in ids and n.get("type") != "start"]
    keep = {n["id"] for n in nodes}
    edges = [copy.deepcopy(e) for e in wf.get("edges", []) if e["src"] in keep and e["dst"] in keep]
    return {CLIP_KEY: 1, "nodes": nodes, "edges": edges}


def new_id(wf: dict, type_: str, taken=()) -> str:
    used = {n["id"] for n in wf.get("nodes", [])} | set(taken)
    n = 1
    while f"{type_}{n}" in used:
        n += 1
    return f"{type_}{n}"


def paste_nodes(wf: dict, payload: dict, dx: float = 40, dy: float = 40) -> list[str]:
    """Insère les blocs copiés (nouveaux identifiants, liens internes conservés) et renvoie leurs identifiants."""
    if not isinstance(payload, dict) or payload.get(CLIP_KEY) != 1:
        return []
    mapping: dict[str, str] = {}
    created = []
    for n in payload.get("nodes", []):
        if n.get("type") not in blocks.REGISTRY or n["type"] == "start":
            continue
        nid = new_id(wf, n["type"], mapping.values())
        mapping[n["id"]] = nid
        c = copy.deepcopy(n)
        c.update(id=nid, x=round(float(n.get("x", 0)) + dx), y=round(float(n.get("y", 0)) + dy))
        upgrade_node(c)
        wf["nodes"].append(c)
        created.append(nid)
    for e in payload.get("edges", []):
        if e["src"] in mapping and e["dst"] in mapping:
            wf["edges"].append({"src": mapping[e["src"]], "port": e.get("port", "out"), "dst": mapping[e["dst"]]})
    return created


def duplicate_nodes(wf: dict, ids) -> list[str]:
    return paste_nodes(wf, copy_nodes(wf, ids))


def clip_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def clip_parse(text: str) -> dict | None:
    try:
        d = json.loads(text)
    except (TypeError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get(CLIP_KEY) == 1 else None


# ------------------------------------------------------------------------------------------------ réordonnancement
def linear_chain(wf: dict) -> list[str]:
    """Identifiants (hors démarrage) de la chaîne simple « out » : démarrage → a → b → c. Vide si le workflow n'est pas une chaîne linéaire."""
    nodes = {n["id"]: n for n in wf.get("nodes", [])}
    starts = [n["id"] for n in nodes.values() if n.get("type") == "start"]
    if len(starts) != 1:
        return []
    out: dict[str, list[dict]] = {}
    for e in wf.get("edges", []):
        out.setdefault(e["src"], []).append(e)
    chain, cur, seen = [], starts[0], {starts[0]}
    while True:
        es = out.get(cur, [])
        if len(es) != 1 or es[0].get("port", "out") != "out" or es[0]["dst"] in seen:
            if es:
                return []
            break
        cur = es[0]["dst"]
        seen.add(cur)
        chain.append(cur)
    return chain if len(seen) == len(nodes) else []


def reorder_chain(wf: dict, new_order: list[str]) -> bool:
    """Réorganise une chaîne linéaire (re-câble les liens). False si le workflow n'est pas linéaire ou si l'ordre ne contient pas exactement les mêmes blocs."""
    chain = linear_chain(wf)
    if not chain or sorted(chain) != sorted(new_order):
        return False
    start = next(n["id"] for n in wf["nodes"] if n.get("type") == "start")
    ids = [start, *new_order]
    wf["edges"] = [{"src": a, "port": "out", "dst": b} for a, b in zip(ids, ids[1:], strict=False)]
    return True


def move_pair(pairs: list, index: int, delta: int) -> list:
    j = index + delta
    if not (0 <= index < len(pairs) and 0 <= j < len(pairs)):
        return list(pairs)
    out = list(pairs)
    out[index], out[j] = out[j], out[index]
    return out


# ------------------------------------------------------------------------------------------------ annuler / rétablir
class History:
    """Pile d'états (instantanés JSON du workflow). `record` enregistre l'état courant ; les modifications successives d'un même champ (même clé) sont fusionnées."""

    def __init__(self, limit: int = 100):
        self.limit = limit
        self.states: list[str] = []
        self.keys: list[str | None] = []
        self.i = -1

    @staticmethod
    def snap(wf: dict) -> str:
        return json.dumps({k: wf.get(k) for k in ("name", "description", "nodes", "edges", "triggers", "enabled")}, sort_keys=True, default=str)

    def reset(self, wf: dict) -> None:
        self.states, self.keys, self.i = [self.snap(wf)], [None], 0

    def record(self, wf: dict, key: str | None = None) -> bool:
        s = self.snap(wf)
        if self.i >= 0 and self.states[self.i] == s:
            return False
        if key is not None and self.i > 0 and self.keys[self.i] == key and self.i == len(self.states) - 1:
            self.states[self.i] = s
            return True
        del self.states[self.i + 1:], self.keys[self.i + 1:]
        self.states.append(s)
        self.keys.append(key)
        if len(self.states) > self.limit:
            del self.states[0], self.keys[0]
        self.i = len(self.states) - 1
        return True

    @property
    def can_undo(self) -> bool:
        return self.i > 0

    @property
    def can_redo(self) -> bool:
        return 0 <= self.i < len(self.states) - 1

    def undo(self) -> dict | None:
        if not self.can_undo:
            return None
        self.i -= 1
        self.keys[self.i] = None
        return json.loads(self.states[self.i])

    def redo(self) -> dict | None:
        if not self.can_redo:
            return None
        self.i += 1
        return json.loads(self.states[self.i])


def restore(wf: dict, state: dict) -> None:
    """Remet `wf` (même objet) dans l'état d'un instantané."""
    for k, v in state.items():
        if v is None:
            wf.pop(k, None)
        else:
            wf[k] = v
