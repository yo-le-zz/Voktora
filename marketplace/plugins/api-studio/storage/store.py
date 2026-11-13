"""Collections par projet, environnements, historique : JSON atomique dans le dossier de données du plugin."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

HISTORY_MAX = 300


class Store:
    def __init__(self, base: Path):
        self.base = Path(base)

    def _dir(self, project: str | None) -> Path:
        key = hashlib.sha1((project or "_global").encode()).hexdigest()[:12]    # noqa: S324 — simple identifiant de dossier
        d = self.base / key
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

    def collections(self, project) -> list[dict]:
        return self._load(project, "collections", [])

    def save_collection(self, project, col: dict) -> None:
        items = [c for c in self.collections(project) if c["name"] != col["name"]] + [col]
        self._save(project, "collections", sorted(items, key=lambda c: c["name"]))

    def delete_collection(self, project, name: str) -> None:
        self._save(project, "collections", [c for c in self.collections(project) if c["name"] != name])

    def environments(self, project) -> dict:
        return self._load(project, "environments", {"active": "", "items": {}})

    def save_environments(self, project, data: dict) -> None:
        self._save(project, "environments", data)

    def add_history(self, project, entry: dict) -> None:
        items = [{**entry, "time": time.time()}, *self._load(project, "history", [])][:HISTORY_MAX]
        self._save(project, "history", items)

    def history(self, project) -> list[dict]:
        return self._load(project, "history", [])

    def clear_history(self, project) -> None:
        self._save(project, "history", [])
