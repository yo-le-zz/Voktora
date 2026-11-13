"""Analyseur Rust (sur le texte, commentaires/chaînes masqués) : mod, use, fn, struct, enum, trait, impl, macros, appels,
attributs PyO3 et `extern "C"`. Les accolades sont appariées : les corps de fonctions sont délimités exactement."""

from __future__ import annotations

import re

from ..core import textutil
from ..core.model import (
    CLASS,
    ENUM,
    FUNCTION,
    MACRO,
    METHOD,
    MODULE,
    STRUCT,
    TRAIT,
    FileResult,
    Issue,
    RawRef,
    Symbol,
    sym_id,
)
from .base import Analyzer, register

ITEM = re.compile(
    r"(?P<attrs>(?:#!?\[[^\]\n]*\]\s*)*)"
    r"(?P<vis>pub(?:\([^)]*\))?\s+)?"
    r"(?P<qual>(?:(?:async|unsafe|const|default)\s+|extern(?:\s+\"[^\"]*\")?\s+)*)"
    r"(?P<kw>fn|struct|enum|trait|impl|mod|macro_rules!|use|union)\b\s*")
ATTR = re.compile(r"#!?\[([^\]]*)\]")
CALL = re.compile(r"(?<![\w.$])((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*(?:::\s*<[^<>()]*(?:<[^<>]*>[^<>()]*)*>)?\s*\(")
METHOD_CALL = re.compile(r"((?:self|[A-Za-z_]\w*)(?:\s*\.\s*[A-Za-z_]\w*)*)\s*\.\s*([A-Za-z_]\w*)\s*(?:::\s*<[^()]*?>)?\s*\(")
CHAIN_CALL = re.compile(r"\)\s*\.\s*([A-Za-z_]\w*)\s*\(")
MACRO_CALL = re.compile(r"(?<![\w.])((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)!\s*[\(\[\{]")
KEYWORDS = {"if", "while", "match", "for", "loop", "return", "fn", "let", "in", "else", "as", "move", "unsafe", "async",
            "await", "where", "impl", "dyn", "mut", "ref", "box", "break", "continue", "Some", "Ok", "Err", "None", "Self",
            "super", "crate"}
STD_SKIP = {"Box::new", "Vec::new", "String::new", "Rc::new", "Arc::new", "String::from", "Vec::with_capacity"}


def expand_use(text: str, prefix: str = "") -> list[tuple[str, str]]:
    """`a::{b, c::d as e, f::*}` → [("a::b",""), ("a::c::d","e"), ("a::f::*","")]."""
    text = text.strip()
    out: list[tuple[str, str]] = []
    brace = text.find("{")
    if brace < 0:
        alias = ""
        m = re.match(r"(.*?)\s+as\s+(\w+)$", text)
        if m:
            text, alias = m.group(1).strip(), m.group(2)
        path = (prefix + text).strip(":")
        return [(path, alias)] if path else []
    head = prefix + text[:brace].strip()
    end = textutil.match_brace(text, brace)
    inner = text[brace + 1:end]
    depth, start, parts = 0, 0, []
    for i, ch in enumerate(inner):
        depth += ch == "{"
        depth -= ch == "}"
        if ch == "," and depth == 0:
            parts.append(inner[start:i])
            start = i + 1
    parts.append(inner[start:])
    for part in parts:
        if part.strip():
            if part.strip() == "self":
                out.append((head.rstrip(":"), ""))
            else:
                out.extend(expand_use(part, head))
    return out


def balanced(text: str, start: int, open_ch: str, close_ch: str) -> int:
    return textutil.match_brace(text, start, open_ch, close_ch)


def body_complexity(body: str) -> int:
    score = 1 + len(re.findall(r"\b(?:if|while|for|loop)\b", body)) + len(re.findall(r"=>", body))
    return score + body.count("&&") + body.count("||") + len(re.findall(r"\?(?![\w])", body))


class _Rust:
    def __init__(self, path: str, orig: str) -> None:
        self.path, self.orig = path, orig
        self.masked = textutil.mask_c_like(orig, rust=True)
        self.starts = textutil.line_starts(orig)
        self.result = FileResult(path, "rust")
        self.module_id = sym_id(path, "<module>")
        self.fn_bodies: list[tuple[Symbol, int, int]] = []

    def line(self, index: int) -> int:
        return textutil.line_at(self.starts, index)

    def issue(self, index, sev, code, title, explain, hint, symbol=""):
        self.result.issues.append(Issue(self.path, self.line(index), sev, code, title, explain, hint, symbol))

    # ------------------------------------------------------------------------------------------------
    def scan(self, lo: int, hi: int, parent: str, modpath: list[str], impl_type: str = "", trait_ctx: bool = False) -> None:
        text, pos = self.masked, lo
        while pos < hi:
            m = ITEM.search(text, pos, hi)
            if not m:
                break
            kw = m.group("kw")
            attrs = [a.strip() for a in ATTR.findall(m.group("attrs") or "")]
            at = m.end()
            if kw == "use":
                end = text.find(";", at, hi)
                end = hi if end < 0 else end
                for full, alias in expand_use(text[at:end]):
                    head, _, last = full.rpartition("::")
                    self.result.imports.append({"module": head, "names": [[last, alias]], "alias": "", "level": 0,
                                                "line": self.line(m.start("kw")), "rust": True})
                pos = end + 1
            elif kw == "mod":
                n = re.match(r"(\w+)\s*([;{])", text[at:hi])
                if not n:
                    pos = at
                    continue
                name = n.group(1)
                if n.group(2) == ";":
                    self.result.imports.append({"module": name, "names": [], "alias": "", "level": 0,
                                                "line": self.line(m.start("kw")), "mod_decl": True, "rust": True})
                    pos = at + n.end()
                else:
                    open_i = at + n.end() - 1
                    close = balanced(text, open_i, "{", "}")
                    close = hi if close < 0 else close
                    qn = ".".join([*modpath, name])
                    sid = sym_id(self.path, qn)
                    self.result.symbols.append(Symbol(sid, MODULE, name, self.path, self.line(m.start("kw")),
                                                      self.line(close), "rust", parent, f"mod {name}", meta={"inline": True}))
                    self.scan(open_i + 1, close, sid, [*modpath, name])
                    pos = close + 1
            elif kw == "macro_rules!":
                n = re.match(r"(\w+)\s*[\{\(\[]", text[at:hi])
                if n:
                    open_i = at + n.end() - 1
                    close_ch = {"{": "}", "(": ")", "[": "]"}[text[open_i]]
                    close = balanced(text, open_i, text[open_i], close_ch)
                    close = hi if close < 0 else close
                    self.result.symbols.append(Symbol(sym_id(self.path, n.group(1) + "!"), MACRO, n.group(1) + "!", self.path,
                                                      self.line(m.start("kw")), self.line(close), "rust", parent,
                                                      f"macro_rules! {n.group(1)}", meta={"exported": "macro_export" in " ".join(attrs)}))
                    pos = close + 1
                else:
                    pos = at
            elif kw in ("struct", "enum", "union", "trait"):
                n = re.match(r"(\w+)", text[at:hi])
                if not n:
                    pos = at
                    continue
                name = n.group(1)
                kind = {"struct": STRUCT, "union": STRUCT, "enum": ENUM, "trait": TRAIT}[kw]
                after = at + n.end()
                gen_end = after
                if text[after:after + 1] == "<":
                    close = balanced(text, after, "<", ">")
                    gen_end = close + 1 if close > 0 else after
                stop = re.compile(r"[{;(]").search(text, gen_end, hi)
                header_end = stop.start() if stop else hi
                supers = text[gen_end:header_end]
                sid = sym_id(self.path, ".".join([*modpath, name]) if modpath else name)
                sym = Symbol(sid, kind, name, self.path, self.line(m.start("kw")), self.line(header_end), "rust", parent,
                             f"{kw} {name}", meta={"attrs": attrs, "public": bool(m.group("vis"))})
                pyo3 = [a for a in attrs if a.startswith(("pyclass", "pyo3::pyclass"))]
                if pyo3:
                    sym.meta["pyo3"] = "pyclass"
                    nm = re.search(r'name\s*=\s*"(\w+)"', pyo3[0])
                    sym.meta["py_name"] = nm.group(1) if nm else name
                self.result.symbols.append(sym)
                if kw == "trait" and ":" in supers:
                    for sup in re.split(r"\+", supers.split(":", 1)[1].split("where")[0]):
                        sup = re.sub(r"<.*", "", sup).strip()
                        if sup and sup != "'static":
                            self.result.refs.append(RawRef(sid, sup, "inherits", sym.line))
                if stop and text[stop.start()] == "{":
                    close = balanced(text, stop.start(), "{", "}")
                    close = hi if close < 0 else close
                    sym.end_line = self.line(close)
                    if kw == "trait":
                        self.scan(stop.start() + 1, close, sid, [*modpath, name], impl_type=name, trait_ctx=True)
                    pos = close + 1
                else:
                    pos = (stop.start() + 1) if stop else hi
                    if stop and text[stop.start()] == "(":                     # struct Tuple(i32);
                        close = balanced(text, stop.start(), "(", ")")
                        pos = text.find(";", close if close > 0 else stop.start(), hi) + 1 or hi
            elif kw == "impl":
                brace = self._find_body_brace(at, hi)
                if brace < 0:
                    pos = at
                    continue
                header = text[at:brace]
                header = re.sub(r"^\s*<[^{}]*?>\s*(?=[\w:&])", "", header) if header.lstrip().startswith("<") else header
                header = header.split(" where ")[0]
                trait, typ = None, header.strip()
                if re.search(r"\bfor\b", header):
                    trait, typ = (x.strip() for x in re.split(r"\bfor\b", header, maxsplit=1))
                typ_name = re.sub(r"<.*", "", typ.strip().lstrip("&")).strip().split("::")[-1].strip()
                trait_name = re.sub(r"<.*", "", trait).strip() if trait else ""
                close = balanced(text, brace, "{", "}")
                close = hi if close < 0 else close
                owner = sym_id(self.path, typ_name)
                if trait_name:
                    self.result.refs.append(RawRef(owner, trait_name, "implements", self.line(m.start("kw")),
                                                   {"type": typ_name}))
                pyo3 = "pyo3" if any(a.startswith(("pymethods", "pyo3::pymethods")) for a in attrs) else ""
                self.scan(brace + 1, close, owner, [*modpath, typ_name], impl_type=typ_name)
                if pyo3:
                    for s in self.result.symbols:
                        if s.parent == owner and s.kind == METHOD and "pyo3" not in s.meta:
                            s.meta["pyo3"] = "pymethod"
                pos = close + 1
            else:                                                                  # fn
                n = re.match(r"(\w+)", text[at:hi])
                if not n:
                    pos = at
                    continue
                name = n.group(1)
                p = at + n.end()
                if text[p:p + 1] == "<":
                    close = balanced(text, p, "<", ">")
                    p = close + 1 if close > 0 else p
                while p < hi and text[p].isspace():
                    p += 1
                params_txt, p2 = "", p
                if text[p:p + 1] == "(":
                    close = balanced(text, p, "(", ")")
                    params_txt = text[p + 1:close]
                    p2 = close + 1
                stop = re.compile(r"[{;]").search(text, p2, hi)
                header_end = stop.start() if stop else hi
                ret = ""
                rm = re.search(r"->\s*(.*?)\s*(?:where\b|$)", text[p2:header_end], re.DOTALL)
                if rm:
                    ret = re.sub(r"\s+", " ", rm.group(1)).strip()
                params = self._params(params_txt)
                in_impl = bool(impl_type)
                qn = ".".join([*modpath, name]) if modpath else name
                kind = METHOD if in_impl and impl_type else FUNCTION
                sid = sym_id(self.path, qn)
                sym = Symbol(sid, kind, name, self.path, self.line(m.start("kw")), self.line(header_end), "rust", parent,
                             self._sig(name, params_txt, ret, m.group("qual") or "", bool(m.group("vis"))),
                             params, ret, attrs, meta={"public": bool(m.group("vis")), "attrs": attrs,
                                                         "impl_type": impl_type, "trait_decl": trait_ctx})
                if "extern" in (m.group("qual") or "") and "no_mangle" in " ".join(attrs):
                    sym.meta["extern_c"] = True
                for a in attrs:
                    head = a.split("(")[0].replace("pyo3::", "").strip()
                    if head in ("pyfunction", "pymodule"):
                        sym.meta["pyo3"] = head
                    if head == "pyo3":
                        nm = re.search(r'name\s*=\s*"(\w+)"', a)
                        if nm:
                            sym.meta["py_name"] = nm.group(1)
                    if head in ("wasm_bindgen", "napi", "tokio::main", "async_std::main"):
                        sym.meta["bridge"] = head
                if "pymodule" in sym.meta.get("pyo3", ""):
                    sym.meta.setdefault("py_name", name)
                if sym.meta.get("pyo3") == "pyfunction":
                    sym.meta.setdefault("py_name", name)
                self.result.symbols.append(sym)
                if stop and text[stop.start()] == "{":
                    close = balanced(text, stop.start(), "{", "}")
                    close = hi if close < 0 else close
                    sym.end_line = self.line(close)
                    sym.complexity = body_complexity(text[stop.start():close])
                    self.fn_bodies.append((sym, stop.start(), close))
                    self._nested_items(stop.start() + 1, close, sid, qn)
                    pos = close + 1
                else:
                    pos = (stop.start() + 1) if stop else hi
                if name == "main" and not modpath and not impl_type:
                    self.result.info["entry"] = "main"
                    self.result.info["main_line"] = sym.line
                    sym.meta["entry"] = True

    def _nested_items(self, lo: int, hi: int, parent: str, qn: str) -> None:
        """Fonctions déclarées DANS une fonction : enregistrées (portée = la fonction), sans réentrer dans leurs doublons."""
        text, pos = self.masked, lo
        while pos < hi:
            m = re.compile(r"\bfn\s+(\w+)").search(text, pos, hi)
            if not m:
                break
            self.scan(m.start(), hi, parent, [*qn.split(".")], impl_type="")
            break

    def _find_body_brace(self, start: int, hi: int) -> int:
        depth_angle = 0
        for i in range(start, hi):
            ch = self.masked[i]
            if ch == "<":
                depth_angle += 1
            elif ch == ">" and self.masked[i - 1] != "-":
                depth_angle = max(0, depth_angle - 1)
            elif ch == "{" and depth_angle == 0:
                return i
            elif ch == ";":
                return -1
        return -1

    def _params(self, text: str) -> list[dict]:
        out, depth, start = [], 0, 0
        for i, ch in enumerate(text + ","):
            if ch in "<([":
                depth += 1
            elif ch in ">)]" and not (ch == ">" and text[i - 1:i] == "-"):
                depth -= 1
            elif ch == "," and depth == 0:
                part = text[start:i].strip()
                start = i + 1
                if not part:
                    continue
                if re.fullmatch(r"&?\s*(?:'\w+\s+)?(?:mut\s+)?self(?:\s*:.*)?", part):
                    out.append({"name": "self", "annotation": "", "default": "", "kind": "positional"})
                    continue
                name, _, typ = part.partition(":")
                out.append({"name": name.strip().removeprefix("mut ").strip(), "annotation": typ.strip(), "default": "",
                            "kind": "positional"})
        return out

    @staticmethod
    def _sig(name: str, params: str, ret: str, qual: str, public: bool) -> str:
        return f"{'pub ' if public else ''}{re.sub(chr(10) + '|  +', ' ', qual).strip() + ' ' if qual.strip() else ''}fn {name}" \
               f"({re.sub(r'\s+', ' ', params).strip()})" + (f" -> {ret}" if ret else "")

    # ------------------------------------------------------------------------------------------------
    def calls(self) -> None:
        text = self.masked
        for sym, lo, hi in self.fn_bodies:
            body = text[lo:hi]
            base = lo
            seen = set()

            def add(expr, idx, kind="call", extra=None, sym=sym, base=base, seen=seen):
                key = (expr, kind, idx)
                if key in seen:
                    return
                seen.add(key)
                self.result.refs.append(RawRef(sym.id, expr, kind, self.line(base + idx), extra or {}))
            macro_spans = []
            for m in MACRO_CALL.finditer(body):
                add(m.group(1) + "!", m.start(), "call", {"macro": True})
                macro_spans.append((m.start(), m.end()))
            for m in METHOD_CALL.finditer(body):
                recv = re.sub(r"\s+", "", m.group(1))
                add(f"{recv}.{m.group(2)}", m.start(), "call")
            for m in CHAIN_CALL.finditer(body):
                add("?." + m.group(1), m.start(), "call", {"receiver": "unknown"})
            for m in CALL.finditer(body):
                expr = m.group(1)
                if expr in KEYWORDS or expr.split("::")[0] in KEYWORDS - {"Self", "super", "crate"} or expr in STD_SKIP:
                    continue
                before = body[max(0, m.start() - 4):m.start()]
                if re.search(r"fn\s*$", before) or re.search(r"\.\s*$", body[max(0, m.start() - 2):m.start()]):
                    continue
                if any(a <= m.start() < b for a, b in macro_spans) and "!" in body[m.end(1):m.end(1) + 1]:
                    continue
                add(expr, m.start(), "call")
            # qualité
            unwraps = len(re.findall(r"\.(?:unwrap|expect)\s*\(", body))
            if unwraps >= 3:
                self.issue(lo, "warn", "RS-UNWRAP", f"{sym.name}() utilise unwrap/expect {unwraps} fois",
                           "unwrap()/expect() font paniquer le programme sur une erreur ou une valeur absente.",
                           "Propagez l'erreur avec `?` ou traitez le cas Err/None.", sym.id)
            for kw, code, title in (("todo!", "RS-TODO", "todo!() restant"), ("unimplemented!", "RS-TODO", "unimplemented!() restant")):
                for m in re.finditer(re.escape(kw) + r"\s*[\(\[\{]", body):
                    self.issue(base + m.start(), "warn", code, title + f" dans {sym.name}()",
                               "Ce code panique dès qu'il est atteint.", "Implémentez-le.", sym.id)
            for m in re.finditer(r"\bunsafe\s*\{", body):
                self.issue(base + m.start(), "info", "RS-UNSAFE", f"Bloc unsafe dans {sym.name}()",
                           "Le compilateur ne vérifie plus la sûreté mémoire dans ce bloc.",
                           "Documentez l'invariant (// SAFETY:) et réduisez la portée du bloc.", sym.id)
            if sym.complexity > 25:
                self.issue(lo, "error", "COMPLEXITY", f"{sym.name}() est très complexe (complexité {sym.complexity})",
                           "Beaucoup de chemins d'exécution.", "Découpez en fonctions plus petites.", sym.id)
            elif sym.complexity > 15:
                self.issue(lo, "warn", "COMPLEXITY", f"{sym.name}() est complexe (complexité {sym.complexity})",
                           "Trop de branches pour être lisible.", "Extrayez des sous-fonctions.", sym.id)


def analyze_rust(path: str, text: str) -> FileResult:
    scanner = _Rust(path, text)
    lines = text.splitlines()
    result = scanner.result
    result.loc = len([ln for ln in lines if ln.strip() and not ln.strip().startswith("//")])
    result.symbols.append(Symbol(scanner.module_id, MODULE, path.rsplit("/", 1)[-1].removesuffix(".rs"), path, 1, len(lines), "rust"))
    scanner.scan(0, len(scanner.masked), scanner.module_id, [])
    scanner.calls()
    if re.search(r"#!?\[\s*(?:pyo3::)?pymodule", text):
        result.info["pyo3"] = True
    registers = []
    for sym, lo, hi in scanner.fn_bodies:
        if sym.meta.get("pyo3") == "pymodule":
            body = scanner.masked[lo:hi]
            registers.append({"module": sym.meta.get("py_name", sym.name), "fn": sym.id,
                              "functions": re.findall(r"wrap_pyfunction!\s*\(\s*(?:[\w:]*::)?(\w+)", body),
                              "classes": re.findall(r"add_class::<\s*(?:[\w:]*::)?(\w+)", body),
                              "submodules": re.findall(r"wrap_pymodule!\s*\(\s*(?:[\w:]*::)?(\w+)", body)})
    if registers:
        result.info["py_registers"] = registers
    calls = []
    for m in re.finditer(r"\.(import|import_bound|getattr|call_method|call_method0|call_method1)\s*\(\s*\"([^\"]+)\"", text):
        calls.append({"line": textutil.line_of(text, m.start()), "kind": m.group(1), "name": m.group(2)})
    if calls:
        result.info["python_calls"] = calls
    result.info["python_callbacks"] = [textutil.line_of(text, m.start()) for m in re.finditer(
        r"Python::with_gil|Python::attach|\.call_method\d?\s*\(|\.call1?\s*\(|\.getattr\s*\(|\.import(?:_bound)?\s*\(", scanner.masked)]
    result.blocks = textutil.duplicate_blocks(scanner.masked.splitlines())
    return result


class RustAnalyzer(Analyzer):
    lang = "rust"
    extensions = (".rs",)

    def analyze_file(self, path: str, text: str) -> FileResult:
        return analyze_rust(path, text)


register(RustAnalyzer())
del CLASS
