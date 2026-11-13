"""
Voktora — plugins.detect (1.1.1)
Détection AUTOMATIQUE des permissions d'un plugin à partir de son code (Python, JavaScript, Rust).

Bibliothèque standard uniquement et aucun import de Voktora : l'outil `tools/plugin_tool.py` (CI, contributeurs)
s'en sert sans lancer l'application, et l'application s'en sert pour les plugins dont le manifeste dit
`"permissions": "auto"` ainsi que dans l'outil de création de plugins.

La table « méthode de l'API → permission » n'est PAS écrite à la main : elle est lue dans le code de l'API
(`self._require("…")`, `self._host()` → « ui »), donc elle reste toujours juste quand l'API évolue.

Limite honnête : c'est une analyse statique. Du code qui construit ses appels dynamiquement (`getattr(api, nom)`)
échappe à la détection ; l'API vérifie de toute façon la permission à l'exécution (et le marketplace interdit
ces constructions). Pour du code natif (Rust), la détection signale ce qu'elle voit mais ne peut RIEN empêcher.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
API_FILES = ("runtime.py", "api_ext.py", "api_more.py", "options.py")
API_CLASSES = {"PluginAPI", "ExtendedAPI", "MoreAPI", "PluginOptions"}

# Modules Python qui exigent une permission (même table que audit.py ; recopiée pour rester autonome).
PY_IMPORTS: dict[str, frozenset[str]] = {
    "network": frozenset({"socket", "ssl", "http.client", "urllib.request", "urllib3", "requests", "httpx", "ftplib",
                          "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc.client", "aiohttp", "websockets"}),
    "shell": frozenset({"subprocess", "pty", "_posixsubprocess", "multiprocessing"}),
    "system": frozenset({"psutil"}),
    "clipboard": frozenset(),
}
RUST_NETWORK = re.compile(r"std::net\b|TcpStream|UdpSocket|TcpListener|\b(reqwest|ureq|hyper|surf|isahc|attohttpc|"
                          r"curl|tokio::net|async_std::net|mio::net|tungstenite|rustls|native_tls|openssl)\b")
RUST_SHELL = re.compile(r"std::process\b|Command::new|\bduct\b|\bxshell\b")
RUST_CRATE_NETWORK = re.compile(r"^\s*(reqwest|ureq|hyper|surf|isahc|attohttpc|curl|tungstenite|rustls|native-tls|"
                                r"openssl|tokio|async-std|mio|socket2|trust-dns[\w-]*)\b", re.MULTILINE)
RUST_CRATE_SHELL = re.compile(r"^\s*(duct|xshell|subprocess|sysinfo|command-group)\b", re.MULTILINE)
JS_CALL = re.compile(r"\bvoktora\s*\.\s*([A-Za-z_]\w*)\s*\(")
RUST_CALL = re.compile(r"\bapi\s*\.\s*([a-z_][a-z0-9_]*)\s*\(")


@dataclass
class Detection:
    permissions: set[str] = field(default_factory=set)
    reasons: dict[str, list[str]] = field(default_factory=dict)     # permission → où elle a été vue
    warnings: list[str] = field(default_factory=list)
    imports: set[str] = field(default_factory=set)                  # modules Python importés (hors relatifs)

    def add(self, permission: str, reason: str) -> None:
        self.permissions.add(permission)
        reasons = self.reasons.setdefault(permission, [])
        if reason not in reasons and len(reasons) < 6:
            reasons.append(reason)

    def merge(self, other: Detection) -> None:
        for permission, reasons in other.reasons.items():
            for reason in reasons:
                self.add(permission, reason)
        self.permissions |= other.permissions
        self.warnings += [w for w in other.warnings if w not in self.warnings]
        self.imports |= other.imports


# ── table « méthode → permission » lue dans le code de l'API ────────────────────

_table_cache: dict[str, str] | None = None


def _method_permission(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "self":
            if node.func.attr == "_require" and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                return node.args[0].value
            if node.func.attr == "_host":
                return "ui"
    return None


def _self_calls(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {n.func.attr for n in ast.walk(func) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"}


def api_permissions(refresh: bool = False) -> dict[str, str]:
    """{nom de méthode: permission} pour toutes les méthodes publiques de l'API qui en exigent une."""
    global _table_cache
    if _table_cache is not None and not refresh:
        return _table_cache
    table: dict[str, str] = {}
    calls: dict[str, set[str]] = {}
    aliases: list[tuple[str, str]] = []
    for name in API_FILES:
        path = HERE / name
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in API_CLASSES):
            for node in cls.body:
                if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                    perm = _method_permission(node)
                    if perm:
                        table[node.name] = perm
                    else:
                        calls[node.name] = _self_calls(node)
                elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):   # on = register_hook
                    aliases += [(t.id, node.value.id) for t in node.targets if isinstance(t, ast.Name)]
    changed = True
    while changed:                     # http_get n'exige rien lui-même mais appelle http_request (« network »)
        changed = False
        for name, called in calls.items():
            if name not in table:
                perm = next((table[c] for c in sorted(called) if c in table), None)
                if perm:
                    table[name] = perm
                    changed = True
    for alias, target in aliases:
        if target in table:
            table[alias] = table[target]
    _table_cache = table
    return table


def camel_to_snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", lambda m: "_" + m.group(1).lower(), name).lower()


# ── Python ──────────────────────────────────────────────────────────────────────

def _api_names(tree: ast.AST) -> set[str]:
    """Noms qui désignent l'objet API : « api » + premier paramètre de on_load / on_unload."""
    names = {"api"}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {"on_load", "on_unload"} and node.args.args:
            names.add(node.args.args[0].arg)
    return names


def detect_python_source(text: str, label: str = "main.py") -> Detection:
    out = Detection()
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        out.warnings.append(f"{label} : code illisible ({exc.msg}, ligne {exc.lineno}) — détection incomplète.")
        return out
    table = api_permissions()
    names = _api_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        else:
            modules = []
        for module in modules:
            out.imports.add(module.split(".")[0])
            parts = module.split(".")
            for permission, blocked in PY_IMPORTS.items():
                if any(".".join(parts[: i + 1]) in blocked for i in range(len(parts))):
                    out.add(permission, f"{label} : import {module}")
        if isinstance(node, ast.Attribute) and node.attr in table:
            base = node.value
            is_api = (isinstance(base, ast.Name) and base.id in names) or (
                isinstance(base, ast.Attribute) and base.attr in names and isinstance(base.value, ast.Name)
                and base.value.id == "self")
            if is_api:
                out.add(table[node.attr], f"{label}:{node.lineno} : api.{node.attr}()")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"getattr", "setattr"} \
                and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id in names:
            out.warnings.append(f"{label}:{node.lineno} : getattr sur l'API — permissions non détectables "
                                "(déclarez-les à la main).")
    return out


# ── JavaScript ──────────────────────────────────────────────────────────────────

def detect_js_source(text: str, label: str = "main.js") -> Detection:
    out = Detection()
    table = api_permissions()
    stripped = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.DOTALL)
    for match in JS_CALL.finditer(stripped):
        method = camel_to_snake(match.group(1))
        if method in table:
            line = stripped.count("\n", 0, match.start()) + 1
            out.add(table[method], f"{label}:{line} : voktora.{match.group(1)}()")
    if re.search(r"\bvoktora\s*\[", stripped):
        out.warnings.append(f"{label} : accès dynamique à « voktora[...] » — permissions non détectables.")
    return out


# ── Rust ────────────────────────────────────────────────────────────────────────

def detect_rust(folder: Path) -> Detection:
    out = Detection()
    out.add("native", "plugin Rust (code natif)")
    table = api_permissions()
    for path in sorted((folder / "src").rglob("*.rs")) if (folder / "src").is_dir() else []:
        text = re.sub(r"//[^\n]*|/\*.*?\*/", "", path.read_text(encoding="utf-8", errors="replace"), flags=re.DOTALL)
        label = str(path.relative_to(folder))
        for match in RUST_CALL.finditer(text):
            if match.group(1) in table:
                line = text.count("\n", 0, match.start()) + 1
                out.add(table[match.group(1)], f"{label}:{line} : api.{match.group(1)}()")
        for regex, permission in ((RUST_NETWORK, "network"), (RUST_SHELL, "shell")):
            found = regex.search(text)
            if found:
                out.add(permission, f"{label} : {found.group(0)}")
    cargo = folder / "Cargo.toml"
    if cargo.is_file():
        deps = cargo.read_text(encoding="utf-8", errors="replace")
        section = re.split(r"^\[(?:dev-|build-)?dependencies[^\]]*\]\s*$", deps, flags=re.MULTILINE)
        body = "\n".join(section[1:])
        found = RUST_CRATE_NETWORK.search(body)
        if found:
            out.add("network", f"Cargo.toml : crate {found.group(1)}")
        found = RUST_CRATE_SHELL.search(body)
        if found:
            out.add("shell" if found.group(1) != "sysinfo" else "system", f"Cargo.toml : crate {found.group(1)}")
    out.warnings.append("Code natif : Voktora ne peut pas restreindre ce que fait le plugin (réseau, fichiers, "
                        "processus). Les permissions détectées ne sont qu'indicatives.")
    return out


# ── dossier complet ─────────────────────────────────────────────────────────────

def _files(folder: Path, suffixes: tuple[str, ...]) -> list[Path]:
    out = []
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder)
        if path.suffix in suffixes and path.is_file() and not path.is_symlink() \
                and not any(p.startswith(".") or p in {"__pycache__", "libs", "target", "node_modules"} for p in rel.parts):
            out.append(path)
    return out


def detect_folder(folder: Path, manifest: dict | None = None) -> Detection:
    """Permissions nécessaires à tout le plugin (`manifest` : contenu de plugin.json, déjà lu ou non)."""
    folder = Path(folder)
    if manifest is None:
        import json
        try:
            manifest = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    lang = manifest.get("lang", "python")
    out = Detection()
    if lang == "rust":
        out.merge(detect_rust(folder))
    elif lang == "js":
        for path in _files(folder, (".js", ".mjs")):
            out.merge(detect_js_source(path.read_text(encoding="utf-8", errors="replace"), str(path.relative_to(folder))))
    else:
        for path in _files(folder, (".py",)):
            out.merge(detect_python_source(path.read_text(encoding="utf-8", errors="replace"),
                                           str(path.relative_to(folder))))
    if manifest.get("requires"):
        out.add("libs", "plugin.json : requires")
    return out


def missing_permissions(folder: Path, declared: list[str], manifest: dict | None = None) -> dict[str, list[str]]:
    """{permission manquante: raisons} : ce que le code utilise sans l'avoir déclaré."""
    found = detect_folder(folder, manifest)
    return {p: found.reasons.get(p, []) for p in sorted(found.permissions - set(declared))}


def unused_permissions(folder: Path, declared: list[str], manifest: dict | None = None) -> list[str]:
    """Permissions déclarées mais jamais utilisées (information : le moins de droits possible)."""
    return sorted(set(declared) - detect_folder(folder, manifest).permissions)
