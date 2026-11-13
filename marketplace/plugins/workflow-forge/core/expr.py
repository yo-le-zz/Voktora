"""Évaluateur d'expressions SÛR : analyse syntaxique Python (ast) puis interprétation d'un sous-ensemble — jamais de eval/exec."""

from __future__ import annotations

import ast
import operator
import re

MAX_LEN = 2000
MAX_POW = 10_000
BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
       ast.Mod: operator.mod, ast.Pow: operator.pow}
CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
       ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b, ast.Is: operator.is_, ast.IsNot: operator.is_not}
FUNCS = {
    "len": len, "str": str, "int": int, "float": float, "bool": bool, "abs": abs, "min": min, "max": max, "sum": sum, "round": round,
    "sorted": sorted, "list": list, "range": lambda *a: list(range(*(min(abs(x), 100000) * (1 if x >= 0 else -1) for x in a))),
    "upper": lambda s: str(s).upper(), "lower": lambda s: str(s).lower(), "strip": lambda s: str(s).strip(),
    "contains": lambda a, b: b in a, "startswith": lambda s, p: str(s).startswith(p), "endswith": lambda s, p: str(s).endswith(p),
    "split": lambda s, sep=None: str(s).split(sep), "join": lambda sep, items: str(sep).join(map(str, items)),
    "replace": lambda s, a, b: str(s).replace(a, b), "regex_match": lambda p, s: re.search(p, str(s)) is not None,
    "keys": lambda d: list(d), "values": lambda d: list(d.values()), "get": lambda d, k, default=None: d.get(k, default) if isinstance(d, dict) else default,
    "default": lambda v, d: d if v in (None, "") else v,
}


class ExprError(ValueError):
    pass


class _Env(dict):
    pass


def parse_expression(source: str):
    """Analyse une EXPRESSION unique (entre parenthèses : aucune instruction possible). Lève ExprError."""
    if len(source) > MAX_LEN:
        raise ExprError("Expression trop longue.")
    try:
        tree = ast.parse("(" + source.strip() + "\n)")
    except SyntaxError as exc:
        raise ExprError(f"Syntaxe invalide : {exc.msg}") from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Expr):
        raise ExprError("Une seule expression est attendue.")
    return tree.body[0].value


def evaluate(source: str, names: dict | None = None):
    return _ev(parse_expression(source), names or {})


def _ev(n, env):  # noqa: C901 — un cas par type de nœud autorisé
    if isinstance(n, ast.Constant):
        if isinstance(n.value, (str, int, float, bool)) or n.value is None:
            return n.value
        raise ExprError("Constante non autorisée.")
    if isinstance(n, ast.Name):
        if n.id in ("true", "True"):
            return True
        if n.id in ("false", "False"):
            return False
        if n.id in ("null", "None"):
            return None
        if n.id in env:
            return env[n.id]
        raise ExprError(f"Variable inconnue : {n.id}")
    if isinstance(n, ast.BoolOp):
        vals = iter(n.values)
        cur = _ev(next(vals), env)
        for v in vals:
            if isinstance(n.op, ast.And):
                if not cur:
                    return cur
            elif cur:
                return cur
            cur = _ev(v, env)
        return cur
    if isinstance(n, ast.UnaryOp):
        v = _ev(n.operand, env)
        if isinstance(n.op, ast.Not):
            return not v
        if isinstance(n.op, ast.USub):
            return -v
        if isinstance(n.op, ast.UAdd):
            return +v
        raise ExprError("Opérateur non autorisé.")
    if isinstance(n, ast.BinOp):
        op = BIN.get(type(n.op))
        if not op:
            raise ExprError("Opérateur non autorisé.")
        a, b = _ev(n.left, env), _ev(n.right, env)
        if isinstance(n.op, ast.Pow) and (abs(b) > 64 or abs(a) > MAX_POW):
            raise ExprError("Puissance trop grande.")
        if isinstance(n.op, ast.Mult) and isinstance(a, (str, list)) and isinstance(b, int) and len(a) * max(b, 0) > 100000:
            raise ExprError("Résultat trop grand.")
        try:
            return op(a, b)
        except (TypeError, ZeroDivisionError, ValueError) as exc:
            raise ExprError(f"Calcul impossible : {exc}") from exc
    if isinstance(n, ast.Compare):
        left = _ev(n.left, env)
        for op, comp in zip(n.ops, n.comparators, strict=True):
            right = _ev(comp, env)
            f = CMP.get(type(op))
            if not f:
                raise ExprError("Comparaison non autorisée.")
            try:
                if not f(left, right):
                    return False
            except TypeError as exc:
                raise ExprError(f"Comparaison impossible : {exc}") from exc
            left = right
        return True
    if isinstance(n, ast.IfExp):
        return _ev(n.body, env) if _ev(n.test, env) else _ev(n.orelse, env)
    if isinstance(n, ast.Attribute):
        base = _ev(n.value, env)
        if n.attr.startswith("_"):
            raise ExprError("Accès interdit.")
        if isinstance(base, dict) and n.attr in base:
            return base[n.attr]
        raise ExprError(f"Champ introuvable : {n.attr}")
    if isinstance(n, ast.Subscript):
        base, key = _ev(n.value, env), _ev(n.slice, env)
        try:
            return base[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExprError(f"Élément introuvable : {key!r}") from exc
    if isinstance(n, (ast.List, ast.Tuple)):
        return [_ev(x, env) for x in n.elts]
    if isinstance(n, ast.Dict):
        return {_ev(k, env): _ev(v, env) for k, v in zip(n.keys, n.values, strict=True) if k is not None}
    if isinstance(n, ast.Call):
        if not isinstance(n.func, ast.Name) or n.func.id not in FUNCS or n.keywords:
            raise ExprError("Appel de fonction non autorisé.")
        try:
            return FUNCS[n.func.id](*[_ev(a, env) for a in n.args])
        except (TypeError, ValueError, AttributeError) as exc:
            raise ExprError(f"{n.func.id}() : {exc}") from exc
    raise ExprError(f"Construction non autorisée : {type(n).__name__}")


TEMPLATE = re.compile(r"\{\{((?:(?!\}\}).)+)\}\}", re.S)


def render(text: str, names: dict):
    """Remplace `{{expr}}` par son résultat. Si le texte est exactement une expression, retourne la valeur non convertie."""
    m = TEMPLATE.fullmatch(text.strip()) if isinstance(text, str) else None
    if m:
        return evaluate(m.group(1), names)
    return TEMPLATE.sub(lambda mm: str(evaluate(mm.group(1), names)), text) if isinstance(text, str) else text
