"""Analyseur C / C++ : #include, #define, namespaces, classes/structs (bases), fonctions et méthodes, appels."""

from __future__ import annotations

import re

from ..core import textutil
from ..core.model import CLASS, FUNCTION, MACRO, METHOD, MODULE, STRUCT, FileResult, Issue, RawRef, Symbol, sym_id
from .base import Analyzer, register

INCLUDE = re.compile(r'^[ \t]*#\s*include\s*(?P<o>[<"])(?P<p>[^>"]+)[>"]', re.MULTILINE)
DEFINE = re.compile(r"^[ \t]*#\s*define\s+(?P<name>\w+)(?P<args>\([^)]*\))?", re.MULTILINE)
CLASS_RE = re.compile(r"\b(?P<kw>class|struct)\s+(?P<name>[A-Za-z_]\w*)\s*(?:final\s*)?(?::\s*(?P<bases>[^{;]+?))?\s*\{")
NAMESPACE = re.compile(r"\bnamespace\s+(?P<name>[\w:]+)\s*\{")
FUNC = re.compile(r"(?P<head>[\w:<>,\*&~\s]*?)(?<![\w])(?P<name>~?[A-Za-z_]\w*(?:::~?[A-Za-z_]\w*)*|operator\s*[^\s(]+)\s*"
                  r"\((?P<params>[^;{}()]*(?:\([^()]*\)[^;{}()]*)*)\)\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?(?:final\s*)?"
                  r"(?:->\s*[\w:<>\*&\s]+?)?\s*(?::\s*[^;{}]+?)?\s*\{")
CALL = re.compile(r"(?<![\w.>])((?:[A-Za-z_]\w*(?:::|->|\.))*[A-Za-z_]\w*)\s*(?:<[^<>()]*>)?\s*\(")
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "sizeof", "defined", "else", "do", "throw", "new", "delete",
            "static_cast", "dynamic_cast", "const_cast", "reinterpret_cast", "alignof", "decltype", "typeid", "noexcept"}
UNSAFE = {"gets": "error", "strcpy": "warn", "strcat": "warn", "sprintf": "warn", "system": "warn", "scanf": "info"}


def analyze_cpp(path: str, text: str, lang: str) -> FileResult:
    keep = textutil.mask_c_like(text, keep_strings=True)
    code = textutil.mask_c_like(text)
    code = re.sub(r"^[ \t]*#[^\n]*(?:\\\n[^\n]*)*", lambda m: re.sub(r"[^\n]", " ", m.group(0)), code, flags=re.MULTILINE)
    starts = textutil.line_starts(text)
    line = lambda i: textutil.line_at(starts, i)  # noqa: E731
    lines = text.splitlines()
    result = FileResult(path, lang, loc=len([ln for ln in lines if ln.strip() and not ln.strip().startswith("//")]))
    module_id = sym_id(path, "<module>")
    result.symbols.append(Symbol(module_id, MODULE, path.rsplit("/", 1)[-1], path, 1, len(lines), lang))
    for m in INCLUDE.finditer(keep):
        result.imports.append({"module": m.group("p"), "names": [], "alias": "", "level": 0, "line": line(m.start()),
                               "system": m.group("o") == "<", "c": True})
    for m in DEFINE.finditer(keep):
        result.symbols.append(Symbol(sym_id(path, m.group("name")), MACRO, m.group("name"), path, line(m.start()), line(m.start()),
                                     lang, module_id, "#define " + m.group("name") + (m.group("args") or "")))
    scopes: list[tuple[int, int, str, str]] = []            # (début, fin, nom qualifié, genre)
    for m in NAMESPACE.finditer(code):
        close = textutil.match_brace(code, m.end() - 1)
        if close > 0:
            scopes.append((m.end(), close, m.group("name"), "ns"))
    for m in CLASS_RE.finditer(code):
        close = textutil.match_brace(code, m.end() - 1)
        if close < 0:
            continue
        ns = next((n for a, b, n, k in scopes if k == "ns" and a <= m.start() < b), "")
        qn = f"{ns}::{m.group('name')}" if ns else m.group("name")
        cid = sym_id(path, m.group("name"))
        result.symbols.append(Symbol(cid, CLASS if m.group("kw") == "class" else STRUCT, m.group("name"), path, line(m.start()),
                                     line(close), lang, module_id, f"{m.group('kw')} {m.group('name')}"
                                     + (f" : {m.group('bases').strip()}" if m.group("bases") else ""), meta={"qualified": qn}))
        for base in re.split(r",", m.group("bases") or ""):
            base = re.sub(r"\b(?:public|private|protected|virtual)\b", "", base)
            base = re.sub(r"<.*", "", base).strip()
            if base:
                result.refs.append(RawRef(cid, base, "inherits", line(m.start())))
        scopes.append((m.end(), close, m.group("name"), "class"))
    bodies = []
    pos = 0
    for m in FUNC.finditer(code):
        name = m.group("name")
        if name.split("::")[-1] in KEYWORDS or name in KEYWORDS or m.start() < pos:
            continue
        head = re.sub(r"\b(?:public|private|protected)\s*:", "", m.group("head")).strip()
        if re.search(r"\b(?:else|return|new|delete|throw)\b\s*$", head):
            continue
        open_b = m.end() - 1
        close = textutil.match_brace(code, open_b)
        if close < 0:
            continue
        owner = next((n for a, b, n, k in sorted(scopes, key=lambda s: s[0], reverse=True) if k == "class" and a <= m.start() < b), "")
        if "::" in name:
            owner, _, short = name.rpartition("::")
        else:
            short = name
        # une « fonction » sans type de retour hors classe est presque toujours un appel de macro/contrôle : on l'ignore
        if not head and not owner and short not in ("main",):
            continue
        in_scope = next((n for a, b, n, k in scopes if k == "ns" and a <= m.start() < b), "")
        qn = f"{owner}.{short}" if owner else (f"{in_scope}::{short}" if in_scope else short)
        sid = sym_id(path, qn)
        params_txt = m.group("params").strip()
        sym = Symbol(sid, METHOD if owner else FUNCTION, short, path, line(m.start("name")), line(close), lang,
                     sym_id(path, owner) if owner else module_id,
                     re.sub(r"\s+", " ", f"{head} {name}({params_txt})").strip(),
                     [{"name": p.strip().split()[-1].strip("*&") if p.strip() else "", "annotation": p.strip(), "default": "",
                       "kind": "positional"} for p in params_txt.split(",") if p.strip() and p.strip() != "void"],
                     head, [], "", 1 + len(re.findall(r"\b(?:if|for|while|case|catch)\b", code[open_b:close]))
                     + code[open_b:close].count("&&") + code[open_b:close].count("||"), {"owner": owner})
        result.symbols.append(sym)
        bodies.append((sym, open_b, close))
        if short == "main" and not owner:
            result.info["entry"] = "main"
            sym.meta["entry"] = True
        pos = close + 1
    for sym, lo, hi in bodies:
        body, seen = code[lo:hi], set()
        for m in CALL.finditer(body):
            expr = m.group(1).replace("->", ".")
            if expr.split(".")[0].split("::")[0] in KEYWORDS or expr in seen:
                continue
            seen.add(expr)
            result.refs.append(RawRef(sym.id, expr, "call", line(lo + m.start())))
            last = expr.split("::")[-1].split(".")[-1]
            if last in UNSAFE:
                result.issues.append(Issue(path, line(lo + m.start()), UNSAFE[last], "C-UNSAFE-API", f"Appel de {last}()",
                                           "Fonction sans contrôle de taille/commande : risque de dépassement de tampon ou d'injection.",
                                           "Utilisez snprintf/strncpy_s/std::string ou une API sûre.", sym.id))
        if sym.complexity > 25:
            result.issues.append(Issue(path, sym.line, "error", "COMPLEXITY", f"{sym.name}() est très complexe ({sym.complexity})",
                                       "Beaucoup de chemins d'exécution.", "Découpez en fonctions.", sym.id))
        elif sym.complexity > 15:
            result.issues.append(Issue(path, sym.line, "warn", "COMPLEXITY", f"{sym.name}() est complexe ({sym.complexity})",
                                       "Trop de branches.", "Extrayez des sous-fonctions.", sym.id))
    if path.endswith((".h", ".hpp", ".hh")) and re.search(r"^\s*using\s+namespace\s+std\s*;", code, re.MULTILINE):
        result.issues.append(Issue(path, 1, "warn", "CPP-USING-NS", "using namespace std dans un en-tête",
                                   "Pollue l'espace de noms de tous les fichiers qui incluent cet en-tête.",
                                   "Qualifiez avec std:: ou limitez la portée."))
    result.blocks = textutil.duplicate_blocks(code.splitlines())
    return result


class CppAnalyzer(Analyzer):
    lang = "cpp"
    extensions = (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx")

    def analyze_file(self, path: str, text: str) -> FileResult:
        return analyze_cpp(path, text, "cpp")


class CAnalyzer(Analyzer):
    lang = "c"
    extensions = (".c", ".h")

    def analyze_file(self, path: str, text: str) -> FileResult:
        return analyze_cpp(path, text, "c")


register(CppAnalyzer())
register(CAnalyzer())
