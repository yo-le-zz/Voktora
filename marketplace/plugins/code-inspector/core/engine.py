"""Moteur central : scan → analyse INCRÉMENTALE (cache) → lieur → services → Analysis.

Incrémental : un fichier n'est réanalysé que si sa taille/date ont changé ET que son contenu (SHA-1) diffère ;
le lieur, lui, est rapide et s'exécute toujours sur l'ensemble pour garder les relations croisées exactes."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..analyzers import base, config_an, cpp_an, js_an, python_an, rust_an  # noqa: F401 — enregistre les analyseurs
from ..services import deps_audit, detect, quality
from ..storage.store import Store
from . import linker, scan, textutil
from .graph import Graph
from .model import FileResult, Issue


class Cancelled(Exception):
    pass


@dataclass
class Analysis:
    root: str
    files: dict[str, FileResult]
    graph: Graph
    issues: list[Issue]
    dependencies: list[dict]
    report: dict
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"root": self.root, "graph": self.graph.to_dict(), "issues": [i.to_dict() for i in self.issues],
                "dependencies": self.dependencies, "report": self.report, "stats": self.stats,
                "files": {p: {"lang": f.lang, "loc": f.loc} for p, f in self.files.items()}}


def analyze_text(path: str, text: str) -> FileResult:
    an = base.for_file(path)
    if an is None:
        raise ValueError(f"Aucun analyseur pour {path}")
    return an.analyze_file(path, text)


def analyze(root: Path | str, store: Store | None = None, progress=None, cancel: threading.Event | None = None,
            force: bool = False, extra_ignore: list[str] | None = None) -> Analysis:
    started = time.time()
    root = Path(root)
    entries = scan.scan(root, extra_ignore)
    cache = {} if (force or store is None) else store.load_files(root, base.ANALYZER_VERSION)
    fresh: dict[str, dict] = {}
    files: dict[str, FileResult] = {}
    stats = {"scanned": len(entries), "analyzed": 0, "reused": 0, "removed": 0, "errors": 0, "analyzed_files": []}
    for i, (rel, size, mtime) in enumerate(entries):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if progress:
            progress(i, len(entries), rel)
        old = cache.get(rel)
        if old and old["size"] == size and old["mtime"] == mtime:
            fresh[rel] = old
            files[rel] = FileResult.from_dict(old["result"])
            stats["reused"] += 1
            continue
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        digest = textutil.file_digest(data)
        if old and old["digest"] == digest:
            old = {**old, "size": size, "mtime": mtime}
            fresh[rel] = old
            files[rel] = FileResult.from_dict(old["result"])
            stats["reused"] += 1
            continue
        text = data.decode("utf-8", errors="replace")
        try:
            result = analyze_text(rel, text)
        except Exception as exc:  # noqa: BLE001 — un fichier piégé ne doit pas casser toute l'analyse
            result = FileResult(rel, (base.for_file(rel) or base.Analyzer()).lang or "?", loc=len(text.splitlines()))
            result.issues.append(Issue(rel, 1, "error", "ANALYZER-ERROR", f"L'analyseur a échoué : {type(exc).__name__}: {exc}",
                                       "Ce fichier est ignoré dans le graphe.", "Signalez le cas : il aide à améliorer l'analyseur."))
            stats["errors"] += 1
        result.digest = digest
        fresh[rel] = {"size": size, "mtime": mtime, "digest": digest, "result": result.to_dict()}
        files[rel] = result
        stats["analyzed"] += 1
        stats["analyzed_files"].append(rel)
    stats["removed"] = len([p for p in cache if p not in fresh])
    if store is not None:
        store.save_files(root, base.ANALYZER_VERSION, fresh)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if progress:
        progress(len(entries), len(entries), "liaison du graphe…")
    graph = linker.build(files)
    deps = []
    for path, fr in files.items():
        for d in fr.info.get("dependencies", []):
            deps.append({**d, "file": path})
    dep_rows, dep_issues = deps_audit.audit(deps, graph, files)
    issues = [i for fr in files.values() for i in fr.issues] + dep_issues + quality.duplicates(files) + quality.file_issues(files)
    issues.sort(key=lambda i: (quality.SEVERITY.get(i.severity, 3), i.file, i.line))
    entries_found = detect.entry_points(files, graph)
    report = {
        "languages": detect.languages(files), "frameworks": detect.frameworks(deps, graph), "entry_points": entries_found,
        "tests": detect.test_files(files), "issues": quality.summarize(issues), "hotspots": quality.hotspots(graph),
        "dead_code": quality.dead_code_candidates(graph, {e["symbol"] for e in entries_found}),
        "dependencies": dep_rows, "graph": graph.stats(), "ffi": graph.meta.get("ffi", {}),
        "config_files": sorted(p for p, f in files.items() if f.lang == "config"),
        "duration": round(time.time() - started, 3), "analyzed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    stats["seconds"] = report["duration"]
    return Analysis(str(root), files, graph, issues, dep_rows, report, stats)
