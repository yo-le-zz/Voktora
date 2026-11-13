#!/usr/bin/env python3
"""
Outil des contributeurs et de la CI pour les plugins Voktora (bibliothèque standard uniquement).

    python tools/plugin_tool.py new mon-plugin --author toi      # crée marketplace/plugins/mon-plugin/
    python tools/plugin_tool.py new mon-plugin --lang js|rust    # modèle JavaScript ou Rust (défaut : python)
    python tools/plugin_tool.py validate                         # vérifie tous les plugins (ou : validate mon-plugin)
    python tools/plugin_tool.py validate --run                   # … et EXÉCUTE chaque plugin dans un bac jetable
    python tools/plugin_tool.py detect                           # permissions détectées dans le code
    python tools/plugin_tool.py fix-permissions                  # les écrit dans plugin.json
    python tools/plugin_tool.py build-index                      # régénère marketplace/index.json
    python tools/plugin_tool.py build-index --check              # échoue si index.json n'est pas à jour
    python tools/plugin_tool.py zip mon-plugin                   # archive .zip installable depuis l'application
    python tools/plugin_tool.py submit https://github.com/vous/mon-plugin   # ajoute VOTRE fork en sous-module
    python tools/plugin_tool.py check-pr --base origin/main      # règles d'une PR communautaire (CI)
    python tools/plugin_tool.py drift                            # dépôts communautaires ayant changé depuis l'épinglage
    python tools/plugin_tool.py pr-summary --base origin/main    # ce qui change entre l'ancien et le nouveau commit

Codes de sortie : 0 = OK, 1 = erreurs de validation / index périmé, 2 = usage.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]       # d'où viennent l'outil et les règles (audit, manifeste)
# Dépôt analysé : par défaut le même ; la CI l'exécute avec l'outil de la branche principale (de confiance)
# sur le code de la Pull Request (non fiable) pour qu'une PR ne puisse pas affaiblir ses propres contrôles.
ROOT = Path(os.environ.get("PLUGIN_REPO_ROOT") or CODE_ROOT).resolve()
MARKET = ROOT / "marketplace"
PLUGINS = MARKET / "plugins"
COMMUNITY = MARKET / "community"
REVOKED = MARKET / "revoked.json"
GITMODULES = ROOT / ".gitmodules"
REPO_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]{1,39})/([A-Za-z0-9_.-]{1,100})$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
INDEX = MARKET / "index.json"
SCHEMA = 1


def _load_manifest_module():
    """manifest.py est autonome : on le charge par son chemin, sans importer toute l'application."""
    path = CODE_ROOT / "voktora" / "plugins" / "manifest.py"
    spec = importlib.util.spec_from_file_location("voktora_plugin_manifest", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["voktora_plugin_manifest"] = module     # requis par @dataclass
    spec.loader.exec_module(module)
    return module


manifest = _load_manifest_module()

ALLOWED_SUFFIXES = set(frozenset({
    ".py", ".json", ".md", ".txt", ".qss", ".svg", ".png", ".css",
    # 1.1.1 : plus de limite par extension pour les contenus non exécutables ni binaires natifs
    ".js", ".mjs", ".rs", ".toml", ".lock", ".html", ".htm", ".yaml", ".yml", ".ini", ".cfg", ".csv", ".tsv", ".xml",
    ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".ttf", ".otf", ".woff", ".woff2", ".wav", ".ogg", ".mp3", ".qml",
    ".ui", ".po", ".pyi", ".rst", ".license", ".typed",
}))
MAX_FILES, MAX_FILE_BYTES, MAX_PLUGIN_BYTES = 500, 32 * 1024 * 1024, 256 * 1024 * 1024

def _load_by_path(name: str, filename: str):
    path = CODE_ROOT / "voktora" / "plugins" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


audit = _load_by_path("voktora_plugin_audit", "audit.py")      # MÊMES règles que dans l'application
lock = _load_by_path("voktora_plugin_lock", "lock.py")
detect = _load_by_path("voktora_plugin_detect", "detect.py")   # permissions détectées dans le code (même table que l'appli)


def _show(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))) if root.exists() else []


def _plugin_dirs(names: list[str]) -> list[Path]:
    """Plugins officiels (dossiers) puis communautaires (sous-modules)."""
    if names:
        return [(COMMUNITY / n if (COMMUNITY / n).exists() else PLUGINS / n) for n in names]
    return _dirs(PLUGINS) + _dirs(COMMUNITY)


def _is_community(folder: Path) -> bool:
    return folder.parent == COMMUNITY


def _published(folder: Path, community: bool) -> list[Path]:
    """Fichiers réellement téléchargés par l'application. Communauté : seulement les fichiers visibles aux
    extensions autorisées (README, LICENSE, .github, tests… du dépôt de l'auteur ne sont ni publiés ni exécutés)."""
    result = []
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder)
        if not (path.is_file() or path.is_symlink()):
            continue
        if community and (any(part.startswith(".") or part == "__pycache__" for part in rel.parts)
                          or path.suffix.lower() not in ALLOWED_SUFFIXES):
            continue
        if not community and any(part == "__pycache__" for part in rel.parts):
            continue
        result.append(path)
    return result


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True,       # noqa: S603, S607
                            check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} a échoué")
    return result.stdout


def gitmodules() -> dict[str, str]:
    """{chemin du sous-module: url} d'après .gitmodules."""
    if not GITMODULES.is_file():
        return {}
    try:
        out = _git("config", "--file", str(GITMODULES), "--get-regexp", r"^submodule\..*\.(path|url)$")
    except RuntimeError:
        return {}
    paths: dict[str, str] = {}
    urls: dict[str, str] = {}
    for line in out.splitlines():
        key, _, value = line.partition(" ")
        name, _, field = key[len("submodule."):].rpartition(".")
        (paths if field == "path" else urls)[name] = value
    return {paths[n]: urls.get(n, "") for n in paths}


def pinned_commit(rel_path: str, ref: str = "HEAD") -> str:
    """SHA épinglé (gitlink) d'un sous-module dans `ref`."""
    try:
        parts = _git("ls-tree", ref, rel_path).split()
    except RuntimeError:
        parts = []
    if len(parts) >= 3 and parts[0] == "160000":
        return parts[2]
    if ref == "HEAD":                       # sous-module ajouté mais pas encore committé (outil « submit »)
        try:
            staged = _git("ls-files", "-s", "--", rel_path).split()
        except RuntimeError:
            return ""
        return staged[1] if len(staged) >= 2 and staged[0] == "160000" else ""
    return ""


def _community_source(folder: Path) -> tuple[str, str, list[str]]:
    """(url, commit épinglé, erreurs) d'un sous-module communautaire."""
    rel = f"marketplace/community/{folder.name}"
    errors: list[str] = []
    url = gitmodules().get(rel, "")
    if not REPO_RE.match(url):
        errors.append(f"{folder.name} : l'URL du sous-module doit être https://github.com/<auteur>/<dépôt> "
                      f"(trouvé : {url or 'rien'}).")
    pinned = pinned_commit(rel)
    if not COMMIT_RE.match(pinned):
        errors.append(f"{folder.name} : le dossier n'est pas un sous-module Git épinglé (git submodule add).")
    elif (folder / ".git").exists():
        try:
            head = _git("rev-parse", "HEAD", cwd=folder).strip()
        except RuntimeError:
            head = ""
        if head != pinned:
            errors.append(f"{folder.name} : le sous-module n'est pas extrait sur le commit épinglé "
                          f"({head[:7] or '?'} ≠ {pinned[:7]}).")
    else:
        errors.append(f"{folder.name} : sous-module non initialisé (git submodule update --init).")
    return url, pinned, errors


def validate_plugin(folder: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    community = _is_community(folder)
    if community:
        errors += _community_source(folder)[2]
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
    files = _published(folder, community)
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
    if data.get("permissions") == "auto":
        errors.append(f"{folder.name} : « permissions »: \"auto\" est réservé aux plugins locaux ; "
                      "listez-les (outil : fix-permissions).")
    elif parsed.lang == "rust" and community:
        errors.append(f"{folder.name} : un plugin Rust est du code natif sans bac à sable : niveau officiel uniquement.")
    else:
        for perm, reasons in detect.missing_permissions(folder, list(parsed.permissions), data).items():
            errors.append(f"{folder.name} : le code utilise « {perm} » sans la déclarer ({'; '.join(reasons[:2])}).")
        for perm in detect.unused_permissions(folder, list(parsed.permissions), data):
            warnings.append(f"{folder.name} : permission « {perm} » déclarée mais inutilisée.")
    with tempfile.TemporaryDirectory() as tmp:          # on n'analyse que ce qui sera réellement exécuté
        for path in files:
            if path.suffix == ".py" and not path.is_symlink():
                target = Path(tmp) / path.relative_to(folder)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        e, w = audit.scan_folder(Path(tmp), parsed.permissions)
    errors += [f"{folder.name}/{m}" for m in e]
    warnings += [f"{folder.name}/{m}" for m in w]
    if not parsed.description:
        warnings.append(f"{folder.name} : pas de description.")
    return errors, warnings


def _file_hashes(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in _published(folder, _is_community(folder)) if not p.is_symlink()}


def _revoked() -> list[dict]:
    try:
        data = json.loads(REVOKED.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def build_index() -> dict:
    entries = []
    for folder in _plugin_dirs([]):
        parsed = manifest.load(folder)
        entry = parsed.to_dict()
        entry["files"] = _file_hashes(folder)
        if _is_community(folder):
            url, commit, _ = _community_source(folder)
            entry.update(tier="community", repo=url, commit=commit)
            entry.pop("path", None)
        else:
            entry.update(tier="official", path=f"plugins/{parsed.id}")
        entries.append(entry)
    return {"schema": SCHEMA, "plugins": sorted(entries, key=lambda e: e["id"]), "revoked": _revoked()}


def _render(index: dict) -> str:
    return json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _devtools():
    sys.path.insert(0, str(CODE_ROOT / "voktora"))
    from plugins import devtools  # noqa: PLC0415 — dépend de PySide6 : seulement pour --run / sync
    return devtools


def _run_check(folder: Path) -> list[str]:
    """Exécute VRAIMENT le plugin (sous-processus jetable) : charge, événements, déchargement."""
    result = _devtools().validate(folder, run=True)
    return [f"{folder.name} : {e}" for e in result["errors"]]


def cmd_detect(args: argparse.Namespace) -> int:
    for folder in _plugin_dirs(args.plugins):
        found = detect.detect_folder(folder)
        print(f"{folder.name} : {', '.join(sorted(found.permissions)) or '(aucune permission)'}")
        for perm in sorted(found.permissions):
            for reason in found.reasons.get(perm, [])[:3]:
                print(f"    {perm:<12} {reason}")
        for warning in found.warnings:
            print(f"    ! {warning}")
    return 0


def cmd_fix_permissions(args: argparse.Namespace) -> int:
    """Écrit dans plugin.json la liste exacte des permissions détectées (et remplace « auto »)."""
    for folder in _plugin_dirs(args.plugins):
        path = folder / manifest.MANIFEST_NAME
        data = json.loads(path.read_text(encoding="utf-8"))
        found = sorted(detect.detect_folder(folder, data).permissions)
        if data.get("permissions") != found:
            data["permissions"] = found
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{folder.name} : permissions = {found}")
    return 0


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
        if getattr(args, "run", False) and not errors:
            errors += _run_check(folder)
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

Documentation de l'API : doc/plugins/
"""


def on_load(api):
    api.add_menu_action("Plugins/{name}", "Dire bonjour", lambda ctx: api.notify("Bonjour depuis {name} !"),
                        icon="mdi:hand-wave-outline")
'''

TEMPLATE_JS = """// {name} — plugin Voktora (JavaScript). Aucun code de liaison : `voktora` est global.
voktora.addMenuAction("Plugins/{name}", "Dire bonjour", ctx => voktora.notify("Bonjour depuis {name} !"));
"""

TEMPLATE_RUST_LIB = """use voktora_plugin::{{plugin, Api}};

plugin!(on_load, on_unload);

fn on_load(api: &Api) {{
    api.add_menu_action("Plugins/{name}", "Dire bonjour", |a, _ctx| a.notify("Bonjour depuis {name} !"));
}}

fn on_unload(_api: &Api) {{}}
"""

TEMPLATE_RUST_CARGO = """[package]
name = "{crate}"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
voktora-plugin = {{ path = "../voktora-sdk" }}
# Toutes les crates voulues : serde = "1", regex = "1", image = "0.25"…
"""


def cmd_new(args: argparse.Namespace) -> int:
    if not manifest.ID_RE.match(args.id):
        print("Identifiant invalide : minuscules, chiffres et tirets (ex. mon-plugin).", file=sys.stderr)
        return 2
    folder = (Path(args.dir).resolve() if args.dir else PLUGINS) / args.id
    if folder.exists():
        print(f"{folder} existe déjà.", file=sys.stderr)
        return 2
    name = args.name or args.id.replace("-", " ").title()
    entry = {"python": "main.py", "js": "main.js", "rust": "Cargo.toml"}[args.lang]
    folder.mkdir(parents=True)
    permissions = ["ui", "native"] if args.lang == "rust" else ["ui"]
    (folder / "plugin.json").write_text(json.dumps({
        "id": args.id, "name": name, "version": "1.0.0", "author": args.author, "description": "À compléter.",
        "api": manifest.API_VERSION, "lang": args.lang, "entry": entry, "permissions": permissions, "tags": [],
        "homepage": "",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.lang == "python":
        (folder / "main.py").write_text(TEMPLATE_MAIN.format(name=name), encoding="utf-8")
    elif args.lang == "js":
        (folder / "main.js").write_text(TEMPLATE_JS.format(name=name), encoding="utf-8")
    else:
        (folder / "src").mkdir()
        (folder / "Cargo.toml").write_text(TEMPLATE_RUST_CARGO.format(crate=args.id), encoding="utf-8")
        (folder / "src" / "lib.rs").write_text(TEMPLATE_RUST_LIB.format(name=name), encoding="utf-8")
    print(f"Plugin créé : {_show(folder)}\nÉtapes suivantes : modifiez-le, puis "
          f"« python tools/plugin_tool.py validate {args.id} --run » et ouvrez une Pull Request.")
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


# ── Plugins communautaires (sous-modules Git) ───────────────────────────────────────

ALLOWED_SUBMODULE_KEYS = {"path", "url"}


def _blob_gitmodules(ref: str) -> dict[str, dict[str, str]]:
    """{nom: {clé: valeur}} de .gitmodules à la révision `ref` (vide si absent)."""
    try:
        out = _git("config", "--blob", f"{ref}:.gitmodules", "--list")
    except RuntimeError:
        return {}
    result: dict[str, dict[str, str]] = {}
    for line in out.splitlines():
        key, _, value = line.partition("=")
        if not key.startswith("submodule."):
            continue
        name, _, field = key[len("submodule."):].rpartition(".")
        result.setdefault(name, {})[field] = value
    return result


def _changed_gitlinks(base: str) -> tuple[list[str], list[str]]:
    """(chemins de sous-modules communautaires modifiés, autres chemins modifiés) entre `base` et HEAD."""
    names = [n for n in _git("diff", "--name-only", "--no-renames", base, "HEAD").splitlines() if n]
    links = [n for n in names if re.fullmatch(r"marketplace/community/[^/]+", n)]
    others = [n for n in names if n not in links]
    return links, others


def check_pr(base: str) -> list[str]:
    """Règles d'une PR communautaire. Liste d'erreurs (vide = conforme)."""
    errors: list[str] = []
    links, others = _changed_gitlinks(base)
    if not links:
        return errors
    if len(links) > 1:
        errors.append("Une PR communautaire ne modifie qu'UN sous-module à la fois : " + ", ".join(links))
    extra = [n for n in others if n != ".gitmodules"]
    if extra:
        errors.append("Une PR communautaire ne doit rien modifier d'autre que le sous-module et .gitmodules "
                      "(fichiers en trop : " + ", ".join(extra[:5]) + ").")
    old_mods, new_mods = _blob_gitmodules(base), _blob_gitmodules("HEAD")
    for rel in links:
        plugin_id = rel.rsplit("/", 1)[1]
        if not manifest.ID_RE.match(plugin_id):
            errors.append(f"{plugin_id} : identifiant invalide.")
        entry = next((v for v in new_mods.values() if v.get("path") == rel), None)
        if entry is None:
            errors.append(f"{rel} : absent de .gitmodules.")
            continue
        url = entry.get("url", "")
        m = REPO_RE.match(url)
        if not m or m.group(2).endswith(".git"):
            errors.append(f"{rel} : URL « {url} » refusée — format exigé : https://github.com/<auteur>/<dépôt> "
                          f"(pas de ssh, file://, git://, identifiants, ni suffixe .git).")
        bad = sorted(set(entry) - ALLOWED_SUBMODULE_KEYS)
        if bad:
            errors.append(f"{rel} : clés .gitmodules interdites : {', '.join(bad)} (« update = !commande » exécuterait du code).")
        if not COMMIT_RE.match(pinned_commit(rel)):
            errors.append(f"{rel} : ce n'est pas un sous-module Git épinglé sur un commit.")
        old_entry = next((v for v in old_mods.values() if v.get("path") == rel), None)
        if old_entry is not None and old_entry.get("url") != url:
            errors.append(f"{rel} : changer l'URL d'un plugin déjà accepté est refusé (nouvel identifiant requis, "
                          f"ou demandez au mainteneur).")
    # Aucune autre entrée de .gitmodules ne doit avoir changé.

    for name, fields in new_mods.items():
        if fields.get("path") not in links and old_mods.get(name) != fields:
            errors.append(f".gitmodules : l'entrée « {name} » a été modifiée sans rapport avec cette PR.")
    return errors


def _read_version(folder: Path, commit: str) -> str:
    """Version déclarée dans plugin.json au commit donné (chaîne vide si inaccessible)."""
    try:
        data = json.loads(_git("show", f"{commit}:{manifest.MANIFEST_NAME}", cwd=folder))
        return str(data.get("version", ""))
    except (RuntimeError, json.JSONDecodeError):
        return ""


def cmd_check_pr(args: argparse.Namespace) -> int:
    try:
        errors = check_pr(args.base)
        links, _ = _changed_gitlinks(args.base)
    except RuntimeError as exc:
        print(f"check-pr : {exc}", file=sys.stderr)
        return 2
    for rel in links:
        folder = ROOT / rel
        old = pinned_commit(rel, args.base)
        new = pinned_commit(rel)
        if old and new and old != new and (folder / ".git").exists():
            old_v, new_v = _read_version(folder, old), _read_version(folder, new)
            if old_v and new_v and not manifest.is_newer(new_v, old_v):
                errors.append(f"{rel} : le commit épinglé a changé ({old[:7]} → {new[:7]}) mais la version "
                              f"n'augmente pas ({old_v} → {new_v}) : incrémentez « version » dans plugin.json.")
    if errors:
        print("Pull Request communautaire non conforme :")
        for message in errors:
            print(f"  ✗ {message}")
        return 1
    print("PR communautaire conforme." if links else "Aucun sous-module communautaire modifié.")
    return 0


def cmd_pr_summary(args: argparse.Namespace) -> int:
    links, _ = _changed_gitlinks(args.base)
    if not links:
        print("Aucun plugin communautaire modifié.")
        return 0
    for rel in links:
        folder = ROOT / rel
        old, new = pinned_commit(rel, args.base), pinned_commit(rel)
        url = gitmodules().get(rel, "?")
        print(f"### {rel}\n- dépôt : {url}\n- ancien commit : {old or '(nouveau plugin)'}\n- nouveau commit : {new}")
        if (folder / ".git").exists() and old and new:
            try:
                print("```\n" + _git("diff", "--stat", old, new, cwd=folder).strip() + "\n```")
                print("```\n" + _git("log", "--oneline", f"{old}..{new}", cwd=folder).strip() + "\n```")
            except RuntimeError as exc:
                print(f"(différences indisponibles : {exc})")
        print(f"Relire le code : {url}/compare/{old[:12]}...{new[:12]}" if old and new else f"Relire le code : {url}/tree/{new}")
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    """Dépôts communautaires dont le code en amont a avancé depuis l'épinglage (information, pas une alerte)."""
    moved = 0
    for folder in _dirs(COMMUNITY):
        url, pinned, _ = _community_source(folder)
        if not REPO_RE.match(url):
            continue
        try:
            head = _git("ls-remote", url, "HEAD").split()[0]
        except (RuntimeError, IndexError):
            print(f"? {folder.name} : dépôt injoignable ({url}) — supprimé ou privé ?")
            moved += 1
            continue
        if head != pinned:
            moved += 1
            print(f"≠ {folder.name} : épinglé {pinned[:7]}, amont {head[:7]} — les utilisateurs restent sur {pinned[:7]} "
                  f"tant qu'une nouvelle PR n'est pas fusionnée.")
        else:
            print(f"= {folder.name} : à jour ({pinned[:7]})")
    return 1 if (moved and args.fail) else 0


def cmd_submit(args: argparse.Namespace) -> int:
    match = REPO_RE.match(args.url)
    if not match or match.group(2).endswith(".git"):
        print("Adresse attendue : https://github.com/<vous>/<votre-plugin> (votre fork/dépôt public).", file=sys.stderr)
        return 2
    plugin_id = args.id or re.sub(r"[^a-z0-9-]+", "-", match.group(2).lower().removeprefix("voktora-")).strip("-")
    if not manifest.ID_RE.match(plugin_id):
        print(f"Identifiant « {plugin_id} » invalide : précisez --id.", file=sys.stderr)
        return 2
    target = COMMUNITY / plugin_id
    if target.exists() or (PLUGINS / plugin_id).exists():
        print(f"{plugin_id} existe déjà.", file=sys.stderr)
        return 2
    try:
        _git("submodule", "add", args.url, f"marketplace/community/{plugin_id}")
    except RuntimeError as exc:
        print(f"git submodule add a échoué : {exc}", file=sys.stderr)
        return 1
    errors, warnings = validate_plugin(target)
    for message in warnings:
        print(f"  ! {message}")
    for message in errors:
        print(f"  ✗ {message}")
    print(f"Sous-module ajouté : marketplace/community/{plugin_id}. Vérifiez, committez .gitmodules + le "
          f"sous-module, puis ouvrez la Pull Request." if not errors else "Corrigez les erreurs dans VOTRE dépôt, "
          "poussez, puis « git submodule update --remote » avant de committer.")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Outil des plugins Voktora")
    sub = parser.add_subparsers(dest="command", required=True)
    p_validate = sub.add_parser("validate", help="vérifie les plugins")
    p_validate.add_argument("plugins", nargs="*", help="identifiants (tous par défaut)")
    p_validate.add_argument("--run", action="store_true", help="exécute réellement chaque plugin (sous-processus jetable)")
    p_validate.set_defaults(func=cmd_validate)
    p_detect = sub.add_parser("detect", help="affiche les permissions détectées dans le code")
    p_detect.add_argument("plugins", nargs="*")
    p_detect.set_defaults(func=cmd_detect)
    p_fix = sub.add_parser("fix-permissions", help="écrit les permissions détectées dans plugin.json")
    p_fix.add_argument("plugins", nargs="*")
    p_fix.set_defaults(func=cmd_fix_permissions)
    p_index = sub.add_parser("build-index", help="génère marketplace/index.json")
    p_index.add_argument("--check", action="store_true", help="échoue si l'index n'est pas à jour")
    p_index.set_defaults(func=cmd_build_index)
    p_new = sub.add_parser("new", help="crée un plugin à partir d'un modèle")
    p_new.add_argument("id")
    p_new.add_argument("--name", default="")
    p_new.add_argument("--author", default="votre-pseudo")
    p_new.add_argument("--lang", choices=["python", "js", "rust"], default="python")
    p_new.add_argument("--dir", default="", help="dossier parent (par défaut marketplace/plugins)")
    p_new.set_defaults(func=cmd_new)
    p_zip = sub.add_parser("zip", help="crée une archive installable")
    p_zip.add_argument("id")
    p_zip.add_argument("--out", default="")
    p_zip.set_defaults(func=cmd_zip)
    p_check = sub.add_parser("check-pr", help="règles d'une PR communautaire (CI)")
    p_check.add_argument("--base", required=True, help="révision de référence, ex. origin/main")
    p_check.set_defaults(func=cmd_check_pr)
    p_sum = sub.add_parser("pr-summary", help="résumé des changements d'un sous-module (relecture)")
    p_sum.add_argument("--base", required=True)
    p_sum.set_defaults(func=cmd_pr_summary)
    p_drift = sub.add_parser("drift", help="dépôts communautaires modifiés en amont depuis l'épinglage")
    p_drift.add_argument("--fail", action="store_true")
    p_drift.set_defaults(func=cmd_drift)
    p_submit = sub.add_parser("submit", help="ajoute VOTRE dépôt de plugin comme sous-module")
    p_submit.add_argument("url")
    p_submit.add_argument("--id", default="")
    p_submit.set_defaults(func=cmd_submit)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
