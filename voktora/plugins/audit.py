"""
Voktora — plugins.audit
Analyse statique d'un plugin (bibliothèque standard uniquement, aucun import de Voktora).

Utilisée à DEUX endroits, avec exactement les mêmes règles :
  • par `tools/plugin_tool.py` dans la CI, avant la relecture du mainteneur ;
  • par l'application, à l'installation puis à chaque chargement d'un plugin du marketplace
    (défense en profondeur : même si l'index ou la CI étaient contournés, un code interdit ne se charge pas).

Ce n'est PAS un antivirus ni un bac à sable : du code Python déterminé peut contourner une analyse
statique. Elle attrape les cas honnêtes et les erreurs ; la relecture humaine reste indispensable.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# Modules dont l'import exige une permission déclarée (partagé avec la garde d'import à l'exécution).
NEEDS_PERMISSION: dict[str, frozenset[str]] = {
    "network": frozenset({
        "socket", "ssl", "http.client", "urllib.request", "urllib3", "requests", "httpx", "ftplib",
        "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc.client", "aiohttp", "websockets",
    }),
    "shell": frozenset({"subprocess", "pty", "_posixsubprocess", "multiprocessing"}),
}
# Modules jamais autorisés dans un plugin : ils servent à contourner les règles (charger du code
# arbitraire, retrouver eval/exec, appeler du code natif).
ALWAYS_DENIED = frozenset({
    "ctypes", "_ctypes", "cffi", "importlib", "imp", "builtins", "marshal", "pickle", "shelve",
    "code", "codeop", "runpy", "zipimport", "pkgutil", "winreg", "_winapi",
})
FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "__import__", "breakpoint"})
FORBIDDEN_ATTRS = frozenset({
    ("os", "system"), ("os", "popen"), ("os", "execv"), ("os", "execve"), ("os", "execvp"),
    ("os", "spawnv"), ("os", "spawnl"), ("os", "startfile"), ("os", "fork"), ("os", "kill"),
})
SUSPICIOUS_IMPORTS = frozenset({"zlib", "binascii", "base64", "codecs"})
FORBIDDEN_NAMES = frozenset({"__builtins__", "__loader__", "__spec__"})
FORBIDDEN_DUNDER_ATTRS = frozenset({"__subclasses__", "__globals__", "__builtins__", "__code__", "__closure__",
                                    "__bases__", "__mro__"})

_OPAQUE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.update({alias.name, alias.name.split(".")[0]})
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.update({node.module, node.module.split(".")[0]})
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
    return found


def restricted_modules(permissions: list[str]) -> frozenset[str]:
    """Modules interdits pour ces permissions (garde d'import à l'exécution comprise)."""
    blocked = set(ALWAYS_DENIED)
    for permission, modules in NEEDS_PERMISSION.items():
        if permission not in permissions:
            blocked |= modules
    return frozenset(blocked)


def is_blocked(module_name: str, permissions: list[str]) -> bool:
    blocked = restricted_modules(permissions)
    parts = module_name.split(".")
    return any(".".join(parts[: i + 1]) in blocked for i in range(len(parts)))


def check_source(path: Path, permissions: list[str]) -> tuple[list[str], list[str]]:
    """(erreurs, avertissements) pour un fichier .py."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
    except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
        return [f"{path.name} : code illisible ({exc})"], []

    for name in sorted(_imports(tree)):
        if is_blocked(name, permissions):
            top = name.split(".")[0]
            needed = next((p for p, mods in NEEDS_PERMISSION.items() if name in mods or top in mods), None)
            if needed:
                errors.append(f"{path.name} : importe « {name} » mais ne déclare pas la permission « {needed} ».")
            else:
                errors.append(f"{path.name} : l'import de « {name} » est interdit dans un plugin.")
    for name in sorted(_imports(tree) & SUSPICIOUS_IMPORTS):
        warnings.append(f"{path.name} : import « {name} » — à justifier dans la Pull Request.")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                errors.append(f"{path.name}:{node.lineno} : appel à {func.id}() interdit.")
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                    and (func.value.id, func.attr) in FORBIDDEN_ATTRS:
                errors.append(f"{path.name}:{node.lineno} : {func.value.id}.{func.attr}() interdit (utilisez api.run).")
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value:
                    errors.append(f"{path.name}:{node.lineno} : shell=True interdit.")
            if isinstance(func, ast.Name) and func.id in {"getattr", "setattr", "delattr", "vars", "globals", "locals"}:
                warnings.append(f"{path.name}:{node.lineno} : {func.id}() — à justifier (introspection).")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_DUNDER_ATTRS:
            errors.append(f"{path.name}:{node.lineno} : accès à .{node.attr} interdit (contournement de l'analyse).")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_CALLS and isinstance(node.ctx, ast.Load):
            errors.append(f"{path.name}:{node.lineno} : référence à {node.id} interdite.")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            errors.append(f"{path.name}:{node.lineno} : utilisation de {node.id} interdite.")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value in FORBIDDEN_CALLS | FORBIDDEN_DUNDER_ATTRS | FORBIDDEN_NAMES:
            errors.append(f"{path.name}:{node.lineno} : chaîne « {node.value} » interdite "
                          f"(getattr dynamique vers une fonction interdite ?).")

    errors = list(dict.fromkeys(errors))
    if _OPAQUE.search(text):
        warnings.append(f"{path.name} : longue chaîne opaque (base64 ?) — à justifier dans la Pull Request.")
    return errors, warnings


def scan_folder(folder: Path, permissions: list[str]) -> tuple[list[str], list[str]]:
    """Analyse tous les .py d'un dossier de plugin (hors dossiers cachés et __pycache__)."""
    errors: list[str] = []
    warnings: list[str] = []
    for path in sorted(folder.rglob("*.py")):
        rel = path.relative_to(folder)
        if path.is_symlink() or any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        e, w = check_source(path, permissions)
        errors += [m if str(rel) == path.name else f"{rel.parent}/{m}" for m in e]
        warnings += [m if str(rel) == path.name else f"{rel.parent}/{m}" for m in w]
    return errors, warnings
