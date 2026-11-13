"""Extraction de symboles et détection du rôle des fichiers."""

from __future__ import annotations

import ast
import re

LANGS = {".py": "python", ".rs": "rust", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".ts": "typescript", ".tsx": "typescript",
         ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".go": "go", ".java": "java", ".md": "markdown", ".toml": "toml",
         ".json": "json", ".yml": "yaml", ".yaml": "yaml", ".sh": "shell", ".html": "html", ".css": "css", ".sql": "sql", ".txt": "text", ".rst": "text"}
RUST_ITEM = re.compile(r"^\s*(?:pub(?:\([a-z]+\))?\s+)?(?:async\s+|unsafe\s+|const\s+)*(fn|struct|enum|trait|mod|type)\s+([A-Za-z_]\w*)", re.M)
JS_ITEM = re.compile(r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?(function\*?|class)\s+([A-Za-z_$][\w$]*)|"
                     r"^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", re.M)
C_ITEM = re.compile(r"^(?:[A-Za-z_][\w:<>\*&\s]+?)\s+\**([A-Za-z_]\w*)\s*\([^;{)]*\)\s*(?:const\s*)?\{", re.M)
GO_ITEM = re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)|^type\s+([A-Za-z_]\w*)\s+(struct|interface)", re.M)
MD_HEAD = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.M)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def extract(path: str, lang: str, text: str) -> list[dict]:
    """[{name, kind, line, signature, doc, parent, public}]"""
    out: list[dict] = []
    if lang == "python":
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return out

        def walk(body, parent=""):
            for n in body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [a.arg for a in n.args.args + n.args.kwonlyargs]
                    if n.args.vararg:
                        args.append("*" + n.args.vararg.arg)
                    if n.args.kwarg:
                        args.append("**" + n.args.kwarg.arg)
                    doc = (ast.get_docstring(n) or "").strip().split("\n")[0]
                    out.append({"name": n.name, "kind": "method" if parent else "function", "line": n.lineno,
                                "signature": f"{'async ' if isinstance(n, ast.AsyncFunctionDef) else ''}def {n.name}({', '.join(args)})",
                                "doc": doc, "parent": parent, "public": not n.name.startswith("_")})
                elif isinstance(n, ast.ClassDef):
                    bases = [ast.unparse(b) for b in n.bases]
                    out.append({"name": n.name, "kind": "class", "line": n.lineno, "signature": f"class {n.name}({', '.join(bases)})" if bases else f"class {n.name}",
                                "doc": (ast.get_docstring(n) or "").strip().split("\n")[0], "parent": parent, "public": not n.name.startswith("_")})
                    walk(n.body, n.name)
        walk(tree.body)
    elif lang == "rust":
        for m in RUST_ITEM.finditer(text):
            line = text[m.start():text.find("\n", m.start()) if "\n" in text[m.start():] else None].strip()
            out.append({"name": m.group(2), "kind": m.group(1), "line": line_of(text, m.start()), "signature": line.rstrip("{ ").strip(), "doc": "",
                        "parent": "", "public": "pub" in line.split(m.group(1))[0]})
    elif lang in ("javascript", "typescript"):
        for m in JS_ITEM.finditer(text):
            name = m.group(2) or m.group(3)
            out.append({"name": name, "kind": "class" if m.group(1) == "class" else "function", "line": line_of(text, m.start()),
                        "signature": text[m.start():text.find("\n", m.start())].strip()[:100], "doc": "", "parent": "", "public": "export" in text[m.start():m.start() + 12]})
    elif lang in ("c", "cpp"):
        for m in C_ITEM.finditer(text):
            if m.group(1) not in ("if", "for", "while", "switch", "return"):
                out.append({"name": m.group(1), "kind": "function", "line": line_of(text, m.start()), "signature": m.group(0).rstrip("{ ").strip()[:100],
                            "doc": "", "parent": "", "public": True})
    elif lang == "go":
        for m in GO_ITEM.finditer(text):
            name = m.group(1) or m.group(2)
            out.append({"name": name, "kind": "function" if m.group(1) else m.group(3), "line": line_of(text, m.start()),
                        "signature": text[m.start():text.find("\n", m.start())].strip()[:100], "doc": "", "parent": "", "public": name[:1].isupper()})
    elif lang == "markdown":
        for m in MD_HEAD.finditer(text):
            out.append({"name": m.group(2), "kind": "heading", "line": line_of(text, m.start()), "signature": m.group(0), "doc": "", "parent": "", "public": True})
    return out


def imports(lang: str, text: str) -> list[str]:
    """Noms de modules importés (bruts)."""
    found: list[str] = []
    if lang == "python":
        try:
            for n in ast.walk(ast.parse(text)):
                if isinstance(n, ast.Import):
                    found += [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom):
                    base = ("." * n.level) + (n.module or "")
                    found.append(base)
                    found += [f"{base}.{a.name}" if (n.module or "") else f"{base}{a.name}" for a in n.names if a.name != "*"]
        except (SyntaxError, ValueError):
            pass
    elif lang in ("javascript", "typescript"):
        found += re.findall(r"""(?:import[^'"]*?from\s*|import\s*|require\()\s*['"]([^'"]+)['"]""", text)
    elif lang == "rust":
        found += [a or b for a, b in re.findall(r"^\s*(?:pub\s+)?(?:use\s+([A-Za-z_][\w:]*)|mod\s+([A-Za-z_]\w*)\s*;)", text, re.M)]
    elif lang in ("c", "cpp"):
        found += re.findall(r'^\s*#\s*include\s*"([^"]+)"', text, re.M)
    elif lang == "go":
        for block, single in re.findall(r"import\s*\(([^)]*)\)|import\s+(\"[^\"]+\")", text, re.S):
            found += re.findall(r'"([^"]+)"', block or single)
    return found


ROLE_RULES = [
    ("test", re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.(py|go|rs)$|\.(test|spec)\.[jt]sx?$")),
    ("doc", re.compile(r"(^|/)(docs?|documentation)/|\.(md|rst)$|(^|/)(README|CHANGELOG|LICENSE)", re.I)),
    ("build", re.compile(r"(^|/)(Makefile|Dockerfile|Cargo\.toml|pyproject\.toml|package\.json|setup\.py|CMakeLists\.txt|PKGBUILD|build\.rs|go\.mod|"
                         r"\.github/workflows/[^/]+|docker-compose[^/]*\.ya?ml)$")),
    ("config", re.compile(r"\.(toml|ya?ml|ini|cfg|json|env)$|(^|/)\.[a-z]+rc$")),
    ("ui", re.compile(r"(^|/)(ui|views?|widgets?|components?|pages?|templates?|gui)/|\.(html|css|qss|ui)$|(^|/)(dialog|window)[^/]*$", re.I)),
    ("model", re.compile(r"(^|/)(models?|schemas?|entities|types)(/|\.)", re.I)),
    ("service", re.compile(r"(^|/)(services?|core|api|controllers?|handlers?|routes?|lib)/", re.I)),
    ("script", re.compile(r"(^|/)(scripts?|tools?|bin)/|\.sh$")),
    ("util", re.compile(r"(^|/)(utils?|helpers?|common|shared)(/|\.)", re.I)),
]
ENTRY_NAMES = re.compile(r"(^|/)(main|app|index|cli|__main__|server|manage)\.(py|rs|js|ts|go|c|cpp)$")


def role_of(path: str, lang: str, text: str = "") -> str:
    if ENTRY_NAMES.search(path) or (lang == "python" and "if __name__ == " in text) or (lang == "rust" and re.search(r"\bfn main\s*\(", text)):
        return "entrée"
    for role, rx in ROLE_RULES:
        if rx.search(path):
            return {"test": "test", "doc": "documentation", "build": "build", "config": "configuration", "ui": "interface", "model": "modèle",
                    "service": "service", "script": "script", "util": "utilitaire"}[role]
    return "code" if lang not in ("markdown", "text", "json", "yaml", "toml") else "données"
