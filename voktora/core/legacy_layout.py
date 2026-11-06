"""
Voktora — core.legacy_layout
Fin de l'ancienne séparation « Instances » / « Intents » sur le disque.

Avant la 1.0.3, les projets vivaient dans deux dossiers distincts
(`<Voktora>/Instances/<projet>` et `<Voktora>/Intents/<projet>`). Depuis, il n'y a plus
qu'une racine (`<Voktora>/Projects`). Au démarrage, si un de ces anciens dossiers existe
encore, son contenu est déplacé dans la racine des projets, la configuration est mise à
jour (chemins des projets enregistrés, racine personnalisée), puis les dossiers vides sont
supprimés.

Garanties :
  • rien n'est écrasé : en cas de nom déjà pris, le dossier déplacé reçoit « (2) », « (3) »… ;
  • la détection (`plan_migration`) est en lecture seule et peu coûteuse (quelques `stat`) ;
  • un déplacement sur le même volume est un simple renommage ; entre deux volumes, la source
    n'est supprimée qu'après copie complète (voir archive.move_tree) ;
  • une annulation ou une erreur laisse chaque projet soit à son ancien emplacement, soit au
    nouveau, et la configuration est enregistrée après CHAQUE déplacement : jamais d'entrée qui
    pointe vers un dossier disparu.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import archive, config_store, constants, drives

LEGACY_DIR_NAMES = frozenset({"instances", "intents"})

ProgressCallback = Callable[[int, int, str], None]


def is_legacy_dir_name(name: str) -> bool:
    return name.strip().lower() in LEGACY_DIR_NAMES


@dataclass
class LegacyMove:
    source: Path
    target: Path
    registered: bool


@dataclass
class LegacyPlan:
    destination: Path
    legacy_dirs: list[Path] = field(default_factory=list)
    moves: list[LegacyMove] = field(default_factory=list)
    set_storage_root: bool = False   # la racine personnalisée était elle-même un ancien dossier

    @property
    def is_empty(self) -> bool:
        return not self.legacy_dirs


@dataclass
class LegacyResult:
    moved: list[LegacyMove] = field(default_factory=list)
    removed_dirs: list[Path] = field(default_factory=list)
    leftovers: list[Path] = field(default_factory=list)   # dossiers anciens non vidés (fichiers isolés…)
    log: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# DÉTECTION (lecture seule)
# ──────────────────────────────────────────────

def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir() and not path.is_symlink()
    except OSError:
        return False


def _legacy_children(base: Path) -> list[Path]:
    """Sous-dossiers « Instances » / « Intents » (insensible à la casse) directement sous `base`."""
    try:
        return [child for child in base.iterdir()
                if is_legacy_dir_name(child.name) and _safe_is_dir(child)]
    except OSError:
        return []


def _candidate_containers(root: Path) -> list[Path]:
    """Dossiers « Voktora » susceptibles de contenir encore l'ancienne arborescence."""
    containers: list[Path] = [root, root.parent, Path.home() / constants.CONTAINER_NAME]
    try:
        locations = drives.get_available_drives()
    except OSError:
        locations = []
    for location in locations:
        base = f"{location}\\" if constants.IS_WINDOWS else location
        containers.append(Path(base) / constants.CONTAINER_NAME)
    return containers


def plan_migration(cfg: dict | None = None) -> LegacyPlan | None:
    """Prépare la migration, ou renvoie None s'il ne reste aucun ancien dossier."""
    cfg = cfg if cfg is not None else config_store._load_config()
    configured = (cfg.get("storage") or {}).get("projects_root")
    root = Path(configured) if configured else drives.get_projects_root()

    set_storage_root = bool(configured) and is_legacy_dir_name(root.name)
    destination = root.parent if is_legacy_dir_name(root.name) else root

    legacy_dirs: list[Path] = []

    def _add(directory: Path) -> None:
        with contextlib.suppress(OSError):
            resolved = directory.resolve()
            if resolved != destination.resolve() and all(resolved != d.resolve() for d in legacy_dirs):
                legacy_dirs.append(directory)

    if is_legacy_dir_name(root.name) and _safe_is_dir(root):
        _add(root)
    for container in _candidate_containers(root):
        for child in _legacy_children(container):
            _add(child)
    for entry in cfg.get("projects", []):
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        parent = Path(entry["path"]).parent
        if is_legacy_dir_name(parent.name) and _safe_is_dir(parent):
            _add(parent)

    if not legacy_dirs:
        return None

    plan = LegacyPlan(destination=destination, legacy_dirs=legacy_dirs, set_storage_root=set_storage_root)
    taken: set[str] = set()
    with contextlib.suppress(OSError):
        taken = {c.name.lower() for c in destination.iterdir()} if destination.exists() else set()

    for legacy in legacy_dirs:
        try:
            children = sorted((c for c in legacy.iterdir() if _safe_is_dir(c)), key=lambda c: c.name.lower())
        except OSError:
            continue
        for child in children:
            target_name = _unique_name(child.name, taken)
            taken.add(target_name.lower())
            registered = config_store._find_entry(cfg, child) is not None
            plan.moves.append(LegacyMove(child, destination / target_name, registered))
    return plan


def _unique_name(name: str, taken: set[str]) -> str:
    if name.lower() not in taken:
        return name
    index = 2
    while f"{name} ({index})".lower() in taken:
        index += 1
    return f"{name} ({index})"


def needs_migration() -> bool:
    """Vrai s'il reste au moins un ancien dossier « Instances » / « Intents »."""
    try:
        return plan_migration() is not None
    except (OSError, constants.ConfigCorruptedError):
        return False


# ──────────────────────────────────────────────
# APPLICATION
# ──────────────────────────────────────────────

def apply_migration(plan: LegacyPlan, on_progress: ProgressCallback | None = None,
                    cancel: Callable[[], bool] | None = None) -> LegacyResult:
    """Exécute le plan. Lève OperationCancelled si `cancel()` devient vrai entre deux projets."""
    result = LegacyResult()
    total = max(len(plan.moves), 1) * 1000

    def report(done_units: int, label: str) -> None:
        if on_progress:
            on_progress(done_units, total, label)

    plan.destination.mkdir(parents=True, exist_ok=True)
    for index, move in enumerate(plan.moves):
        if cancel and cancel():
            raise constants.OperationCancelled("Migration annulée.")
        report(index * 1000, move.source.name)

        def inner(done: int, size: int, _label: str = "", _base: int = index * 1000,
                  _name: str = move.source.name) -> None:
            if size:
                report(_base + int(1000 * min(done, size) / size), _name)

        try:
            archive.move_tree(move.source, move.target, inner, cancel)
        except constants.OperationCancelled:
            raise
        except (OSError, ValueError) as exc:
            result.log.append(f"❌ {move.source} → {move.target} : {exc}")
            continue
        _repoint_entry(move.source, move.target)
        result.moved.append(move)
        result.log.append(f"✅ {move.source} → {move.target}")

    for legacy in plan.legacy_dirs:
        try:
            legacy.rmdir()          # ne supprime que si le dossier est vide
            result.removed_dirs.append(legacy)
        except OSError:
            if legacy.exists():
                result.leftovers.append(legacy)
                result.log.append(f"⚠ {legacy} n'est pas vide (fichiers isolés) : conservé.")

    if plan.set_storage_root:
        config_store.set_storage_config(plan.destination)
        result.log.append(f"✅ Dossier des projets : {plan.destination}")
    report(total, "")
    return result


def _repoint_entry(old: Path, new: Path) -> None:
    """Met à jour (et enregistre tout de suite) le chemin d'un projet déplacé."""
    cfg = config_store._load_config()
    entry = config_store._find_entry(cfg, old)
    if entry is None:
        return
    entry["path"] = str(new)
    entry["name"] = entry.get("name") or new.name
    config_store._save_config(cfg)


def migrate_now(on_progress: ProgressCallback | None = None,
                cancel: Callable[[], bool] | None = None) -> LegacyResult | None:
    """Détecte puis applique ; None si rien à faire."""
    plan = plan_migration()
    if plan is None:
        return None
    return apply_migration(plan, on_progress, cancel)
