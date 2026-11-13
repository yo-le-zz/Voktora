"""Stockage des résultats : un dossier par projet dans les données privées du plugin (api.data_path())."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

SCHEMA = 2


class Store:
    def __init__(self, base: Path) -> None:
        self.base = Path(base)

    def project_dir(self, project_root: Path | str) -> Path:
        key = hashlib.sha1(str(Path(project_root).resolve()).encode()).hexdigest()[:16]
        d = self.base / key
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_files(self, project_root, analyzer_version: int) -> dict:
        """{chemin relatif: {"size","mtime","digest","result": dict}} — vide si absent, corrompu ou d'une autre version."""
        path = self.project_dir(project_root) / "files.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if data.get("schema") != SCHEMA or data.get("analyzer") != analyzer_version:
            return {}
        return data.get("files", {})

    def save_files(self, project_root, analyzer_version: int, files: dict) -> None:
        d = self.project_dir(project_root)
        tmp = d / "files.json.tmp"
        tmp.write_text(json.dumps({"schema": SCHEMA, "analyzer": analyzer_version, "root": str(Path(project_root).resolve()),
                                   "files": files}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, d / "files.json")

    def save_analysis(self, project_root, name: str, data: dict) -> Path:
        d = self.project_dir(project_root)
        target = d / f"{name}.json"
        tmp = d / f"{name}.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, target)
        return target

    def load_analysis(self, project_root, name: str) -> dict | None:
        try:
            return json.loads((self.project_dir(project_root) / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def forget(self, project_root) -> None:
        d = self.project_dir(project_root)
        for p in d.glob("*"):
            p.unlink(missing_ok=True)
