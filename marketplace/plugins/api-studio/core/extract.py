"""Chaînage de réponses : extraction (JSON « $.a.b[0].c », en-tête, regex, statut) et assertions de tests."""

from __future__ import annotations

import json
import re

TOKEN = re.compile(r"\.([A-Za-z0-9_\-]+)|\[(\d+)\]|\['([^']+)'\]|\[\"([^\"]+)\"\]")


def json_path(data, expr: str):
    """Sous-ensemble de JSONPath : `$`, `.clé`, `[n]`, `['clé']`. Lève KeyError si absent."""
    if not expr.startswith("$"):
        raise KeyError(f"Chemin invalide (doit commencer par $) : {expr}")
    pos, cur = 1, data
    while pos < len(expr):
        m = TOKEN.match(expr, pos)
        if not m:
            raise KeyError(f"Chemin invalide près de : {expr[pos:]}")
        key, idx, k1, k2 = m.groups()
        try:
            cur = cur[int(idx)] if idx is not None else cur[key or k1 or k2]
        except (KeyError, IndexError, TypeError) as exc:
            raise KeyError(f"Introuvable : {expr}") from exc
        pos = m.end()
    return cur


def value_from(resp, source: str, expr: str):
    if source == "json":
        return json_path(resp.json(), expr)
    if source == "header":
        v = resp.header(expr)
        if not v:
            raise KeyError(f"En-tête absent : {expr}")
        return v
    if source == "regex":
        m = re.search(expr, resp.text)
        if not m:
            raise KeyError(f"Motif introuvable : {expr}")
        return m.group(1) if m.groups() else m.group(0)
    if source == "status":
        return resp.status
    raise KeyError(f"Source inconnue : {source}")


def run_extract(resp, rules: list[dict]) -> tuple[dict, list[str]]:
    got, errors = {}, []
    for r in rules:
        try:
            v = value_from(resp, r["source"], r.get("expr", ""))
            got[r["var"]] = v if isinstance(v, str) else json.dumps(v) if isinstance(v, (dict, list)) else str(v)
        except (KeyError, ValueError, re.error) as exc:
            errors.append(f"{r.get('var', '?')} : {exc}")
    return got, errors


OPS = {"==": lambda a, b: str(a) == str(b), "!=": lambda a, b: str(a) != str(b), "contains": lambda a, b: str(b) in str(a),
       "matches": lambda a, b: re.search(str(b), str(a)) is not None, "<": lambda a, b: float(a) < float(b), ">": lambda a, b: float(a) > float(b),
       "<=": lambda a, b: float(a) <= float(b), ">=": lambda a, b: float(a) >= float(b), "exists": lambda a, b: True}


def _actual(resp, kind: str, expr: str):
    if kind == "status":
        return resp.status
    if kind == "time":
        return resp.seconds * 1000
    if kind == "body":
        return resp.text
    if kind == "header":
        return value_from(resp, "header", expr)
    if kind == "json":
        return json_path(resp.json(), expr)
    raise KeyError(f"Type de test inconnu : {kind}")


def run_tests(resp, tests: list[dict]) -> list[dict]:
    """Chaque test : {"kind": status|header|json|body|time, "expr", "op", "value"} → {"ok","name","detail"}."""
    out = []
    for t in tests:
        kind, expr, op, expected = t.get("kind", "status"), t.get("expr", ""), t.get("op", "=="), t.get("value", "")
        name = f"{kind}{(' ' + expr) if expr else ''} {op} {expected}".strip()
        try:
            actual = _actual(resp, kind, expr)
            ok = OPS[op](actual, expected)
            out.append({"ok": bool(ok), "name": name, "detail": f"obtenu : {str(actual)[:120]}"})
        except (KeyError, ValueError) as exc:
            out.append({"ok": False, "name": name, "detail": str(exc)})
    return out
