"""Analyseur JavaScript / TypeScript : imports (ES, require, import()), exports, fonctions, flèches, classes, appels."""

from __future__ import annotations

import re

from ..core import textutil
from ..core.model import CLASS, FUNCTION, METHOD, MODULE, TRAIT, FileResult, Issue, RawRef, Symbol, sym_id
from .base import Analyzer, register

IMPORT_FROM = re.compile(r"""\bimport\s+(?:type\s+)?(?P<what>[^'";]*?)\s*from\s*['"](?P<mod>[^'"]+)['"]""")
IMPORT_BARE = re.compile(r"""\bimport\s*['"](?P<mod>[^'"]+)['"]""")
EXPORT_FROM = re.compile(r"""\bexport\s+(?P<what>\*(?:\s+as\s+\w+)?|\{[^}]*\})\s*from\s*['"](?P<mod>[^'"]+)['"]""")
REQUIRE = re.compile(r"""(?:(?:const|let|var)\s+(?P<bind>\{[^}]*\}|\w+)\s*=\s*)?require\(\s*['"](?P<mod>[^'"]+)['"]\s*\)""")
DYN_IMPORT = re.compile(r"""\bimport\(\s*['"](?P<mod>[^'"]+)['"]\s*\)""")
FUNC = re.compile(r"(?P<exp>\bexport\s+(?:default\s+)?)?(?P<async>async\s+)?function\s*\*?\s*(?P<name>[A-Za-z_$][\w$]*)\s*(?:<[^>(]*>)?\s*\(")
ARROW = re.compile(r"(?P<exp>\bexport\s+)?\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?P<async>async\s+)?"
                   r"(?:function\s*\*?\s*[\w$]*\s*\(|\(|[A-Za-z_$][\w$]*\s*=>)")
CLASS_RE = re.compile(r"(?P<exp>\bexport\s+(?:default\s+)?)?(?:abstract\s+)?\bclass\s+(?P<name>[A-Za-z_$][\w$]*)"
                      r"(?:\s*<[^>{]*>)?(?:\s+extends\s+(?P<base>[\w$.]+))?(?:\s+implements\s+(?P<impl>[^{]+))?\s*\{")
IFACE = re.compile(r"(?P<exp>\bexport\s+)?\binterface\s+(?P<name>[A-Za-z_$][\w$]*)(?:\s*<[^>{]*>)?(?:\s+extends\s+(?P<base>[^{]+))?\s*\{")
METHOD_RE = re.compile(r"(?<![\w$.])(?:(?:public|private|protected|static|async|readonly|override|get|set)\s+)*(?P<name>#?[A-Za-z_$][\w$]*)"
                       r"\s*(?:<[^>(]*>)?\s*\((?P<params>[^)]*)\)\s*(?::\s*[^{;=]+)?\s*\{")
CALL = re.compile(r"(?<![\w$.])(?:new\s+)?((?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*)\s*(?:<[^>()]*>)?\s*\(")
CALL_CHAIN = re.compile(r"\)\s*\.\s*([A-Za-z_$][\w$]*)\s*\(")
KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "typeof", "await", "super", "import", "require",
            "async", "else", "do", "void", "delete", "yield", "constructor"}


def complexity(body: str) -> int:
    return 1 + len(re.findall(r"\b(?:if|for|while|case|catch)\b", body)) + body.count("&&") + body.count("||") + body.count("?") \
        - body.count("?.") - body.count("??")


def split_params(text: str) -> list[dict]:
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text + ","):
        if ch in "({[<":
            depth += 1
        elif ch in ")}]>":
            depth -= 1
        elif ch == "," and depth == 0:
            part = text[start:i].strip()
            start = i + 1
            if part:
                name, _, default = part.partition("=")
                name, _, ann = name.partition(":")
                out.append({"name": name.strip().rstrip("?"), "annotation": ann.strip(), "default": default.strip(),
                            "kind": "rest" if name.strip().startswith("...") else "positional"})
    return out


def analyze_js(path: str, text: str, lang: str = "javascript") -> FileResult:
    code = textutil.mask_c_like(text, templates=True)                       # chaînes vidées : accolades sûres
    keep = textutil.mask_c_like(text, templates=True, keep_strings=True)    # chaînes conservées : chemins d'import
    starts = textutil.line_starts(text)
    line = lambda i: textutil.line_at(starts, i)  # noqa: E731
    lines = text.splitlines()
    result = FileResult(path, lang, loc=len([ln for ln in lines if ln.strip() and not ln.strip().startswith("//")]))
    module_id = sym_id(path, "<module>")
    result.symbols.append(Symbol(module_id, MODULE, path.rsplit("/", 1)[-1], path, 1, len(lines), lang))
    for m in IMPORT_FROM.finditer(keep):
        what, names, alias = m.group("what").strip(), [], ""
        for part in re.findall(r"\{([^}]*)\}", what):
            for item in part.split(","):
                item = item.strip().removeprefix("type ").strip()
                if item:
                    n, _, a = item.partition(" as ")
                    names.append([n.strip(), a.strip()])
        ns = re.search(r"\*\s+as\s+([\w$]+)", what)
        if ns:
            alias = ns.group(1)
        default = re.match(r"([A-Za-z_$][\w$]*)", what)
        if default and not what.startswith(("{", "*")):
            names.append(["default", default.group(1)])
        result.imports.append({"module": m.group("mod"), "names": names, "alias": alias, "level": 0, "line": line(m.start()), "js": True})
    for m in IMPORT_BARE.finditer(keep):
        result.imports.append({"module": m.group("mod"), "names": [], "alias": "", "level": 0, "line": line(m.start()), "js": True})
    for m in EXPORT_FROM.finditer(keep):
        names = [[n.strip().partition(" as ")[0], ""] for n in re.findall(r"[\w$]+(?:\s+as\s+[\w$]+)?", m.group("what"))
                 if n.strip() not in ("as",)]
        result.imports.append({"module": m.group("mod"), "names": names, "alias": "", "level": 0, "line": line(m.start()),
                               "js": True, "reexport": True})
    for m in REQUIRE.finditer(keep):
        bind, names, alias = m.group("bind") or "", [], ""
        if bind.startswith("{"):
            for item in bind.strip("{}").split(","):
                n, _, a = item.strip().partition(":")
                if n.strip():
                    names.append([n.strip(), a.strip()])
        elif bind:
            alias = bind
        result.imports.append({"module": m.group("mod"), "names": names, "alias": alias, "level": 0, "line": line(m.start()),
                               "js": True, "require": True})
    for m in DYN_IMPORT.finditer(keep):
        result.imports.append({"module": m.group("mod"), "names": [], "alias": "", "level": 0, "line": line(m.start()),
                               "js": True, "dynamic": True})
    bodies: list[tuple[Symbol, int, int]] = []

    def add_function(name, start_idx, open_paren, parent, qual_prefix, kind, exported, is_async):
        close_paren = textutil.match_brace(code, open_paren, "(", ")")
        if close_paren < 0:
            return None
        params_txt = code[open_paren + 1:close_paren]
        brace = re.compile(r"=>\s*\{|\{").search(code, close_paren, close_paren + 400)
        arrow_expr = re.compile(r"=>\s*[^{\s]").match(code, close_paren + 1) or re.compile(r"\)\s*(?::[^={;]+)?=>\s*[^{\s]").match(code, close_paren)
        sid = sym_id(path, f"{qual_prefix}{name}")
        sym = Symbol(sid, kind, name, path, line(start_idx), line(close_paren), lang, parent,
                     f"{'async ' if is_async else ''}function {name}({re.sub(r'\s+', ' ', params_txt).strip()})",
                     split_params(params_txt), "", [], "", 1, {"exported": exported, "async": bool(is_async)})
        result.symbols.append(sym)
        if brace and (not arrow_expr or brace.start() < (arrow_expr.start() if arrow_expr else 10**9)):
            open_b = code.find("{", brace.start())
            close_b = textutil.match_brace(code, open_b)
            if close_b > 0:
                sym.end_line = line(close_b)
                sym.complexity = complexity(code[open_b:close_b])
                bodies.append((sym, open_b, close_b))
                return close_b
        elif arrow_expr:                                    # flèche sans accolades : corps = jusqu'à la fin de l'instruction
            end = code.find("\n", close_paren)
            end = len(code) if end < 0 else end
            bodies.append((sym, close_paren, end))
            return end
        return close_paren

    taken: list[tuple[int, int]] = []
    for m in CLASS_RE.finditer(code):
        open_b = m.end() - 1
        close_b = textutil.match_brace(code, open_b)
        if close_b < 0:
            continue
        cid = sym_id(path, m.group("name"))
        csym = Symbol(cid, CLASS, m.group("name"), path, line(m.start()), line(close_b), lang, module_id,
                      f"class {m.group('name')}" + (f" extends {m.group('base')}" if m.group("base") else ""),
                      meta={"exported": bool(m.group("exp"))})
        result.symbols.append(csym)
        if m.group("base"):
            result.refs.append(RawRef(cid, m.group("base"), "inherits", line(m.start())))
        for iface in re.split(r",", m.group("impl") or ""):
            if iface.strip():
                result.refs.append(RawRef(cid, re.sub(r"<.*", "", iface).strip(), "implements", line(m.start())))
        inner_taken: list[tuple[int, int]] = []
        for mm in METHOD_RE.finditer(code, open_b + 1, close_b):
            if mm.group("name") in KEYWORDS - {"constructor"} or any(a <= mm.start() < b for a, b in inner_taken):
                continue
            end = add_function(mm.group("name"), mm.start("name"), code.find("(", mm.start("name")), cid, m.group("name") + ".",
                               METHOD, False, "async" in mm.group(0).split(mm.group("name"))[0])
            if end:
                inner_taken.append((mm.start(), end))
        taken.append((open_b, close_b))
    for m in IFACE.finditer(code):
        close_b = textutil.match_brace(code, m.end() - 1)
        iid = sym_id(path, m.group("name"))
        result.symbols.append(Symbol(iid, TRAIT, m.group("name"), path, line(m.start()), line(close_b), lang, module_id,
                                     f"interface {m.group('name')}", meta={"interface": True, "exported": bool(m.group("exp"))}))
        for base in re.split(r",", m.group("base") or ""):
            if base.strip():
                result.refs.append(RawRef(iid, re.sub(r"<.*", "", base).strip(), "inherits", line(m.start())))
    skip_until = 0
    for rx in (FUNC, ARROW):
        for m in rx.finditer(code):
            if any(a <= m.start() < b for a, b in taken):
                continue
            if m.start() < skip_until:
                continue
            open_paren = code.rfind("(", m.start(), m.end()) if "(" in m.group(0) else -1
            if open_paren < 0:                                           # flèche à un seul paramètre sans parenthèses
                open_paren = m.end() - 1
                sid = sym_id(path, m.group("name"))
                bodies.append((Symbol(sid, FUNCTION, m.group("name"), path, line(m.start()), line(m.end()), lang, module_id,
                                      f"const {m.group('name')} = (…) =>", [], "", [], "", 1, {"exported": bool(m.group("exp"))}),
                               m.end(), code.find("\n", m.end()) if code.find("\n", m.end()) > 0 else len(code)))
                result.symbols.append(bodies[-1][0])
                continue
            add_function(m.group("name"), m.start(), open_paren, module_id, "", FUNCTION, bool(m.group("exp")), m.group("async"))
    for sym, lo, hi in bodies:
        body = code[lo:hi]
        seen = set()
        for m in CALL.finditer(body):
            expr = m.group(1)
            if expr.split(".")[0] in KEYWORDS or expr in seen:
                continue
            if expr.startswith("this.") and expr.count(".") == 1:
                pass
            seen.add(expr)
            result.refs.append(RawRef(sym.id, expr, "call", line(lo + m.start()), {"new": body[max(0, m.start() - 4):m.start() + 4].lstrip().startswith("new")}))
        for m in CALL_CHAIN.finditer(body):
            result.refs.append(RawRef(sym.id, "?." + m.group(1), "call", line(lo + m.start()), {"receiver": "unknown"}))
        for m in re.finditer(r"\b(?:eval|Function)\s*\(", body):
            result.issues.append(Issue(path, line(lo + m.start()), "error", "JS-EVAL", f"eval/Function dans {sym.name}()",
                                       "Exécuter du texte comme du code est dangereux avec des données externes.",
                                       "Évitez eval ; utilisez JSON.parse ou des fonctions.", sym.id))
        if sym.complexity > 25:
            result.issues.append(Issue(path, sym.line, "error", "COMPLEXITY", f"{sym.name}() est très complexe ({sym.complexity})",
                                       "Beaucoup de chemins d'exécution.", "Découpez en fonctions.", sym.id))
        elif sym.complexity > 15:
            result.issues.append(Issue(path, sym.line, "warn", "COMPLEXITY", f"{sym.name}() est complexe ({sym.complexity})",
                                       "Trop de branches.", "Extrayez des sous-fonctions.", sym.id))
    for m in re.finditer(r"[^=!<>]==[^=]|[^=!]!=[^=]", code):
        result.issues.append(Issue(path, line(m.start()), "info", "JS-LOOSE-EQ", "Égalité non stricte (== / !=)",
                                   "Les conversions implicites produisent des résultats surprenants.", "Utilisez === / !==."))
        break
    for m in re.finditer(r"\bvar\s+\w", code):
        result.issues.append(Issue(path, line(m.start()), "info", "JS-VAR", "Utilisation de var",
                                   "var a une portée de fonction et est « hissé » : source de bugs.", "Préférez const/let."))
        break
    for m in re.finditer(r"\.innerHTML\s*=", code):
        result.issues.append(Issue(path, line(m.start()), "warn", "JS-INNERHTML", "Affectation à innerHTML",
                                   "Insérer du HTML non filtré ouvre la porte aux injections XSS.", "Utilisez textContent ou un filtre."))
    for m in re.finditer(r"catch\s*(?:\([^)]*\))?\s*\{\s*\}", code):
        result.issues.append(Issue(path, line(m.start()), "warn", "SWALLOWED", "Bloc catch vide",
                                   "L'erreur est ignorée en silence.", "Journalisez ou traitez l'erreur."))
    for m in re.finditer(r"\bexport\s+default\s+(?:abstract\s+)?(?:async\s+)?(?:function\s*\*?\s*|class\s+)?([A-Za-z_$][\w$]*)", code):
        target = sym_id(path, m.group(1))
        for sym in result.symbols:
            if sym.id == target:
                sym.meta["default"] = True
                sym.meta["exported"] = True
    for m in re.finditer(r"\bmodule\.exports\s*=\s*([A-Za-z_$][\w$]*)\s*;?", code):
        for sym in result.symbols:
            if sym.id == sym_id(path, m.group(1)):
                sym.meta["default"] = sym.meta["exported"] = True
    if text.startswith("#!") and "node" in lines[0]:
        result.info["entry"] = "shebang"
    result.blocks = textutil.duplicate_blocks(code.splitlines())
    return result


class JsAnalyzer(Analyzer):
    lang = "javascript"
    extensions = (".js", ".mjs", ".cjs", ".jsx")

    def analyze_file(self, path: str, text: str) -> FileResult:
        return analyze_js(path, text, "javascript")


class TsAnalyzer(Analyzer):
    lang = "typescript"
    extensions = (".ts", ".tsx", ".mts", ".cts")

    def analyze_file(self, path: str, text: str) -> FileResult:
        return analyze_js(path, text, "typescript")


register(JsAnalyzer())
register(TsAnalyzer())
