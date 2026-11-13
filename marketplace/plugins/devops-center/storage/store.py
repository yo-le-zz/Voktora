"""Stockage JSON atomique dans le dossier de données du plugin (profils, pipelines, cibles, historique)."""

from __future__ import annotations

import json
import time
from pathlib import Path

HISTORY_MAX = 500
SCHEMA = 1


class Store:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.base / f"{name}.json"

    def load(self, name: str, default):
        try:
            data = json.loads(self._path(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default
        return data.get("items", default) if isinstance(data, dict) and data.get("schema") == SCHEMA else default

    def save(self, name: str, items) -> None:
        tmp = self._path(name).with_suffix(".tmp")
        tmp.write_text(json.dumps({"schema": SCHEMA, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._path(name))

    # -- historique -------------------------------------------------------------
    def add_history(self, record: dict) -> None:
        items = self.load("history", [])
        items.insert(0, {**record, "id": int(time.time() * 1000)})
        self.save("history", items[:HISTORY_MAX])

    def history(self, kind: str = "") -> list[dict]:
        return [h for h in self.load("history", []) if not kind or h.get("kind") == kind]

    def clear_history(self) -> None:
        self.save("history", [])
