"""
Voktora — fleet.py (1.1.0)
Vue d'ensemble de TOUS les projets : état Git (modifications, retard/avance, sans dépôt distant, dossier manquant),
actions groupées (fetch / pull sans fusion forcée), recherche globale (noms, fichiers, contenu) et projets orphelins.
Pensé pour une centaine de projets : analyses en parallèle (nombre de threads réglé par le profil de performance),
aucune lecture inutile, annulation possible. Toutes les fonctions sont bloquantes : à lancer dans un thread.
Voktora ne lance ici ni commit ni push.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import core

GIT_TIMEOUT = 20.0
SKIP_DIRS = {".git", "node_modules", "target", ".venv", "venv", "__pycache__", "dist", "build", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", ".gradle", ".idea"}
MAX_SEARCH_FILE = 1_000_000          # on ne lit pas les fichiers de plus de 1 Mo (binaires, journaux…)


@dataclass
class RepoState:
    name: str
    path: str
    exists: bool = True
    is_git: bool = False
    branch: str = ""
    dirty: int = 0              # fichiers modifiés / en attente
    untracked: int = 0
    ahead: int = 0
    behind: int = 0
    has_remote: bool = False
    error: str = ""

    @property
    def problems(self) -> list[str]:
        out = []
        if not self.exists:
            out.append("dossier manquant")
        elif not self.is_git:
            out.append("pas de dépôt Git")
        else:
            if self.dirty or self.untracked:
                out.append(f"{self.dirty + self.untracked} modification(s) non commitée(s)")
            if self.behind:
                out.append(f"{self.behind} commit(s) de retard")
            if self.ahead:
                out.append(f"{self.ahead} commit(s) non poussé(s)")
            if not self.has_remote:
                out.append("sans dépôt distant")
        return out

    @property
    def clean(self) -> bool:
        return self.exists and self.is_git and not self.problems

    def to_dict(self) -> dict:
        return {**asdict(self), "problems": self.problems}


def _git(path: Path, *args: str, timeout: float = GIT_TIMEOUT) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=timeout,  # noqa: S603, S607
                              encoding="utf-8", errors="replace", check=False,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def scan_repo(name: str, path: str | Path) -> RepoState:
    """État d'un projet avec UNE seule commande git (`status --porcelain=v2 --branch`), sans réseau."""
    p = Path(path)
    state = RepoState(name=name, path=str(p), exists=p.is_dir())
    if not state.exists or not (p / ".git").exists():
        return state
    state.is_git = True
    code, out = _git(p, "status", "--porcelain=v2", "--branch")
    if code != 0:
        state.error = out.strip()[:200]
        return state
    for line in out.splitlines():
        if line.startswith("# branch.head "):
            state.branch = line.split(" ", 2)[2]
        elif line.startswith("# branch.upstream "):
            state.has_remote = True
        elif line.startswith("# branch.ab "):
            _, _, plus, minus = line.split()
            state.ahead, state.behind = int(plus[1:]), int(minus[1:])
        elif line.startswith("?"):
            state.untracked += 1
        elif line[:1] in "12u":
            state.dirty += 1
    if not state.has_remote:                       # branche sans suivi : un remote existe-t-il quand même ?
        code, remotes = _git(p, "remote")
        state.has_remote = code == 0 and bool(remotes.strip())
    return state


def projects_list() -> list[tuple[str, str]]:
    return [(e.get("name") or Path(e["path"]).name, e["path"]) for e in core.list_projects() if e.get("path")]


def scan_all(workers: int = 4, cancel: Callable[[], bool] | None = None,
             on_result: Callable[[RepoState, int, int], None] | None = None,
             projects: Iterable[tuple[str, str]] | None = None) -> list[RepoState]:
    items = list(projects if projects is not None else projects_list())
    results: list[RepoState] = []
    if not items:
        return results

    def work(item: tuple[str, str]) -> RepoState | None:
        if cancel and cancel():
            return None
        return scan_repo(*item)

    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="voktora-fleet") as pool:
        for done, state in enumerate(pool.map(work, items), start=1):
            if state is None:
                break
            results.append(state)
            if on_result:
                on_result(state, done, len(items))
    return results


def summary(states: list[RepoState]) -> dict:
    return {"total": len(states), "clean": sum(s.clean for s in states),
            "dirty": sum(1 for s in states if s.dirty or s.untracked),
            "behind": sum(1 for s in states if s.behind), "ahead": sum(1 for s in states if s.ahead),
            "no_remote": sum(1 for s in states if s.is_git and not s.has_remote),
            "not_git": sum(1 for s in states if s.exists and not s.is_git),
            "missing": sum(1 for s in states if not s.exists)}


# ── actions groupées ────────────────────────────────────────────────────────────

BULK_OPS = {"fetch": ["fetch", "--all", "--prune"], "pull": ["pull", "--ff-only"]}


def bulk(op: str, targets: Iterable[tuple[str, str]], workers: int = 3, cancel: Callable[[], bool] | None = None,
         on_result: Callable[[str, bool, str, int, int], None] | None = None) -> list[dict]:
    """`fetch` ou `pull --ff-only` (jamais de fusion ni de réécriture : un pull qui diverge échoue proprement).
    Pas de push, pas de commit. Les dépôts avec modifications locales sont ignorés pour `pull`."""
    if op not in BULK_OPS:
        raise ValueError(f"Action inconnue : {op}")
    items = list(targets)
    results: list[dict] = []

    def work(item: tuple[str, str]) -> dict:
        name, path = item
        if cancel and cancel():
            return {"name": name, "ok": False, "message": "annulé", "skipped": True}
        p = Path(path)
        if not (p / ".git").exists():
            return {"name": name, "ok": False, "message": "pas un dépôt Git", "skipped": True}
        if op == "pull":
            state = scan_repo(name, p)
            if state.dirty:
                return {"name": name, "ok": False, "message": "modifications locales : pull ignoré", "skipped": True}
            if not state.has_remote:
                return {"name": name, "ok": False, "message": "sans dépôt distant", "skipped": True}
        code, out = _git(p, *BULK_OPS[op], timeout=120.0)
        return {"name": name, "ok": code == 0, "message": out.strip().splitlines()[-1][:200] if out.strip() else "ok",
                "skipped": False}

    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="voktora-bulk") as pool:
        for done, res in enumerate(pool.map(work, items), start=1):
            results.append(res)
            if on_result:
                on_result(res["name"], res["ok"], res["message"], done, len(items))
    return results


# ── recherche globale ────────────────────────────────────────────────────────────

@dataclass
class Hit:
    project: str
    path: str            # chemin relatif dans le projet ("" = le projet lui-même)
    kind: str            # "projet" | "fichier" | "contenu"
    line: int = 0
    text: str = ""


def search(query: str, projects: Iterable[tuple[str, str]] | None = None, limit: int = 200, content: bool = True,
           cancel: Callable[[], bool] | None = None) -> list[Hit]:
    """Cherche dans les noms de projets, de fichiers et (si `content`) dans le texte. Insensible à la casse.
    Utilise ripgrep s'il est installé (rapide sur 100 projets), sinon un parcours Python borné."""
    q = query.strip()
    if len(q) < 2:
        return []
    items = list(projects if projects is not None else projects_list())
    hits: list[Hit] = []
    low = q.lower()
    for name, _path in items:
        if low in name.lower():
            hits.append(Hit(name, "", "projet"))
    rg = shutil.which("rg") if content else None
    for name, path in items:
        if len(hits) >= limit or (cancel and cancel()):
            break
        root = Path(path)
        if not root.is_dir():
            continue
        if rg:
            hits.extend(_rg_search(rg, name, root, q, limit - len(hits), cancel))
            hits.extend(_name_search(name, root, low, limit - len(hits), cancel, names_only=True))
        else:
            hits.extend(_name_search(name, root, low, limit - len(hits), cancel, content=content, query=q))
    return hits[:limit]


def _name_search(name: str, root: Path, low: str, room: int, cancel, names_only: bool = False,
                 content: bool = False, query: str = "") -> list[Hit]:
    out: list[Hit] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if cancel and cancel():
            break
        for fname in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fname), root).replace(os.sep, "/")
            if low in fname.lower():
                out.append(Hit(name, rel, "fichier"))
            if content and not names_only:
                out.extend(_grep_file(name, Path(dirpath) / fname, rel, query))
            if len(out) >= room:
                return out
    return out


def _grep_file(name: str, path: Path, rel: str, query: str) -> list[Hit]:
    try:
        if path.stat().st_size > MAX_SEARCH_FILE:
            return []
        data = path.read_bytes()
    except OSError:
        return []
    if b"\0" in data[:4096]:
        return []
    low = query.lower()
    out = []
    for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), start=1):
        if low in line.lower():
            out.append(Hit(name, rel, "contenu", number, line.strip()[:160]))
            if len(out) >= 5:                   # 5 lignes par fichier suffisent pour s'y retrouver
                break
    return out


def _rg_search(rg: str, name: str, root: Path, query: str, room: int, cancel) -> list[Hit]:
    try:
        done = subprocess.run([rg, "--json", "-i", "-F", "-m", "5", "--max-filesize", "1M", "--", query, str(root)],  # noqa: S603
                              capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace", check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    import json
    out: list[Hit] = []
    for raw in done.stdout.splitlines():
        if cancel and cancel():
            break
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if ev.get("type") != "match":
            continue
        data = ev["data"]
        file = data.get("path", {}).get("text", "")
        out.append(Hit(name, os.path.relpath(file, root).replace(os.sep, "/"), "contenu", data.get("line_number", 0),
                       data.get("lines", {}).get("text", "").strip()[:160]))
        if len(out) >= room:
            break
    return out


# ── projets orphelins ────────────────────────────────────────────────────────────

def find_orphans() -> list[str]:
    """Dossiers de la racine des projets qui ne sont enregistrés nulle part (ex. copiés à la main)."""
    root = core.get_projects_root()
    if not root.is_dir():
        return []
    known = {Path(p).resolve() for _, p in projects_list() if p}
    ignore = ["_*", ".*", "lost+found"]
    out = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and not any(fnmatch.fnmatch(child.name, pat) for pat in ignore) and child.resolve() not in known:
            out.append(str(child))
    return out


def timestamp() -> float:
    return time.time()
