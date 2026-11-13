"""Qualité : problèmes de fichiers, duplications inter-fichiers, points chauds, code possiblement mort (avec réserves)."""

from __future__ import annotations

from collections import defaultdict

from ..core.model import CALLS, DECORATES, FFI, REFERENCES, Issue

LONG_FILE = 1200
DUP_MIN_LINES = 12
TEST_MARKERS = ("test_", "_test.", "/tests/", "/test/", "conftest", ".spec.", ".test.")
SEVERITY = {"error": 0, "warn": 1, "info": 2}


def duplicates(files: dict) -> list[Issue]:
    """Groupes de fenêtres de lignes identiques présentes à au moins deux endroits, fusionnées en régions."""
    index: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for path, fr in files.items():
        for digest, a, b in fr.blocks:
            index[digest].append((path, a, b))
    regions: dict[tuple, list] = {}
    for _digest, locs in index.items():
        distinct = {(p, a) for p, a, _ in locs}
        if len(distinct) < 2:
            continue
        key = tuple(sorted({p for p, _, _ in locs}))
        regions.setdefault(key, []).append(sorted(locs))
    issues: list[Issue] = []
    seen_pairs = set()
    for _key, groups in regions.items():
        # fusionne les fenêtres consécutives d'une même paire de fichiers
        by_file: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for locs in groups:
            for p, a, b in locs:
                by_file[p].append((a, b))
        merged: dict[str, list[tuple[int, int]]] = {}
        for p, spans in by_file.items():
            spans.sort()
            out = []
            for a, b in spans:
                if out and a <= out[-1][1] + 1:
                    out[-1] = (out[-1][0], max(out[-1][1], b))
                else:
                    out.append((a, b))
            merged[p] = out
        for p, spans in merged.items():
            for a, b in spans:
                lines = b - a + 1
                if lines < DUP_MIN_LINES or (p, a) in seen_pairs:
                    continue
                seen_pairs.add((p, a))
                others = sorted({f"{q}:{x}" for q, ss in merged.items() for x, _ in ss if (q, x) != (p, a)})[:6]
                if not others:
                    continue
                issues.append(Issue(p, a, "warn" if lines >= 30 else "info", "DUPLICATE",
                                    f"Bloc dupliqué de ~{lines} lignes",
                                    "Ces lignes (espaces et casse ignorés) se retrouvent à : " + ", ".join(others),
                                    "Factorisez dans une fonction commune."))
    return issues


def file_issues(files: dict) -> list[Issue]:
    out = []
    for path, fr in files.items():
        if fr.loc > LONG_FILE and fr.lang != "config":
            out.append(Issue(path, 1, "info", "LONG-FILE", f"Fichier très long ({fr.loc} lignes)",
                             f"Un fichier de plus de {LONG_FILE} lignes mélange souvent plusieurs responsabilités.",
                             "Découpez-le par responsabilité."))
        todos = fr.info.get("todos", [])
        if len(todos) >= 5:
            out.append(Issue(path, todos[0], "info", "TODO", f"{len(todos)} marqueurs TODO/FIXME",
                             "Du travail restant est noté dans le code.", "Transformez-les en tâches suivies."))
    return out


def hotspots(graph, limit: int = 15) -> list[dict]:
    rows = [s for s in graph.nodes.values() if s.kind in ("function", "method") and s.complexity > 1]
    rows.sort(key=lambda s: -s.complexity)
    return [{"id": s.id, "name": s.name, "file": s.file, "line": s.line, "complexity": s.complexity,
             "lines": max(0, s.end_line - s.line + 1)} for s in rows[:limit]]


def dead_code_candidates(graph, entry_ids: set[str]) -> list[dict]:
    """Fonctions jamais appelées DANS le projet. Réserves : usage dynamique, API publique, rappels, tests, hors-projet."""
    out = []
    for s in graph.nodes.values():
        if s.kind not in ("function", "method") or s.id in entry_ids:
            continue
        if s.name.startswith("__") or any(m in s.file for m in TEST_MARKERS) or s.name.startswith(("test_", "Test")):
            continue
        if s.decorators or s.meta.get("pyo3") or s.meta.get("extern_c") or s.meta.get("exported") or s.meta.get("trait_decl"):
            continue
        if s.meta.get("public") and s.lang == "rust":
            continue
        if graph.in_edges(s.id, {CALLS, REFERENCES, FFI, DECORATES}):
            continue
        parent = graph.nodes.get(s.parent)
        if parent is not None and parent.kind == "trait":
            continue
        out.append({"id": s.id, "name": s.name, "file": s.file, "line": s.line, "kind": s.kind})
    out.sort(key=lambda r: (r["file"], r["line"]))
    return out


def summarize(issues: list[Issue]) -> dict:
    by_sev = defaultdict(int)
    by_code = defaultdict(int)
    for i in issues:
        by_sev[i.severity] += 1
        by_code[i.code] += 1
    return {"total": len(issues), "by_severity": dict(by_sev), "by_code": dict(sorted(by_code.items(), key=lambda kv: -kv[1]))}
