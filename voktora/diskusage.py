"""
Voktora — diskusage
Espace disque d'un projet, avec classification « intelligente » de ce qui est régénérable.

Pour chaque dossier reconnu (node_modules, target, build, __pycache__, .venv, dossiers Nuitka…) on décide
s'il s'agit de dépendances, d'une sortie de compilation ou d'un cache — en vérifiant les fichiers voisins
(un dossier « target » n'est un build Rust que s'il y a un Cargo.toml à côté ; un « build » ne l'est que
s'il y a un CMakeLists.txt, un pyproject.toml, un package.json…). Le marqueur standard CACHEDIR.TAG est aussi
reconnu. Rien n'est jamais supprimé hors du projet, ni les dossiers suivis par git, ni `.git`.

Bibliothèque standard uniquement ; `core` n'est utilisé que pour la configuration.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

CACHEDIR_SIGNATURE = b"Signature: 8a477f597d28d172789f06886806bc55"

# catégories
DEPS, BUILD, CACHE, VCS, SOURCE = "deps", "build", "cache", "vcs", "source"
LABELS = {
    DEPS: "Dépendances (réinstallables)",
    BUILD: "Compilation / sorties de build",
    CACHE: "Caches d'outils",
    VCS: "Historique git (.git)",
    SOURCE: "Vos fichiers",
}
REGENERABLE = (CACHE, BUILD, DEPS)
DEFAULT_RESET = (CACHE, BUILD)               # les dépendances demandent un réseau pour revenir : opt-in
DEFAULT_CONFIRM_MB = 500


@dataclass(frozen=True)
class Rule:
    names: tuple[str, ...]
    category: str
    why: str
    parent_markers: tuple[str, ...] = ()          # au moins un doit exister À CÔTÉ du dossier
    inside_markers: tuple[str, ...] = ()          # au moins un doit exister DANS le dossier


RULES: tuple[Rule, ...] = (
    # dépendances
    Rule(("node_modules",), DEPS, "paquets npm"),
    Rule((".venv", "venv", "env", ".virtualenv"), DEPS, "environnement virtuel Python", inside_markers=("pyvenv.cfg",)),
    Rule(("vendor",), DEPS, "dépendances (Composer/Go/Bundler)", ("composer.json", "go.mod", "Gemfile")),
    Rule(("bower_components", "jspm_packages"), DEPS, "paquets web"),
    Rule(("Pods",), DEPS, "CocoaPods", ("Podfile",)),
    Rule((".tox", ".nox"), DEPS, "environnements de test Python"),
    # sorties de compilation
    Rule(("target",), BUILD, "compilation Rust/Java", ("Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts")),
    Rule(("build",), BUILD, "dossier de build", ("CMakeLists.txt", "setup.py", "pyproject.toml", "package.json",
                                                  "build.gradle", "build.gradle.kts", "Makefile", "meson.build",
                                                  "Cargo.toml", "setup.cfg")),
    Rule(("dist",), BUILD, "paquets générés", ("package.json", "pyproject.toml", "setup.py", "setup.cfg")),
    Rule(("out",), BUILD, "sortie de build", ("package.json", "pom.xml", "build.gradle", "tsconfig.json")),
    Rule(("bin", "obj"), BUILD, "compilation .NET", ("*.csproj", "*.sln", "*.fsproj", "*.vbproj")),
    Rule((".next", ".nuxt", ".svelte-kit", ".angular", ".turbo", ".parcel-cache", ".vite", ".docusaurus"), BUILD,
         "build du framework web"),
    Rule(("cmake-build-*", "_build"), BUILD, "build CMake/Elixir"),
    Rule(("*.build", "*.dist", "*.onefile-build"), BUILD, "compilation Nuitka", inside_markers=()),
    Rule((".gradle", ".dart_tool", ".stack-work", ".zig-cache", "zig-cache", "DerivedData"), BUILD,
         "cache de compilation"),
    Rule(("*.egg-info", ".eggs"), BUILD, "métadonnées de paquet Python"),
    # caches d'outils
    Rule(("__pycache__",), CACHE, "bytecode Python"),
    Rule((".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis", ".pytype", ".pyre", ".ipynb_checkpoints",
          ".eslintcache", ".sass-cache", ".cache", "htmlcov", ".coverage_html"), CACHE, "cache d'outil"),
)

_EXACT = {n: r for r in RULES for n in r.names if not any(c in n for c in "*?[")}
_PATTERNS = [(n, r) for r in RULES for n in r.names if any(c in n for c in "*?[")]


@dataclass
class Item:
    rel: str                  # chemin relatif au projet
    category: str
    why: str
    bytes: int
    files: int
    protected: str = ""       # raison pour laquelle on ne le supprimera pas (git, hors projet…)


@dataclass
class ProjectUsage:
    path: Path
    total: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    items: list[Item] = field(default_factory=list)
    snapshots: int = 0
    error: str = ""

    @property
    def reclaimable(self) -> int:
        return sum(self.by_category.get(c, 0) for c in REGENERABLE)

    def reclaimable_for(self, categories: Iterable[str]) -> int:
        cats = set(categories)
        return sum(i.bytes for i in self.items if i.category in cats and not i.protected)


def human(size: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if abs(size) < 1024 or unit == "To":
            return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} To"


def _disk_bytes(st: os.stat_result) -> int:
    blocks = getattr(st, "st_blocks", None)
    return blocks * 512 if blocks is not None else st.st_size


def dir_size(path: Path) -> tuple[int, int]:
    """(octets occupés sur le disque, nombre de fichiers) d'un dossier ; sans suivre les liens symboliques."""
    total = files = 0
    stack = [str(path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += _disk_bytes(entry.stat(follow_symlinks=False))
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, files


def _has(directory: str, patterns: tuple[str, ...]) -> bool:
    try:
        names = os.listdir(directory)
    except OSError:
        return False
    return any(fnmatch.filter(names, pattern) for pattern in patterns)


def classify_dir(parent: str, name: str) -> Rule | None:
    """Règle applicable au dossier `parent/name`, en vérifiant les marqueurs ; None = c'est vos fichiers."""
    full = os.path.join(parent, name)
    rule = _EXACT.get(name)
    if rule is None:
        rule = next((r for pattern, r in _PATTERNS if fnmatch.fnmatch(name, pattern)), None)
    if rule is not None and (
        (rule.parent_markers and not _has(parent, rule.parent_markers))
        or (rule.inside_markers and not _has(full, rule.inside_markers))
        or (rule.names[0] == "*.build" and not _looks_like_nuitka(parent, name))
    ):
        rule = None
    if rule is None:
        try:                                         # standard CACHEDIR.TAG (cargo, pip, ccache, …)
            with open(os.path.join(full, "CACHEDIR.TAG"), "rb") as handle:
                if handle.read(len(CACHEDIR_SIGNATURE)) == CACHEDIR_SIGNATURE:
                    return Rule((name,), CACHE, "cache marqué CACHEDIR.TAG")
        except OSError:
            pass
    return rule


def _looks_like_nuitka(parent: str, name: str) -> bool:
    full = os.path.join(parent, name)
    stem = name.split(".")[0]
    return os.path.isfile(os.path.join(full, f"{stem}.c")) \
        or _has(full, ("module.*.c", "*.o", "static_src", "__constants.bin", "*.const"))


def scan_project(path: Path | str, snapshots_dir: Path | None = None,
                 cancel: Callable[[], bool] | None = None) -> ProjectUsage:
    """Taille du projet par catégorie. N'écrit rien."""
    root = Path(path)
    usage = ProjectUsage(root)
    if not root.is_dir():
        usage.error = "Dossier introuvable."
        return usage
    by_cat: dict[str, int] = {}
    stack = [str(root)]
    while stack:
        if cancel and cancel():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                listing = list(entries)
        except OSError:
            continue
        for entry in listing:
            try:
                if entry.is_symlink():
                    continue
                if not entry.is_dir(follow_symlinks=False):
                    by_cat[SOURCE] = by_cat.get(SOURCE, 0) + _disk_bytes(entry.stat(follow_symlinks=False))
                    continue
                rel = os.path.relpath(entry.path, root)
                if entry.name == ".git" and current == str(root):
                    size, files = dir_size(Path(entry.path))
                    by_cat[VCS] = by_cat.get(VCS, 0) + size
                    continue
                rule = classify_dir(current, entry.name)
                if rule is not None:
                    size, files = dir_size(Path(entry.path))
                    by_cat[rule.category] = by_cat.get(rule.category, 0) + size
                    usage.items.append(Item(rel.replace(os.sep, "/"), rule.category, rule.why, size, files))
                else:
                    stack.append(entry.path)
            except OSError:
                continue
    usage.by_category = by_cat
    usage.total = sum(by_cat.values())
    usage.items.sort(key=lambda i: -i.bytes)
    _mark_protected(root, usage.items)
    if snapshots_dir is not None and snapshots_dir.is_dir():
        usage.snapshots = dir_size(snapshots_dir)[0]
    return usage


def _git_tracked(root: Path, rel: str) -> bool:
    """True si git suit des fichiers dans ce dossier (le supprimer modifierait le dépôt)."""
    if not (root / ".git").exists() or shutil.which("git") is None:
        return False
    try:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", rel],        # noqa: S603, S607
                                capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip(b"\0"))


def _mark_protected(root: Path, items: list[Item]) -> None:
    for item in items:
        if _git_tracked(root, item.rel):
            item.protected = "suivi par git"


def scan_many(paths: Iterable[Path | str], workers: int = 4,
              on_progress: Callable[[int, int, str], None] | None = None,
              cancel: Callable[[], bool] | None = None,
              snapshots_root: Path | None = None) -> list[ProjectUsage]:
    """Analyse plusieurs projets en parallèle (le disque est le goulot : peu de threads suffisent)."""
    paths = [Path(p) for p in paths]
    results: dict[int, ProjectUsage] = {}
    done = 0

    def work(index: int) -> None:
        p = paths[index]
        snaps = snapshots_root / p.name if snapshots_root else None
        results[index] = scan_project(p, snaps, cancel)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(work, i) for i in range(len(paths))]
        for future in futures:
            future.result()
            done += 1
            if on_progress:
                on_progress(done, len(paths), paths[done - 1].name)
    return [results[i] for i in range(len(paths))]


# ── Nettoyage ─────────────────────────────────────────────────────────────────

def safe_to_delete(root: Path, item: Item) -> str:
    """Raison du refus, ou chaîne vide si on peut supprimer cet élément."""
    if item.category not in REGENERABLE:
        return "catégorie non régénérable"
    if item.protected:
        return item.protected
    if not item.rel or item.rel.startswith(("/", "..")) or ".." in Path(item.rel).parts:
        return "chemin invalide"
    target = root / item.rel
    if target.is_symlink() or not target.is_dir():
        return "n'est pas un dossier ordinaire"
    try:
        real_root, real_target = root.resolve(), target.resolve()
    except OSError:
        return "chemin illisible"
    if real_target == real_root or not real_target.is_relative_to(real_root):
        return "hors du projet"
    if ".git" in Path(item.rel).parts:
        return "dossier git"
    return ""


def clean_project(path: Path | str, categories: Iterable[str] = DEFAULT_RESET,
                  usage: ProjectUsage | None = None,
                  cancel: Callable[[], bool] | None = None) -> tuple[int, list[str]]:
    """Supprime les éléments régénérables des catégories demandées. Retourne (octets libérés, avertissements)."""
    root = Path(path)
    cats = set(categories) & set(REGENERABLE)
    usage = usage or scan_project(root)
    freed, notes = 0, []
    for item in usage.items:
        if item.category not in cats:
            continue
        if cancel and cancel():
            break
        reason = safe_to_delete(root, item)
        if reason:
            notes.append(f"{item.rel} conservé ({reason})")
            continue
        shutil.rmtree(root / item.rel, ignore_errors=True)
        if (root / item.rel).exists():
            notes.append(f"{item.rel} : suppression incomplète")
        freed += item.bytes
    return freed, notes


def reset_all(usages: list[ProjectUsage], categories: Iterable[str] = DEFAULT_RESET,
              on_progress: Callable[[int, int, str], None] | None = None,
              cancel: Callable[[], bool] | None = None) -> tuple[int, list[str]]:
    freed, notes = 0, []
    for index, usage in enumerate(usages, 1):
        if cancel and cancel():
            break
        done, project_notes = clean_project(usage.path, categories, usage, cancel)
        freed += done
        notes += [f"{usage.path.name}/{n}" for n in project_notes]
        if on_progress:
            on_progress(index, len(usages), usage.path.name)
    return freed, notes


# ── Seuil de double confirmation (réglage) ─────────────────────────────────────

def confirm_threshold_bytes() -> int:
    import core
    try:
        mb = float(core.get_app_config().get("disk_reset_confirm_mb", DEFAULT_CONFIRM_MB))
    except (TypeError, ValueError):
        mb = DEFAULT_CONFIRM_MB
    return int(max(0.0, mb) * 1024 * 1024)


def needs_double_confirmation(total_bytes: int) -> bool:
    return total_bytes > confirm_threshold_bytes()
