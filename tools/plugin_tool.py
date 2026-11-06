#!/usr/bin/env python3
"""
Outil des contributeurs et de la CI pour les plugins Voktora (bibliothèque standard uniquement).

    python tools/plugin_tool.py new mon-plugin --author toi      # crée marketplace/plugins/mon-plugin/
    python tools/plugin_tool.py validate                         # vérifie tous les plugins (ou : validate mon-plugin)
    python tools/plugin_tool.py build-index                      # régénère marketplace/index.json
    python tools/plugin_tool.py build-index --check              # échoue si index.json n'est pas à jour
    python tools/plugin_tool.py zip mon-plugin                   # archive .zip installable depuis l'application

Codes de sortie : 0 = OK, 1 = erreurs de validation / index périmé, 2 = usage.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "marketplace"
PLUGINS = MARKET / "plugins"
INDEX = MARKET / "index.json"
SCHEMA = 1


def _load_manifest_module():
    """manifest.py est autonome : on le charge par son chemin, sans importer toute l'application."""
    path = ROOT / "voktora" / "plugins" / "manifest.py"
    spec = importlib.util.spec_from_file_location("voktora_plugin_manifest", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["voktora_plugin_manifest"] = module     # requis par @dataclass
    spec.loader.exec_module(module)
    return module


manifest = _load_manifest_module()

ALLOWED_SUFFIXES = {".py", ".json", ".md", ".txt", ".qss", ".svg", ".png", ".css"}
MAX_FILES, MAX_FILE_BYTES, MAX_PLUGIN_BYTES = 40, 512 * 1024, 2 * 1024 * 1024

# Imports qui exigent une permission déclarée.
NEEDS_PERMISSION = {
    "network": {"urllib.request", "urllib3", "requests", "httpx", "socket", "http.client", "ftplib",
                "smtplib", "aiohttp", "websockets"},
    "shell":   {"subprocess", "pty"},
}
# Appels toujours refusés dans un plugin du marketplace.
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}
FORBIDDEN_ATTRS = {("os", "system"), ("os", "popen"), ("os", "execv"), ("os", "execvp"), ("os", "spawnv")}
SUSPICIOUS_IMPORTS = {"ctypes", "base64", "marshal", "pickle", "winreg", "zlib"}


def _show(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _plugin_dirs(names: list[str]) -> list[Path]:
    if names:
        return [PLUGINS / n for n in names]
    return sorted(p for p in PLUGINS.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))) if PLUGINS.exists() else []


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.add(node.module.split(".")[0])
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
    return found


def check_source(path: Path, permissions: list[str]) -> tuple[list[str], list[str]]:
    """Analyse statique d'un fichier .py : (erreurs, avertissements). Ce n'est PAS un antivirus :
    c'est un filet de sécurité avant la relecture humaine du mainteneur."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [f"{path.name} : code illisible ({exc})"], []
    imports = _imports(tree)
    for permission, modules in NEEDS_PERMISSION.items():
        used = sorted(imports & modules)
        if used and permission not in permissions:
            errors.append(f"{path.name} : utilise {', '.join(used)} mais ne déclare pas la permission « {permission} ».")
    for name in sorted(imports & SUSPICIOUS_IMPORTS):
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
    text = path.read_text(encoding="utf-8")
    if re.search(r"[A-Za-z0-9+/]{200,}={0,2}", text):
        warnings.append(f"{path.name} : longue chaîne opaque (base64 ?) — à justifier dans la Pull Request.")
    return errors, warnings


def validate_plugin(folder: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not folder.is_dir():
        return [f"{folder.name} : dossier introuvable."], []
    manifest_path = folder / manifest.MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"{folder.name} : {manifest.MANIFEST_NAME} manquant."], []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"{folder.name} : plugin.json illisible ({exc})."], []
    parsed, problems = manifest.validate(data)
    errors += [f"{folder.name} : {p}" for p in problems]
    if parsed is None:
        return errors, warnings
    if parsed.id != folder.name:
        errors.append(f"{folder.name} : « id » ({parsed.id}) doit être identique au nom du dossier.")
    files = [p for p in sorted(folder.rglob("*")) if p.is_file()]
    if len(files) > MAX_FILES:
        errors.append(f"{folder.name} : trop de fichiers ({len(files)} > {MAX_FILES}).")
    total = 0
    for path in files:
        rel = path.relative_to(folder)
        if path.is_symlink():
            errors.append(f"{folder.name}/{rel} : lien symbolique interdit.")
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            errors.append(f"{folder.name}/{rel} : type de fichier non autorisé ({path.suffix or 'sans extension'}).")
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES:
            errors.append(f"{folder.name}/{rel} : trop volumineux ({size // 1024} Ko > {MAX_FILE_BYTES // 1024} Ko).")
    if total > MAX_PLUGIN_BYTES:
        errors.append(f"{folder.name} : plugin trop volumineux ({total // 1024} Ko).")
    if not (folder / parsed.entry).is_file():
        errors.append(f"{folder.name} : fichier d'entrée « {parsed.entry} » introuvable.")
    for path in files:
        if path.suffix == ".py" and not path.is_symlink():
            e, w = check_source(path, parsed.permissions)
            errors += [f"{folder.name}/{m}" for m in e]
            warnings += [f"{folder.name}/{m}" for m in w]
    if not parsed.description:
        warnings.append(f"{folder.name} : pas de description.")
    return errors, warnings


def _file_hashes(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file() and not p.is_symlink()}


def build_index() -> dict:
    entries = []
    for folder in _plugin_dirs([]):
        parsed = manifest.load(folder)
        entry = parsed.to_dict()
        entry["path"] = f"plugins/{parsed.id}"
        entry["files"] = _file_hashes(folder)
        del entry["entry"]
        entry["entry"] = parsed.entry
        entries.append(entry)
    return {"schema": SCHEMA, "plugins": sorted(entries, key=lambda e: e["id"])}


def _render(index: dict) -> str:
    return json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def cmd_validate(args: argparse.Namespace) -> int:
    folders = _plugin_dirs(args.plugins)
    if not folders:
        print("Aucun plugin à valider.")
        return 0
    failed = False
    seen_ids: set[str] = set()
    for folder in folders:
        errors, warnings = validate_plugin(folder)
        status = "ERREUR" if errors else "ok"
        print(f"[{status}] {folder.name}")
        for message in errors:
            print(f"    ✗ {message}")
        for message in warnings:
            print(f"    ! {message}")
        if folder.name in seen_ids:
            print(f"    ✗ identifiant en double : {folder.name}")
            errors.append("dup")
        seen_ids.add(folder.name)
        failed = failed or bool(errors)
    return 1 if failed else 0


def cmd_build_index(args: argparse.Namespace) -> int:
    for folder in _plugin_dirs([]):
        errors, _ = validate_plugin(folder)
        if errors:
            print("Index non généré : corrigez d'abord les erreurs (validate).", file=sys.stderr)
            return 1
    text = _render(build_index())
    if args.check:
        current = INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""
        if current != text:
            print("marketplace/index.json n'est pas à jour : lancez « python tools/plugin_tool.py build-index ».")
            return 1
        print("index.json à jour.")
        return 0
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(text, encoding="utf-8")
    print(f"{_show(INDEX)} : {len(json.loads(text)['plugins'])} plugin(s).")
    return 0


TEMPLATE_MAIN = '''"""{name} — plugin Voktora.

Documentation de l'API : doc/PLUGINS.md
"""


def on_load(api):
    api.add_menu_action("Plugins/{name}", "Dire bonjour", lambda ctx: api.notify("Bonjour depuis {name} !"),
                        icon="mdi:hand-wave-outline")
'''


def cmd_new(args: argparse.Namespace) -> int:
    if not manifest.ID_RE.match(args.id):
        print("Identifiant invalide : minuscules, chiffres et tirets (ex. mon-plugin).", file=sys.stderr)
        return 2
    folder = PLUGINS / args.id
    if folder.exists():
        print(f"{folder} existe déjà.", file=sys.stderr)
        return 2
    name = args.name or args.id.replace("-", " ").title()
    folder.mkdir(parents=True)
    (folder / "plugin.json").write_text(json.dumps({
        "id": args.id, "name": name, "version": "1.0.0", "author": args.author, "description": "À compléter.",
        "api": manifest.API_VERSION, "entry": "main.py", "permissions": ["ui"], "tags": [],
        "homepage": "",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "main.py").write_text(TEMPLATE_MAIN.format(name=name), encoding="utf-8")
    print(f"Plugin créé : {_show(folder)}\nÉtapes suivantes : modifiez-le, puis "
          f"« python tools/plugin_tool.py validate {args.id} » et ouvrez une Pull Request.")
    return 0


def cmd_zip(args: argparse.Namespace) -> int:
    folder = PLUGINS / args.id
    errors, _ = validate_plugin(folder)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else ROOT / f"{args.id}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(folder).as_posix())
    print(f"Archive créée : {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Outil des plugins Voktora")
    sub = parser.add_subparsers(dest="command", required=True)
    p_validate = sub.add_parser("validate", help="vérifie les plugins")
    p_validate.add_argument("plugins", nargs="*", help="identifiants (tous par défaut)")
    p_validate.set_defaults(func=cmd_validate)
    p_index = sub.add_parser("build-index", help="génère marketplace/index.json")
    p_index.add_argument("--check", action="store_true", help="échoue si l'index n'est pas à jour")
    p_index.set_defaults(func=cmd_build_index)
    p_new = sub.add_parser("new", help="crée un plugin à partir d'un modèle")
    p_new.add_argument("id")
    p_new.add_argument("--name", default="")
    p_new.add_argument("--author", default="votre-pseudo")
    p_new.set_defaults(func=cmd_new)
    p_zip = sub.add_parser("zip", help="crée une archive installable")
    p_zip.add_argument("id")
    p_zip.add_argument("--out", default="")
    p_zip.set_defaults(func=cmd_zip)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
