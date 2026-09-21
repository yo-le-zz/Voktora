"""
Voktora — core.projects
Projets : création, import (ZIP / dossier / clone), renommage, suppression,
notes, dépôt GitHub, tokens, export, ordre d'affichage, mises à jour.

Un « projet » est un dossier enregistré dans config.json (liste `projects`).
Il n'y a plus de distinction instance / intent : le classement se fait par
catégories (voir core.categories) et par organisation GitHub (core.organize).
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import archive, categories, config_store, constants, crypto, drives, git_ops, organize, paths

IMPORT_MOVE = "move"   # déplace le dossier vers la racine des projets (défaut)
IMPORT_COPY = "copy"   # copie le dossier ; la source reste en place
IMPORT_LINK = "link"   # enregistre le dossier là où il se trouve, sans le toucher
IMPORT_MODES = (IMPORT_MOVE, IMPORT_COPY, IMPORT_LINK)


# ──────────────────────────────────────────────
# LECTURE / ENREGISTREMENT
# ──────────────────────────────────────────────

def list_projects() -> list:
    return config_store._load_config().get("projects", [])


def get_project(path: Path | str) -> dict | None:
    return config_store._find_entry(config_store._load_config(), path)


def register_project(path: Path | str, drive: str = "", **fields) -> dict:
    """Enregistre un dossier existant comme projet et retourne son entrée.

    `category` (facultative) est créée si elle n'existe pas encore.
    """
    path = Path(path)
    cfg = config_store._load_config()
    if config_store._find_entry(cfg, path) is not None:
        raise ValueError(f"« {path} » est déjà enregistré comme projet.")
    category = fields.pop("category", None)
    canonical = categories.ensure_category(category)["name"] if category and str(category).strip() else None
    # ensure_category a pu sauvegarder la config : on repart de l'instance en cache.
    cfg = config_store._load_config()
    entry: dict = {
        "name": fields.pop("name", None) or path.name,
        "path": str(path),
        "drive": drive,
        "created": datetime.now().isoformat(),
        "category": canonical,
    }
    entry.update(fields)
    config_store.normalize_entry(entry)
    cfg["projects"].append(entry)
    config_store._save_config(cfg)
    return entry


def update_project(path: Path | str, **fields) -> bool:
    """Met à jour des champs d'un projet (couleur, emoji, statut, tags…)."""
    cfg = config_store._load_config()
    if not config_store._update_entry(cfg, path, **fields):
        return False
    config_store._save_config(cfg)
    return True


def create_project(drive: str, name: str, category: str | None = None,
                   git_init: bool = False, github_repo: str | None = None) -> Path:
    name = name.strip()
    paths.validate_name(name)
    root = drives.get_projects_root(drive)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if path.exists():
        raise FileExistsError(f"Le projet « {name} » existe déjà ({path}).")
    path.mkdir(parents=True, exist_ok=True)
    if git_init:
        git_ops.git_init(path)
    fields: dict = {"category": category}
    if github_repo and github_repo.strip():
        fields["github_repo"] = git_ops.validate_clone_url(github_repo)
    register_project(path, drive, name=name, **fields)
    return path


def forget_project(path: Path | str) -> None:
    """Retire un projet de Voktora SANS toucher à son dossier."""
    cfg = config_store._load_config()
    target = str(path)
    cfg["projects"] = [e for e in cfg["projects"] if e["path"] != target]
    config_store._save_config(cfg)
    constants._SESSION_VAULT.pop(target, None)


def delete_project(path: Path, on_progress: archive.ProgressCallback | None = None,
                   cancel: archive.CancelCheck | None = None) -> None:
    """Supprime le dossier du projet ET son enregistrement.

    Si le dossier ne peut pas être entièrement supprimé, une ArchiveError est
    levée et le projet reste enregistré (rien n'est « oublié » à moitié).
    """
    archive.delete_tree(Path(path), on_progress, cancel)
    forget_project(path)


def rename_project(path: Path, new_name: str) -> Path:
    paths.validate_name(new_name)
    new_path = path.parent / new_name
    if new_path.exists():
        raise FileExistsError(f"Un dossier « {new_name} » existe déjà.")
    path.rename(new_path)
    cfg = config_store._load_config()
    entry = config_store._find_entry(cfg, path)
    if entry:
        entry["path"] = str(new_path)
        entry["name"] = new_name
    config_store._save_config(cfg)
    return new_path


def find_readme(folder: Path) -> Path | None:
    """Cherche un fichier README (n'importe quelle casse) à la racine du
    dossier de projet. Renvoie le premier trouvé par ordre de préférence
    (.md > .markdown > .txt > sans extension), ou None."""
    folder = Path(folder)
    if not folder.is_dir():
        return None
    by_lower_name = {p.name.lower(): p for p in folder.iterdir() if p.is_file()}
    for candidate in ("readme.md", "readme.markdown", "readme.txt", "readme"):
        if candidate in by_lower_name:
            return by_lower_name[candidate]
    return None


def reorder_projects(ordered_paths: list[str]) -> None:
    """Persiste l'ordre manuel des projets (glisser-déposer).

    Les projets absents de `ordered_paths` sont conservés à leur place relative,
    après les projets ordonnés.
    """
    cfg = config_store._load_config()
    by_path = {e["path"]: e for e in cfg["projects"]}
    reordered = [by_path[p] for p in dict.fromkeys(ordered_paths) if p in by_path]
    seen = {e["path"] for e in reordered}
    reordered += [e for e in cfg["projects"] if e["path"] not in seen]
    cfg["projects"] = reordered
    config_store._save_config(cfg)


# ──────────────────────────────────────────────
# NOTE / DÉPÔT GITHUB / TOKEN
# ──────────────────────────────────────────────

def _get(path: Path, key: str, default=""):
    entry = config_store._find_entry(config_store._load_config(), path)
    return (entry.get(key) or default) if entry else default


def _set(path: Path, **fields) -> None:
    cfg = config_store._load_config()
    config_store._update_entry(cfg, path, **fields)
    config_store._save_config(cfg)


def get_project_note(path: Path) -> str:
    return _get(path, "note")


def set_project_note(path: Path, note: str) -> None:
    _set(path, note=note)


def get_project_repo(path: Path) -> str:
    return _get(path, "github_repo")


def set_project_repo(path: Path, url: str) -> None:
    _set(path, github_repo=url)


def get_project_branch(path: Path) -> str:
    return _get(path, "github_branch", "main")


def set_project_branch(path: Path, branch: str) -> None:
    _set(path, github_branch=branch)


def get_project_branches(path: Path) -> list:
    return _get(path, "github_branches", ["main"])


def set_project_branches(path: Path, branches: list) -> None:
    _set(path, github_branches=branches)


def set_project_token(path: Path, token: str, password: str = "") -> None:
    if password:
        stored    = crypto.token_encrypt(token, password)
        protected = True
        constants._SESSION_VAULT[str(path)] = token
    else:
        stored    = token
        protected = False
    _set(path, github_token=stored, github_token_protected=protected)


def get_project_token_raw(path: Path) -> str:
    return _get(path, "github_token")


def is_token_protected(path: Path) -> bool:
    entry = config_store._find_entry(config_store._load_config(), path)
    return bool(entry.get("github_token_protected", False)) if entry else False


def get_project_token(path: Path, password: str = "") -> str:
    vault_key = str(path)
    if vault_key in constants._SESSION_VAULT:
        return constants._SESSION_VAULT[vault_key]
    raw = get_project_token_raw(path)
    if not raw:
        return ""
    if is_token_protected(path):
        if not password:
            return ""
        decrypted = crypto.token_decrypt(raw, password)
        if decrypted:
            constants._SESSION_VAULT[vault_key] = decrypted
        return decrypted
    return raw


def vault_session_store(path: Path, token: str) -> None:
    """Stocke un token déchiffré en mémoire (session uniquement, non persisté)."""
    constants._SESSION_VAULT[str(path)] = token


def vault_session_clear(path: Path) -> None:
    """Supprime un token du cache de session."""
    constants._SESSION_VAULT.pop(str(path), None)


# ──────────────────────────────────────────────
# MISES À JOUR — Vérification GitHub Releases
# ──────────────────────────────────────────────

def _version_gt(v1: str, v2: str) -> bool:
    """True si v1 > v2 (comparaison sémantique X.Y.Z)."""
    def _parse(v: str) -> tuple:
        try:
            return tuple(int(x) for x in v.strip().lstrip("v").split("."))
        except ValueError:
            return (0,)
    return _parse(v1) > _parse(v2)


def check_for_update() -> tuple[bool, str, str]:
    """
    Interroge l'API GitHub Releases pour vérifier si une nouvelle version est disponible.
    Retourne (update_available: bool, latest_version: str, release_url: str).
    Ne lève jamais d'exception — toujours sûr à appeler depuis un thread.
    """
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/yo-le-zz/Voktora/releases/latest",
            headers={
                "User-Agent": f"{constants.APP_NAME}/{constants.APP_VERSION}",
                "Accept":     "application/vnd.github+json",
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest  = data.get("tag_name", "").lstrip("v").strip()
        rel_url = data.get("html_url",
                           "https://github.com/yo-le-zz/Voktora/releases/latest")
        if latest and _version_gt(latest, constants.APP_VERSION):
            return True, latest, rel_url
        return False, latest, rel_url
    except Exception:
        return False, "", ""


# ──────────────────────────────────────────────
# CLONE DANS UN PROJET EXISTANT
# ──────────────────────────────────────────────

def clone_into_existing(project_path: Path, repo_url: str,
                         token: str = "", branch: str = "main") -> str:
    """
    Clone un repo GitHub dans un projet/dossier existant.
    Clone dans un dossier temporaire puis copie les fichiers (sans `.git`, pour
    conserver l'historique du projet cible). Le dossier `project_path` doit déjà exister.

    Returns: Sortie de la commande git.
    """
    if not project_path.exists():
        raise FileNotFoundError(f"Le dossier projet n'existe pas : {project_path}")

    tmp_dir = project_path.parent / f"_voktora_tmp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        out = git_ops.git_clone(repo_url, tmp_dir, token=token, branch=branch)
        for item in tmp_dir.iterdir():
            if item.name == ".git":
                continue
            dst = project_path / item.name
            if item.is_dir():
                shutil.copytree(str(item), str(dst), dirs_exist_ok=True)
            else:
                shutil.copy2(str(item), str(dst))
        return out
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def clone_project(repo_url: str, drive: str = "", name: str | None = None,
                  branch: str = "", token: str = "", category: str | None = None,
                  on_output: Callable[[str], None] | None = None,
                  cancel: Callable[[], bool] | None = None) -> Path:
    """Clone un dépôt dans la racine des projets et l'enregistre.

    Sans catégorie explicite, le projet garde simplement le propriétaire du
    dépôt comme « organisation GitHub » (regroupement automatique).
    """
    clean_url = git_ops.validate_clone_url(repo_url)
    project_name = (name or organize.repo_name_from_url(clean_url)).strip()
    paths.validate_name(project_name)
    target = drives.get_projects_root(drive) / project_name
    if target.exists():
        raise FileExistsError(f"Le projet « {project_name} » existe déjà ({target}).")
    git_ops.git_clone(clean_url, target, token=token, branch=branch, on_output=on_output, cancel=cancel)
    _url, head_branch = organize.read_git_origin(target)
    used_branch = branch or head_branch or "main"
    register_project(
        target, drive, name=project_name, category=category, github_repo=clean_url,
        github_branch=used_branch, github_branches=[used_branch],
        note=f"Cloné depuis {clean_url}",
    )
    return target


# ──────────────────────────────────────────────
# EXPORT (ZIP)
# ──────────────────────────────────────────────

def export_to_zip(folder_path: Path, output_dir: Path | None = None,
                  on_progress: archive.ProgressCallback | None = None,
                  cancel: archive.CancelCheck | None = None) -> Path:
    return archive.export_folder_to_zip(folder_path, output_dir, on_progress, cancel)


def export_all_to_zip(on_progress: archive.ProgressCallback | None = None,
                      cancel: archive.CancelCheck | None = None) -> str:
    """Exporte tous les projets et la configuration dans un ZIP horodaté.

    La configuration exportée ne contient ni le compte GitHub, ni le coffre,
    ni les tokens de projet : l'archive peut être partagée sans exposer de secret.
    """
    cfg = config_store._load_config()
    folders = [Path(e["path"]) for e in cfg.get("projects", []) if Path(e["path"]).is_dir()]
    total = sum(archive._tree_size(f)[1] for f in folders)
    tracker = archive.ProgressTracker(total, on_progress)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    public_cfg = {k: v for k, v in cfg.items() if k not in ("github_account", "vault")}
    public_cfg["projects"] = [
        {**e, "github_token": "", "github_token_protected": False} for e in cfg.get("projects", [])
    ]

    def _write(zf) -> None:
        used: set[str] = set()
        for folder in folders:
            # Deux projets de même nom (dossiers différents) ne doivent pas se mélanger.
            prefix, n = f"projects/{folder.name}", 2
            while prefix in used:
                prefix, n = f"projects/{folder.name}_{n}", n + 1
            used.add(prefix)
            archive.add_tree_to_zip(zf, folder, prefix, tracker, cancel)
        zf.writestr("config.json", json.dumps(public_cfg, indent=2, ensure_ascii=False))
        zf.writestr("export_info.txt", f"Voktora export — {timestamp}\nVersion : {constants.APP_VERSION}\n")

    result = archive.write_zip_atomically(paths.get_backups_dir() / f"voktora_export_{timestamp}.zip", _write)
    tracker.finish(result.name)
    return str(result)


# ──────────────────────────────────────────────
# IMPORT (ZIP / DOSSIER)
# ──────────────────────────────────────────────

def _register_imported(path: Path, drive: str, name: str, category: str | None) -> Path:
    """Enregistre un dossier importé ; reprend le dépôt GitHub s'il en a un."""
    origin_url, branch = organize.read_git_origin(path)
    fields: dict = {"name": name, "category": category}
    if origin_url:
        fields.update(github_repo=origin_url, github_branch=branch or "main",
                      github_branches=[branch or "main"])
    register_project(path, drive, **fields)
    return path


def import_from_zip(zip_path: Path, drive: str = "", name: str | None = None,
                    category: str | None = None,
                    on_progress: archive.ProgressCallback | None = None,
                    cancel: archive.CancelCheck | None = None) -> Path:
    """Importe une archive ZIP comme nouveau projet (voir archive.extract_zip)."""
    root = drives.get_projects_root(drive)
    extracted = archive.extract_zip(Path(zip_path), root, name, on_progress, cancel)
    try:
        return _register_imported(extracted, drive, extracted.name, category)
    except Exception:
        # Enregistrement impossible : ne pas laisser un dossier orphelin fraîchement extrait.
        shutil.rmtree(extracted, ignore_errors=True)
        raise


def import_from_folder(folder_path: Path, drive: str = "", mode: str = IMPORT_MOVE,
                       name: str | None = None, category: str | None = None,
                       on_progress: archive.ProgressCallback | None = None,
                       cancel: archive.CancelCheck | None = None) -> Path:
    """Importe un dossier existant (non compressé) comme projet.

    mode :
      IMPORT_MOVE (défaut) — déplace le dossier vers la racine des projets ;
      IMPORT_COPY          — le copie, la source reste intacte ;
      IMPORT_LINK          — l'enregistre sur place, sans rien déplacer.
    """
    folder = Path(folder_path)
    if mode not in IMPORT_MODES:
        raise ValueError(f"Mode d'import inconnu : {mode!r}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Introuvable ou n'est pas un dossier : {folder}")
    project_name = (name or folder.name).strip()
    paths.validate_name(project_name)

    if mode == IMPORT_LINK:
        return _register_imported(folder, drive, project_name, category)

    root = drives.get_projects_root(drive)
    dest = root / project_name
    if folder.resolve().parent == root.resolve():
        raise ValueError("Ce dossier est déjà dans le dossier des projets : utilisez « Ajouter sur place ».")
    if dest.exists():
        raise FileExistsError(f"Un projet nommé « {project_name} » existe déjà dans {root}.")

    if mode == IMPORT_MOVE:
        archive.move_tree(folder, dest, on_progress, cancel)
    else:
        archive.copy_tree(folder, dest, on_progress, cancel)
    try:
        return _register_imported(dest, drive, project_name, category)
    except Exception:
        # Copie : on peut défaire proprement. Déplacement : le dossier est déjà
        # chez sa destination, on le laisse plutôt que de risquer de le perdre.
        if mode == IMPORT_COPY:
            shutil.rmtree(dest, ignore_errors=True)
        raise

