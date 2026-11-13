"""Workflows par projet, historique d'exécutions, import/export JSON validé."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from ..core import validation

HISTORY_MAX = 200
SCHEMA = 1


class Store:
    def __init__(self, base: Path):
        self.base = Path(base)

    def _dir(self, project) -> Path:
        d = self.base / hashlib.sha1(str(project).encode()).hexdigest()[:12]      # noqa: S324 — nom de dossier
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _load(self, project, name, default):
        try:
            return json.loads((self._dir(project) / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _save(self, project, name, data) -> None:
        p = self._dir(project) / f"{name}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)

    def workflows(self, project) -> dict[str, dict]:
        return self._load(project, "workflows", {})

    def save_workflow(self, project, wf: dict, wf_id: str | None = None) -> str:
        items = self.workflows(project)
        wf_id = wf_id or self.unique_id(items, wf.get("name", "workflow"))
        items[wf_id] = wf
        self._save(project, "workflows", items)
        return wf_id

    @staticmethod
    def unique_id(items: dict, name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workflow"
        wf_id, n = base, 2
        while wf_id in items:
            wf_id, n = f"{base}-{n}", n + 1
        return wf_id

    def delete_workflow(self, project, wf_id: str) -> None:
        items = self.workflows(project)
        items.pop(wf_id, None)
        self._save(project, "workflows", items)

    def add_run(self, project, wf_id: str, rec: dict) -> None:
        runs = [{"wf": wf_id, **rec, "id": int(time.time() * 1000)}, *self._load(project, "runs", [])][:HISTORY_MAX]
        self._save(project, "runs", runs)

    def runs(self, project, wf_id: str = "") -> list[dict]:
        return [r for r in self._load(project, "runs", []) if not wf_id or r.get("wf") == wf_id]

    def clear_runs(self, project) -> None:
        self._save(project, "runs", [])


def export_text(wf: dict) -> str:
    clean = {**wf, "triggers": [{k: v for k, v in t.items() if k != "token"} for t in wf.get("triggers", [])]}
    return json.dumps({"voktora_workflow": SCHEMA, **clean}, indent=2, ensure_ascii=False)


def import_text(text: str) -> dict:
    """Lit un workflow exporté ; lève ValueError s'il est invalide. Les jetons de déclencheurs HTTP ne sont jamais exportés/importés en clair."""
    try:
        d = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"JSON invalide : {exc}") from exc
    if not isinstance(d, dict) or d.get("voktora_workflow") != SCHEMA:
        raise ValueError("Ce fichier n'est pas un workflow Voktora (version 1).")
    d.pop("voktora_workflow")
    d.setdefault("nodes", [])
    d.setdefault("edges", [])
    d.setdefault("triggers", [{"kind": "manual"}])
    for n in d["nodes"]:
        n.setdefault("params", {})
        n.setdefault("options", {})
        n.setdefault("x", 0)
        n.setdefault("y", 0)
    for t in d["triggers"]:
        t.pop("token", None)
    problems = validation.validate({**d, "triggers": [t for t in d["triggers"] if t.get("kind") != "http_in"]})
    if problems["errors"]:
        raise ValueError("Workflow invalide : " + " ; ".join(problems["errors"][:5]))
    return d
