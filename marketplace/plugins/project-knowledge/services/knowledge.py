"""Façade : charge/enregistre l'index et le wiki d'un projet, actualise (incrémental), génère les pages."""

from __future__ import annotations

from pathlib import Path

from ..core.index import ProjectIndex
from ..core.wiki import Wiki


class Knowledge:
    def __init__(self, store, project):
        self.store, self.project = store, str(project)
        self.root = Path(project)
        data = store.load(self.project, "index", {})
        self.index = ProjectIndex.from_dict(self.root, data) if data else ProjectIndex(self.root)
        self.wiki = Wiki(store.load(self.project, "wiki", {}))

    def refresh(self, progress=None, cancel=None, regenerate: bool = True) -> dict:
        report = self.index.update(progress, cancel)
        if regenerate:
            report["pages_updated"] = self.wiki.generate(self.index, self.root.name, self.index.changes)
        report["stale_pages"] = self.wiki.stale(self.index)
        self.save()
        return report

    def save(self) -> None:
        self.store.save(self.project, "index", self.index.to_dict())
        self.store.save(self.project, "wiki", self.wiki.pages)

    def save_page(self, name: str, text: str) -> None:
        self.wiki.set_page(name, text, generated=False, index=self.index)
        self.store.save(self.project, "wiki", self.wiki.pages)

    def delete_page(self, name: str) -> None:
        self.wiki.delete(name)
        self.store.save(self.project, "wiki", self.wiki.pages)
