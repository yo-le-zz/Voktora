"""Analyseur Python (module `ast`) : symboles, signatures, imports, appels bruts, décorateurs, qualité."""

from __future__ import annotations

import ast
import re

from ..core import textutil
from ..core.data import names
from ..core.model import CLASS, FUNCTION, METHOD, MODULE, FileResult, Issue, RawRef, Symbol, sym_id
from .base import Analyzer, register

BRANCHES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Assert, ast.comprehension)
SECRET = re.compile(r"""(?i)(password|passwd|secret|api[_-]?key|token)\s*=\s*['"][^'"\s]{8,}['"]""")
DYNAMIC = set(names()["dynamic"])


def dotted(node: ast.AST) -> str | None:
    """`a.b.c` → « a.b.c » ; renvoie None si la chaîne contient un appel/indice (récepteur non statique)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def tail_attr(node: ast.AST) -> str | None:
    return node.attr if isinstance(node, ast.Attribute) else None


def complexity(node: ast.AST) -> int:
    score = 1
    for n in ast.walk(node):
        if isinstance(n, BRANCHES):
            score += 1
        elif isinstance(n, ast.BoolOp):
            score += len(n.values) - 1
        elif isinstance(n, ast.match_case):
            score += 1
    return score


def params_of(args: ast.arguments) -> list[dict]:
    out = []
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for a, d in zip(positional, defaults, strict=True):
        out.append({"name": a.arg, "annotation": ast.unparse(a.annotation) if a.annotation else "",
                    "default": ast.unparse(d) if d is not None else "", "kind": "positional"})
    if args.vararg:
        out.append({"name": args.vararg.arg, "annotation": ast.unparse(args.vararg.annotation) if args.vararg.annotation else "",
                    "default": "", "kind": "*args"})
    for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        out.append({"name": a.arg, "annotation": ast.unparse(a.annotation) if a.annotation else "",
                    "default": ast.unparse(d) if d is not None else "", "kind": "keyword"})
    if args.kwarg:
        out.append({"name": args.kwarg.arg, "annotation": ast.unparse(args.kwarg.annotation) if args.kwarg.annotation else "",
                    "default": "", "kind": "**kwargs"})
    return out


def signature(name: str, params: list[dict], returns: str, is_async: bool) -> str:
    parts = []
    for p in params:
        text = {"*args": "*", "**kwargs": "**"}.get(p["kind"], "") + p["name"]
        if p["annotation"]:
            text += f": {p['annotation']}"
        if p["default"]:
            text += f" = {p['default']}"
        parts.append(text)
    return f"{'async ' if is_async else ''}def {name}({', '.join(parts)})" + (f" -> {returns}" if returns else "")


class _Collector(ast.NodeVisitor):
    """Parcourt un module : symboles + références brutes, avec la pile de portées."""

    def __init__(self, path: str, result: FileResult, source_lines: list[str]) -> None:
        self.path, self.result, self.lines = path, result, source_lines
        self.scope: list[tuple[str, str]] = []       # (kind, nom)
        self.module_id = sym_id(path, "<module>")
        self.current_class_attrs: dict | None = None
        self.local_types: dict[str, str] | None = None
        self.assigned: dict[str, int] | None = None
        self.used_names: set[str] = set()
        self.imported: dict[str, int] = {}           # nom lié → ligne (pour « import inutilisé »)
        self.all_names: set[str] = set()
        self._assign_target: dict[int, str] = {}

    # -- identifiants ------------------------------------------------------------
    def qual(self, name: str) -> str:
        return ".".join([n for _, n in self.scope] + [name])

    def owner(self) -> str:
        for kind, _ in reversed(self.scope):
            if kind in ("function", "method"):
                return sym_id(self.path, ".".join(n for _, n in self.scope))
        return self.module_id if not self.scope else sym_id(self.path, ".".join(n for _, n in self.scope)) \
            if self.scope[-1][0] == "class" else self.module_id

    def add_issue(self, node, sev, code, title, explain, hint, symbol="") -> None:
        self.result.issues.append(Issue(self.path, getattr(node, "lineno", 0), sev, code, title, explain, hint, symbol))

    # -- définitions -------------------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qn = self.qual(node.name)
        sid = sym_id(self.path, qn)
        parent = sym_id(self.path, ".".join(n for _, n in self.scope)) if self.scope else self.module_id
        decorators = [ast.unparse(d) for d in node.decorator_list]
        sym = Symbol(sid, CLASS, node.name, self.path, node.lineno, node.end_lineno or node.lineno, "python", parent,
                     f"class {node.name}({', '.join(ast.unparse(b) for b in node.bases)})", [], "", decorators,
                     (ast.get_docstring(node) or "").split("\n")[0], complexity(node), {"attr_types": {}})
        self.result.symbols.append(sym)
        for base in node.bases:
            expr = dotted(base) or (dotted(base.value) if isinstance(base, ast.Subscript) else None)
            if expr:
                self.result.refs.append(RawRef(sid, expr, "inherits", node.lineno))
        for deco in node.decorator_list:
            self._decorator(deco, sid)
        previous = self.current_class_attrs
        self.current_class_attrs = sym.meta["attr_types"]
        self.scope.append(("class", node.name))
        for child in node.body:
            self.visit(child)
        self.scope.pop()
        self.current_class_attrs = previous

    def _decorator(self, deco: ast.AST, target: str) -> None:
        call = deco.func if isinstance(deco, ast.Call) else deco
        expr = dotted(call)
        if expr:
            self.result.refs.append(RawRef(target, expr, "decorates", getattr(deco, "lineno", 0)))
        if isinstance(deco, ast.Call):
            for arg in [*deco.args, *[k.value for k in deco.keywords]]:
                self.visit(arg)

    def _function(self, node) -> None:
        in_class = bool(self.scope) and self.scope[-1][0] == "class"
        qn = self.qual(node.name)
        sid = sym_id(self.path, qn)
        parent = sym_id(self.path, ".".join(n for _, n in self.scope)) if self.scope else self.module_id
        params = params_of(node.args)
        returns = ast.unparse(node.returns) if node.returns else ""
        is_async = isinstance(node, ast.AsyncFunctionDef)
        decorators = [ast.unparse(d) for d in node.decorator_list]
        cx = complexity(node)
        sym = Symbol(sid, METHOD if in_class else FUNCTION, node.name, self.path, node.lineno, node.end_lineno or node.lineno,
                     "python", parent, signature(node.name, params, returns, is_async), params, returns, decorators,
                     (ast.get_docstring(node) or "").split("\n")[0], cx,
                     {"async": is_async, "static": any(d.endswith("staticmethod") for d in decorators),
                      "classmethod": any(d.endswith("classmethod") for d in decorators),
                      "property": any(d in ("property",) or d.endswith(".setter") for d in decorators),
                      "local_types": {}})
        self.result.symbols.append(sym)
        for deco in node.decorator_list:
            self._decorator(deco, sid)
        for default in [*node.args.defaults, *[d for d in node.args.kw_defaults if d is not None]]:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                    isinstance(default, ast.Call) and dotted(default.func) in ("list", "dict", "set")):
                self.add_issue(node, "warn", "PY-MUTABLE-DEFAULT", f"Valeur par défaut mutable dans {node.name}()",
                               "Un argument par défaut mutable est créé UNE fois et partagé entre tous les appels.",
                               "Utilisez None puis créez la valeur dans la fonction.", sid)
        length = (node.end_lineno or node.lineno) - node.lineno + 1
        if cx > 25:
            self.add_issue(node, "error", "COMPLEXITY", f"{node.name}() est très complexe (complexité {cx})",
                           "Beaucoup de chemins d'exécution : difficile à comprendre et à tester.",
                           "Découpez en fonctions plus petites (une responsabilité chacune).", sid)
        elif cx > 15:
            self.add_issue(node, "warn", "COMPLEXITY", f"{node.name}() est complexe (complexité {cx})",
                           "Trop de branches pour être lisible d'un coup d'œil.", "Extrayez des sous-fonctions.", sid)
        if length > 120:
            self.add_issue(node, "warn", "LONG-FUNCTION", f"{node.name}() fait {length} lignes",
                           "Les très longues fonctions cachent plusieurs responsabilités.", "Découpez-la.", sid)
        if len([p for p in params if p["name"] not in ("self", "cls")]) > 7:
            self.add_issue(node, "info", "MANY-PARAMS", f"{node.name}() prend beaucoup de paramètres",
                           "Plus de 7 paramètres rendent les appels fragiles.", "Regroupez-les dans un objet (dataclass).", sid)
        previous_types, previous_assigned = self.local_types, self.assigned
        self.local_types, self.assigned = sym.meta["local_types"], {}
        self.scope.append(("method" if in_class else "function", node.name))
        self._unreachable(node.body, sid)
        for child in node.body:
            self.visit(child)
        self.scope.pop()
        for var, count in self.assigned.items():              # une variable réassignée n'a plus de type fiable
            if count > 1:
                self.local_types.pop(var, None)
        self.local_types, self.assigned = previous_types, previous_assigned

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def _unreachable(self, body: list, sid: str) -> None:
        for a, b in zip(body, body[1:], strict=False):
            if isinstance(a, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
                self.add_issue(b, "warn", "UNREACHABLE", "Code inaccessible",
                               "Cette instruction suit un return/raise/break/continue et ne s'exécutera jamais.",
                               "Supprimez-la ou corrigez la logique.", sid)
                return

    # -- imports -----------------------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.result.imports.append({"module": alias.name, "names": [], "alias": alias.asname or "", "level": 0,
                                        "line": node.lineno})
            self.imported[(alias.asname or alias.name).split(".")[0]] = node.lineno

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        names = [[a.name, a.asname or ""] for a in node.names]
        self.result.imports.append({"module": node.module or "", "names": names, "alias": "", "level": node.level,
                                    "line": node.lineno})
        for a in node.names:
            if a.name == "*":
                self.add_issue(node, "info", "WILDCARD-IMPORT", f"import * depuis {node.module}",
                               "Les imports « * » masquent l'origine des noms et polluent l'espace de noms.",
                               "Importez explicitement les noms utilisés.")
            else:
                self.imported[a.asname or a.name] = node.lineno

    # -- appels ------------------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        owner = self.owner()
        func = node.func
        expr = dotted(func)
        if expr and node.args:
            first = node.args[0]
            last = expr.split(".")[-1]
            if last in ("CDLL", "PyDLL", "WinDLL", "LoadLibrary", "dlopen") and isinstance(first, ast.Constant) \
                    and isinstance(first.value, str):
                self.result.info.setdefault("native_loads", []).append({"line": node.lineno, "lib": first.value, "owner": owner,
                                                                          "var": self._assign_target.get(id(node), "")})
            if expr in ("subprocess.run", "subprocess.Popen", "subprocess.check_output", "subprocess.check_call",
                        "subprocess.call", "Popen", "run") and isinstance(first, (ast.List, ast.Tuple)) and first.elts \
                    and isinstance(first.elts[0], ast.Constant) and isinstance(first.elts[0].value, str):
                self.result.info.setdefault("subprocess_cmds", []).append({"line": node.lineno, "cmd": first.elts[0].value,
                                                                           "owner": owner})
        if expr:
            self.result.refs.append(RawRef(owner, expr, "call", node.lineno))
            root = expr.split(".")[0]
            if root in DYNAMIC and "." not in expr:
                self.result.refs.append(RawRef(owner, expr, "dynamic", node.lineno, {"dynamic": expr}))
            if expr in names()["eval_like"]:
                self.add_issue(node, "error", "EVAL", f"Appel de {expr}()",
                               "Exécuter du texte comme du code est dangereux si la donnée peut être contrôlée par un tiers.",
                               "Utilisez ast.literal_eval, json, ou une table de fonctions.", owner)
            if expr.endswith("importlib.import_module") or expr == "import_module":
                self.result.refs.append(RawRef(owner, expr, "dynamic", node.lineno, {"dynamic": "import dynamique"}))
        elif isinstance(func, ast.Attribute):
            inner = func.value
            if isinstance(inner, ast.Call) and dotted(inner.func):                 # Foo().méthode()
                self.result.refs.append(RawRef(owner, dotted(inner.func) + "()." + func.attr, "call", node.lineno,
                                               {"chain": True}))
            else:
                self.result.refs.append(RawRef(owner, "?." + func.attr, "call", node.lineno, {"receiver": "unknown"}))
        elif isinstance(func, ast.Call) and dotted(func.func) in DYNAMIC:           # getattr(x, "a")()
            self.result.refs.append(RawRef(owner, "<dynamique>", "dynamic", node.lineno, {"dynamic": "appel indirect"}))
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                self.add_issue(node, "error", "SHELL-TRUE", "subprocess avec shell=True",
                               "Un texte interprété par le shell permet l'injection de commandes.",
                               "Passez une liste d'arguments et shell=False.", owner)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(dotted(node).split(".")[0] if dotted(node) else "")
            expr = dotted(node)
            if expr:                                   # référence sans appel (callback possible) : résolue seulement si fonction
                self.result.refs.append(RawRef(self.owner(), expr, "ref", node.lineno))
        self.generic_visit(node)

    # -- affectations (types locaux simples) ---------------------------------------
    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._assign_target[id(node.value)] = target.id
                elif isinstance(target, ast.Attribute):
                    self._assign_target[id(node.value)] = target.attr
        call = node.value.func if isinstance(node.value, ast.Call) else None
        ctor = dotted(call) if call is not None else None
        for target in node.targets:
            if isinstance(target, ast.Name):
                if self.assigned is not None:
                    self.assigned[target.id] = self.assigned.get(target.id, 0) + 1
                    if ctor and self.local_types is not None:
                        self.local_types[target.id] = ctor
                if target.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                    self.all_names |= {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
            elif (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self"
                  and ctor and self.current_class_attrs is not None):
                self.current_class_attrs[target.attr] = ctor
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        owner = self.owner()
        if node.type is None:
            self.add_issue(node, "warn", "BARE-EXCEPT", "except: sans type",
                           "Attrape aussi KeyboardInterrupt/SystemExit et masque les vraies erreurs.",
                           "Attrapez une exception précise (ou Exception).", owner)
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            self.add_issue(node, "warn", "SWALLOWED", "Exception ignorée silencieusement",
                           "Un `except …: pass` cache les erreurs et rend le débogage très difficile.",
                           "Journalisez l'erreur ou traitez-la.", owner)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        for op, right in zip(node.ops, node.comparators, strict=True):
            if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(right, ast.Constant) and right.value is None:
                self.add_issue(node, "info", "EQ-NONE", "Comparaison à None avec ==",
                               "`== None` peut être surchargé ; l'identité est la comparaison correcte.", "Utilisez `is None`.")
            if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(right, ast.Constant) and isinstance(right.value, (str, int)) \
                    and not isinstance(right.value, bool):
                self.add_issue(node, "warn", "IS-LITERAL", "`is` comparé à un littéral",
                               "`is` teste l'identité d'objet, pas l'égalité : résultat dépendant de l'implémentation.",
                               "Utilisez == / !=.")
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        if isinstance(node.test, ast.Tuple) and node.test.elts:
            self.add_issue(node, "error", "ASSERT-TUPLE", "assert sur un tuple",
                           "Un tuple non vide est toujours vrai : l'assertion ne vérifie rien.", "Retirez les parenthèses.")
        self.generic_visit(node)


def analyze_python(path: str, text: str) -> FileResult:
    lines = text.splitlines()
    result = FileResult(path, "python", loc=len([ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]))
    module = Symbol(sym_id(path, "<module>"), MODULE, path.rsplit("/", 1)[-1].removesuffix(".py"), path, 1, len(lines), "python",
                    "", "", [], "", [], "", 0)
    result.symbols.append(module)
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        result.issues.append(Issue(path, exc.lineno or 1, "error", "SYNTAX", "Erreur de syntaxe : " + (exc.msg or ""),
                                   "Ce fichier ne peut pas être analysé ni importé.", "Corrigez la syntaxe."))
        return result
    module.doc = (ast.get_docstring(tree) or "").split("\n")[0]
    collector = _Collector(path, result, lines)
    collector.visit(tree)
    for node in tree.body:                                   # points d'entrée : if __name__ == "__main__"
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) \
                and node.test.left.id == "__name__":
            result.info["entry"] = "main-guard"
            result.info["main_line"] = node.lineno
    if path.endswith("__main__.py"):
        result.info["entry"] = "__main__"
    # imports inutilisés (hors __init__.py : souvent des ré-exports)
    if not path.endswith("__init__.py"):
        in_strings = " ".join(re.findall(r"""['"]([\w.]+)['"]""", text))
        for name, line in collector.imported.items():
            if name not in collector.used_names and name not in collector.all_names and name not in in_strings.split() \
                    and name != "annotations":
                result.issues.append(Issue(path, line, "info", "UNUSED-IMPORT", f"Import inutilisé : {name}",
                                           "Ce nom est importé mais jamais utilisé dans le fichier.", "Supprimez l'import."))
    for m in SECRET.finditer(text):
        result.issues.append(Issue(path, text.count("\n", 0, m.start()) + 1, "error", "SECRET", "Secret possible en clair",
                                   "Une valeur ressemblant à un mot de passe ou à une clé est écrite dans le code.",
                                   "Déplacez-la dans une variable d'environnement ou un coffre."))
    for i, ln in enumerate(lines, 1):
        if re.search(r"#\s*(TODO|FIXME|XXX|HACK)\b", ln):
            result.info.setdefault("todos", []).append(i)
    result.blocks = textutil.duplicate_blocks(lines)
    return result


class PythonAnalyzer(Analyzer):
    lang = "python"
    extensions = (".py", ".pyi")

    def analyze_file(self, path: str, text: str) -> FileResult:
        return analyze_python(path, text)


register(PythonAnalyzer())
