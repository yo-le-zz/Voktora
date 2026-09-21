"""
Voktora — core.projects
Fragment de core.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from . import config_store, constants, crypto, drives, git_ops, paths

# INSTANCES
# ──────────────────────────────────────────────

def list_instances() -> list:
    return config_store._load_config().get("instances", [])


def create_instance(drive: str, name: str) -> Path:
    name = name.strip()
    paths.validate_name(name)
    root = drives.get_instances_root(drive)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if path.exists():
        raise FileExistsError(f"L'instance « {name} » existe déjà ({path}).")
    path.mkdir(parents=True, exist_ok=True)
    cfg = config_store._load_config()
    cfg["instances"].append({
        "name": name, "path": str(path), "drive": drive,
        "created": datetime.now().isoformat(),
        "github_repo": None, "github_branch": "main",
        "github_branches": ["main"], "github_token": "",
        "github_token_protected": False, "note": "",
        "status": constants.DEFAULT_PROJECT_STATUS, "color": None,
        "emoji": None, "category": None, "language": None,
    })
    config_store._save_config(cfg)
    return path


def delete_instance(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    cfg = config_store._load_config()
    cfg["instances"] = [e for e in cfg["instances"] if e["path"] != str(path)]
    config_store._save_config(cfg)


def rename_instance(path: Path, new_name: str) -> Path:
    paths.validate_name(new_name)
    new_path = path.parent / new_name
    if new_path.exists():
        raise FileExistsError(f"Un dossier « {new_name} » existe déjà.")
    path.rename(new_path)
    cfg = config_store._load_config()
    entry = config_store._find_entry(cfg, "instances", path)
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


def rename_intent(path: Path, new_name: str) -> Path:
    paths.validate_name(new_name)
    new_path = path.parent / new_name
    if new_path.exists():
        raise FileExistsError(f"Un dossier « {new_name} » existe déjà.")
    path.rename(new_path)
    cfg = config_store._load_config()
    entry = config_store._find_entry(cfg, "intents", path)
    if entry:
        entry["path"] = str(new_path)
        entry["name"] = new_name
    config_store._save_config(cfg)
    return new_path


def get_instance_note(path: Path) -> str:
    cfg = config_store._load_config()
    entry = config_store._find_entry(cfg, "instances", path)
    return (entry.get("note") or "") if entry else ""


def set_instance_note(path: Path, note: str) -> None:
    cfg = config_store._load_config()
    config_store._update_entry(cfg, "instances", path, note=note)
    config_store._save_config(cfg)


def get_instance_repo(path: Path) -> str:
    cfg = config_store._load_config()
    entry = config_store._find_entry(cfg, "instances", path)
    return (entry.get("github_repo") or "") if entry else ""


def set_instance_repo(path: Path, url: str) -> None:
    cfg = config_store._load_config()
    config_store._update_entry(cfg, "instances", path, github_repo=url)
    config_store._save_config(cfg)


def get_instance_branch(path: Path) -> str:
    cfg = config_store._load_config()
    entry = config_store._find_entry(cfg, "instances", path)
    return (entry.get("github_branch") or "main") if entry else "main"


def set_instance_branch(path: Path, branch: str) -> None:
    cfg = config_store._load_config()
    config_store._update_entry(cfg, "instances", path, github_branch=branch)
    config_store._save_config(cfg)


def get_instance_branches(path: Path) -> list:
    cfg = config_store._load_config()
    entry = config_store._find_entry(cfg, "instances", path)
    return (entry.get("github_branches") or ["main"]) if entry else ["main"]


def set_instance_branches(path: Path, branches: list) -> None:
    cfg = config_store._load_config()
    config_store._update_entry(cfg, "instances", path, github_branches=branches)
    config_store._save_config(cfg)


def set_instance_token(path: Path, token: str, password: str = "") -> None:
    if password:
        stored    = crypto.token_encrypt(token, password)
        protected = True
        constants._SESSION_VAULT[str(path)] = token
    else:
        stored    = token
        protected = False
    cfg = config_store._load_config()
    config_store._update_entry(cfg, "instances", path, github_token=stored, github_token_protected=protected)
    config_store._save_config(cfg)


def get_instance_token_raw(path: Path) -> str:
    cfg = config_store._load_config()
    entry = config_store._find_entry(cfg, "instances", path)
    return (entry.get("github_token") or "") if entry else ""


def is_token_protected(path: Path) -> bool:
    cfg = config_store._load_config()
    entry = config_store._find_entry(cfg, "instances", path)
    return bool(entry.get("github_token_protected", False)) if entry else False


def get_instance_token(path: Path, password: str = "") -> str:
    vault_key = str(path)
    if vault_key in constants._SESSION_VAULT:
        return constants._SESSION_VAULT[vault_key]
    raw = get_instance_token_raw(path)
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
# ORDRE DES PROJETS — persistance drag & drop / tri
# ──────────────────────────────────────────────

def reorder_entries(kind: str, ordered_paths: list[str]) -> None:
    """
    Persiste l'ordre des instances ou intents après un glisser-déposer.
    kind        : "instance" ou "intent"
    ordered_paths : chemins dans le nouvel ordre.
    Les entrées absentes de la liste sont ajoutées à la fin (sécurité).
    """
    key = f"{kind}s"          # "instances" | "intents"
    cfg = config_store._load_config()
    entries       = cfg.get(key, [])
    path_to_entry = {e["path"]: e for e in entries}
    reordered: list[dict] = []
    for p in ordered_paths:
        if p in path_to_entry:
            reordered.append(path_to_entry[p])
    seen = set(ordered_paths)
    for e in entries:
        if e["path"] not in seen:
            reordered.append(e)
    cfg[key] = reordered
    config_store._save_config(cfg)


# ──────────────────────────────────────────────
# TRANSFERT Instance ↔ Intent (v1.0.1)
# ──────────────────────────────────────────────

def transfer_project(path: Path, from_kind: str, to_kind: str) -> Path:
    """
    Transfère un projet d'un type à l'autre (instance → intent ou intent → instance).
    Déplace le dossier et met à jour la configuration.

    Args:
        path:      Chemin du projet à transférer.
        from_kind: "instance" ou "intent".
        to_kind:   "instance" ou "intent".

    Returns:
        Nouveau chemin du projet après déplacement.

    Raises:
        ValueError:      Si from_kind == to_kind ou types invalides.
        FileExistsError: Si un projet du même nom existe déjà dans la destination.
    """
    if from_kind == to_kind:
        raise ValueError("Le projet est déjà de ce type.")
    if from_kind not in ("instance", "intent") or to_kind not in ("instance", "intent"):
        raise ValueError("Types invalides (attendu : 'instance' ou 'intent').")

    cfg = config_store._load_config()
    from_key = f"{from_kind}s"
    to_key   = f"{to_kind}s"

    # Retrouver l'entrée source
    src_entry = config_store._find_entry(cfg, from_key, path)
    if src_entry is None:
        raise FileNotFoundError(f"Projet introuvable dans la configuration : {path}")

    # Calculer le chemin de destination
    drive = src_entry.get("drive", "")
    name  = src_entry.get("name", path.name)

    dest_root = drives.get_instances_root(drive) if to_kind == "instance" else drives.get_intents_root(drive)

    dest_root.mkdir(parents=True, exist_ok=True)
    new_path = dest_root / name

    if new_path.exists():
        raise FileExistsError(
            f"Un projet nommé « {name} » existe déjà dans les {to_kind}s."
        )

    # Déplacer physiquement le dossier
    shutil.move(str(path), str(new_path))

    # Créer la nouvelle entrée
    new_entry = dict(src_entry)
    new_entry["path"] = str(new_path)
    new_entry["drive"] = drive

    # Les intents n'ont pas les champs GitHub — nettoyer si passage vers intent
    if to_kind == "intent":
        for field in ["github_repo", "github_branch", "github_branches",
                       "github_token", "github_token_protected"]:
            new_entry.pop(field, None)
    else:
        # Passage vers instance : ajouter les champs GitHub manquants
        new_entry.setdefault("github_repo", None)
        new_entry.setdefault("github_branch", "main")
        new_entry.setdefault("github_branches", ["main"])
        new_entry.setdefault("github_token", "")
        new_entry.setdefault("github_token_protected", False)

    # Mettre à jour la configuration : supprimer de la source, ajouter dans la dest
    cfg[from_key] = [e for e in cfg[from_key] if e["path"] != str(path)]
    cfg[to_key].append(new_entry)
    config_store._save_config(cfg)

    return new_path


# ──────────────────────────────────────────────
# CLONE DANS UN PROJET EXISTANT (v1.0.1)
# ──────────────────────────────────────────────

def clone_into_existing(project_path: Path, repo_url: str,
                         token: str = "", branch: str = "main") -> str:
    """
    Clone un repo GitHub dans un projet/dossier existant.
    Utilise `git clone --no-checkout` puis copie les fichiers.
    Le dossier `project_path` doit déjà exister.

    Returns: Sortie de la commande git.
    """
    if not project_path.exists():
        raise FileNotFoundError(f"Le dossier projet n'existe pas : {project_path}")

    # Construire l'URL avec token si nécessaire
    clone_url = repo_url
    if token and repo_url.startswith("https://"):
        clone_url = "https://" + token + "@" + repo_url[len("https://"):]

    # Clone dans un dossier temporaire
    tmp_dir = project_path.parent / f"_voktora_tmp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        out = git_ops._run_git(["clone", "--branch", branch, clone_url, str(tmp_dir)],
                       project_path.parent)
        # Copier le contenu, sauf .git (on conserve le .git existant du
        # projet cible s'il y en a un, pour ne pas écraser son historique).
        for item in tmp_dir.iterdir():
            if item.name == ".git":
                continue
            dst = project_path / item.name
            if item.is_dir():
                if dst.exists():
                    shutil.copytree(str(item), str(dst), dirs_exist_ok=True)
                else:
                    shutil.copytree(str(item), str(dst))
            else:
                shutil.copy2(str(item), str(dst))
        return out
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ──────────────────────────────────────────────
# INTENTS
# ──────────────────────────────────────────────

def list_intents() -> list:
    return config_store._load_config().get("intents", [])


def create_intent(drive: str, name: str) -> Path:
    name = name.strip()
    paths.validate_name(name)
    root = drives.get_intents_root(drive)
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    if path.exists():
        raise FileExistsError(f"L'intent « {name} » existe déjà ({path}).")
    path.mkdir(parents=True, exist_ok=True)
    cfg = config_store._load_config()
    cfg["intents"].append({
        "name": name, "path": str(path), "drive": drive,
        "created": datetime.now().isoformat(), "note": "",
        "color": None, "emoji": None, "category": None, "language": None,
    })
    config_store._save_config(cfg)
    return path


def delete_intent(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    cfg = config_store._load_config()
    cfg["intents"] = [e for e in cfg["intents"] if e["path"] != str(path)]
    config_store._save_config(cfg)


def get_intent_note(path: Path) -> str:
    cfg = config_store._load_config()
    entry = config_store._find_entry(cfg, "intents", path)
    return (entry.get("note") or "") if entry else ""


def set_intent_note(path: Path, note: str) -> None:
    cfg = config_store._load_config()
    config_store._update_entry(cfg, "intents", path, note=note)
    config_store._save_config(cfg)


# ──────────────────────────────────────────────
# EXPORT / IMPORT (ZIP)
# ──────────────────────────────────────────────

def export_to_zip(folder_path: Path, output_dir: Path | None = None) -> Path:
    if output_dir is None:
        output_dir = paths.get_backups_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path  = output_dir / f"{folder_path.name}_{timestamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in folder_path.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(folder_path.parent))
    return zip_path


def import_from_zip(zip_path: Path, drive: str, kind: str) -> Path:
    root = drives.get_instances_root(drive) if kind == "instance" else drives.get_intents_root(drive)
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        top_dirs    = {Path(n).parts[0] for n in zf.namelist() if n.strip("/")}
        folder_name = next(iter(top_dirs)) if top_dirs else zip_path.stem
        zf.extractall(root)
    extracted_path = root / folder_name
    cfg = config_store._load_config()
    key = "instances" if kind == "instance" else "intents"
    existing_paths = {e["path"] for e in cfg[key]}
    if str(extracted_path) not in existing_paths:
        entry: dict = {
            "name": folder_name, "path": str(extracted_path),
            "drive": drive, "created": datetime.now().isoformat(), "note": "",
        }
        if kind == "instance":
            entry.update({
                "github_repo": None, "github_branch": "main",
                "github_branches": ["main"], "github_token": "",
                "github_token_protected": False,
            })
        cfg[key].append(entry)
        config_store._save_config(cfg)
    return extracted_path


def import_from_folder(folder_path: Path, drive: str, kind: str) -> Path:
    """Importe un dossier existant (non compressé) comme instance ou intent.

    Copie le dossier tel quel vers la racine Instances/Intents du disque
    choisi (le dossier source n'est jamais modifié ni supprimé — même
    comportement non destructif que import_from_zip) puis l'enregistre
    dans la configuration.
    """
    folder_path = Path(folder_path)
    if not folder_path.is_dir():
        raise NotADirectoryError(f"Introuvable ou n'est pas un dossier : {folder_path}")

    root = drives.get_instances_root(drive) if kind == "instance" else drives.get_intents_root(drive)
    root.mkdir(parents=True, exist_ok=True)

    folder_name = folder_path.name
    dest_path   = root / folder_name
    if dest_path.exists():
        raise FileExistsError(
            f"Un projet nommé « {folder_name} » existe déjà dans les {kind}s."
        )
    if dest_path.resolve() == folder_path.resolve() or root.resolve() in folder_path.resolve().parents:
        raise ValueError("Le dossier source est déjà à l'intérieur de la racine de destination.")

    shutil.copytree(folder_path, dest_path)

    cfg = config_store._load_config()
    key = "instances" if kind == "instance" else "intents"
    existing_paths = {e["path"] for e in cfg[key]}
    if str(dest_path) not in existing_paths:
        entry: dict = {
            "name": folder_name, "path": str(dest_path),
            "drive": drive, "created": datetime.now().isoformat(), "note": "",
        }
        if kind == "instance":
            entry.update({
                "github_repo": None, "github_branch": "main",
                "github_branches": ["main"], "github_token": "",
                "github_token_protected": False,
            })
        cfg[key].append(entry)
        config_store._save_config(cfg)
    return dest_path


