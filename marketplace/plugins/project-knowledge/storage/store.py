"""Stockage : index (JSON compact) et wiki par projet, dans le dossier de données du plugin."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class Store:
    def __init__(self, base: Path):
        self.base = Path(base)

    def _dir(self, project) -> Path:
        d = self.base / hashlib.sha1(str(project).encode()).hexdigest()[:12]     # noqa: S324 — nom de dossier
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load(self, project, name: str, default):
        try:
            return json.loads((self._dir(project) / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def save(self, project, name: str, data) -> None:
        p = self._dir(project) / f"{name}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(p)

    def forget(self, project) -> None:
        for f in self._dir(project).glob("*.json"):
            f.unlink()
