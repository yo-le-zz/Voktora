"""Index d'un projet : analyse incrémentale (taille/date puis empreinte), fichiers, symboles, rôles, dépendances, BM25."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import time
from pathlib import Path

from . import symbols as sy
from .bm25 import BM25

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", "target", "dist", "build", ".mypy_cache", ".ruff_cache",
             ".pytest_cache", ".idea", ".vscode", ".tox", "site-packages", ".next", "coverage"}
INDEXED = set(sy.LANGS)
MAX_SIZE = 1_500_000
CHUNK, OVERLAP = 40, 6
SCHEMA = 3


def _gitignore(root: Path) -> list[str]:
    pats = []
    for name in (".gitignore", ".voktoraignore"):
        try:
            for line in (root / name).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("!"):
                    pats.append(line.rstrip("/"))
        except OSError:
            pass
    return pats


def scan(root: Path) -> list[tuple[str, int, float]]:
    pats = _gitignore(root)
    out = []
    for dirpath, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not any(fnmatch.fnmatch(d, p) for p in pats))
        for f in sorted(files):
            rel = f if rel_dir == "." else f"{rel_dir}/{f}"
            if Path(f).suffix.lower() not in INDEXED and f not in ("Makefile", "Dockerfile"):
                continue
            if any(fnmatch.fnmatch(f, p) or fnmatch.fnmatch(rel, p) for p in pats):
                continue
            try:
                st = os.stat(os.path.join(dirpath, f))
            except OSError:
                continue
            if st.st_size <= MAX_SIZE:
                out.append((rel, st.st_size, st.st_mtime))
    return out


def chunks(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        out.append((i + 1, "\n".join(lines[i:i + CHUNK])))
        if i + CHUNK >= len(lines):
            break
        i += CHUNK - OVERLAP
    return out or [(1, "")]


class ProjectIndex:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.files: dict[str, dict] = {}          # rel → {size,mtime,sha,lang,role,loc,symbols,imports}
        self.bm = BM25()
        self.changes: list[dict] = []             # journal des mises à jour

    # -- construction incrémentale ---------------------------------------------------------------
    def update(self, progress=None, cancel=None) -> dict:
        entries = scan(self.root)
        seen = {rel for rel, _, _ in entries}
        report = {"added": [], "modified": [], "removed": [], "unchanged": 0, "symbols_added": [], "symbols_removed": []}
        for rel in [r for r in self.files if r not in seen]:
            report["removed"].append(rel)
            self._drop(rel)
        for i, (rel, size, mtime) in enumerate(entries):
            if cancel is not None and cancel.is_set():
                raise RuntimeError("annulé")
            if progress:
                progress(i, len(entries), rel)
            old = self.files.get(rel)
            if old and old["size"] == size and old["mtime"] == mtime:
                report["unchanged"] += 1
                continue
            try:
                data = (self.root / rel).read_bytes()
            except OSError:
                continue
            sha = hashlib.sha1(data).hexdigest()   # noqa: S324 — empreinte de changement, pas de sécurité
            if old and old["sha"] == sha:
                old["size"], old["mtime"] = size, mtime
                report["unchanged"] += 1
                continue
            text = data.decode("utf-8", "replace")
            lang = sy.LANGS.get(Path(rel).suffix.lower(), "text")
            syms = sy.extract(rel, lang, text)
            before = {(s["name"], s["parent"]) for s in old["symbols"]} if old else set()
            after = {(s["name"], s["parent"]) for s in syms}
            report["symbols_added"] += [f"{rel}:{'.'.join(filter(None, [p, n]))}" for n, p in sorted(after - before)] if old else []
            report["symbols_removed"] += [f"{rel}:{'.'.join(filter(None, [p, n]))}" for n, p in sorted(before - after)]
            self._drop(rel, keep_record=True)
            self.files[rel] = {"size": size, "mtime": mtime, "sha": sha, "lang": lang, "role": sy.role_of(rel, lang, text), "loc": text.count("\n") + 1,
                               "symbols": syms, "imports": sy.imports(lang, text)}
            for start, body in chunks(text):
                self.bm.add(f"{rel}#{start}", f"{rel} {body}", {"path": rel, "line": start})
            (report["modified"] if old else report["added"]).append(rel)
        if report["added"] or report["modified"] or report["removed"]:
            self.changes.insert(0, {"time": time.time(), **{k: v for k, v in report.items() if k != "unchanged"}})
            self.changes = self.changes[:100]
        return report

    def _drop(self, rel: str, keep_record: bool = False) -> None:
        for doc_id in [d for d, v in self.bm.docs.items() if v["meta"].get("path") == rel]:
            self.bm.remove(doc_id)
        if not keep_record:
            self.files.pop(rel, None)

    # -- consultation ------------------------------------------------------------------------------
    def search(self, query: str, mode: str = "lexical", limit: int = 20) -> list[dict]:
        hits = self.bm.search(query, limit * 3) if mode == "lexical" else self.bm.similar(query, limit * 3)
        out, seen = [], set()
        qt = set(re.findall(r"\w+", query.lower()))
        for doc_id, score in hits:
            meta = self.bm.docs[doc_id]["meta"]
            if meta["path"] in seen:
                continue
            seen.add(meta["path"])
            out.append({"path": meta["path"], "line": meta["line"], "score": round(score, 4), "role": self.files.get(meta["path"], {}).get("role", ""),
                        "snippet": self._snippet(meta["path"], meta["line"], qt)})
            if len(out) >= limit:
                break
        return out

    def _snippet(self, rel: str, start: int, terms: set) -> str:
        try:
            lines = (self.root / rel).read_text(encoding="utf-8", errors="replace").splitlines()[start - 1:start - 1 + CHUNK]
        except OSError:
            return ""
        best, idx = -1, 0
        for i, ln in enumerate(lines):
            sc = sum(t in ln.lower() for t in terms)
            if sc > best:
                best, idx = sc, i
        return "\n".join(lines[max(idx - 1, 0):idx + 2])[:300]

    def all_symbols(self) -> list[dict]:
        return [{**s, "file": rel} for rel, f in sorted(self.files.items()) for s in f["symbols"] if s["kind"] != "heading"]

    def _py_module_map(self) -> dict[str, str]:
        out = {}
        for rel, f in self.files.items():
            if f["lang"] == "python":
                key = rel[:-3]
                out[key[:-9] if key.endswith("/__init__") else key] = rel
        return out

    def _resolve_python(self, rel: str, imp: str, mods: dict[str, str]) -> str | None:
        dots = len(imp) - len(imp.lstrip("."))
        name = imp.lstrip(".").replace(".", "/")
        if dots:
            base = Path(rel).parent
            for _ in range(dots - 1):
                base = base.parent
            key = (base / name).as_posix() if name else base.as_posix()
            return mods.get("" if key == "." else key)
        hits = [t for k, t in mods.items() if (k == name or k.endswith("/" + name)) and t != rel]
        return hits[0] if len(hits) == 1 else None

    def internal_imports(self) -> list[tuple[str, str]]:
        """Arêtes (fichier → fichier) pour les imports qui se résolvent vers UN fichier du projet (jamais deviné si ambigu)."""
        mods = self._py_module_map()
        by_stem: dict[str, list[str]] = {}
        for rel in self.files:
            p = Path(rel)
            by_stem.setdefault(p.stem, []).append(rel)
            if p.stem in ("mod", "index", "lib") and p.parent.name:
                by_stem.setdefault(p.parent.name, []).append(rel)
        edges = set()
        for rel, f in self.files.items():
            for imp in f["imports"]:
                if f["lang"] == "python":
                    t = self._resolve_python(rel, imp, mods)
                    if t and t != rel:
                        edges.add((rel, t))
                    continue
                name = imp.replace("::", ".").replace("/", ".").lstrip(".").split(".")
                for cand in (name[-1], name[0]) if len(name) > 1 else (name[0],):
                    c = Path(cand).stem if "." in cand and f["lang"] in ("javascript", "typescript", "c", "cpp") else cand
                    targets = [t for t in by_stem.get(c, []) if t != rel and self.files[t]["lang"] == f["lang"]]
                    if len(targets) == 1:
                        edges.add((rel, targets[0]))
                        break
        return sorted(edges)

    def stats(self) -> dict:
        langs: dict[str, int] = {}
        roles: dict[str, int] = {}
        for f in self.files.values():
            langs[f["lang"]] = langs.get(f["lang"], 0) + f["loc"]
            roles[f["role"]] = roles.get(f["role"], 0) + 1
        return {"files": len(self.files), "symbols": sum(len(f["symbols"]) for f in self.files.values()), "chunks": len(self.bm),
                "loc_by_lang": dict(sorted(langs.items(), key=lambda kv: -kv[1])), "roles": dict(sorted(roles.items(), key=lambda kv: -kv[1]))}

    # -- persistance ---------------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "files": self.files, "bm25": self.bm.to_dict(), "changes": self.changes}

    @staticmethod
    def from_dict(root: Path, d: dict) -> ProjectIndex:
        ix = ProjectIndex(root)
        if d.get("schema") == SCHEMA:
            ix.files, ix.bm, ix.changes = d["files"], BM25.from_dict(d["bm25"]), d.get("changes", [])
        return ix
