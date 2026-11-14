"""Snippet Vault — stockage JSON de morceaux de code, recherche, export Markdown (sans Qt)."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

LANGUAGES = ["", "python", "javascript", "typescript", "rust", "go", "java", "c", "cpp", "csharp", "bash", "sql", "html", "css",
             "json", "yaml", "toml", "markdown", "texte"]


@dataclass
class Snippet:
    id: str
    title: str
    code: str = ""
    language: str = ""
    tags: list[str] = field(default_factory=list)
    project: str = ""          # chemin du projet ; vide = disponible partout
    updated: float = 0.0


def parse_tags(text: str) -> list[str]:
    seen, out = set(), []
    for t in (p.strip().lstrip("#").lower() for p in text.replace(";", ",").split(",")):
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


class Vault:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.items: dict[str, Snippet] = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = []
        self.items = {}
        for d in raw if isinstance(raw, list) else []:
            if isinstance(d, dict) and d.get("id") and d.get("title") is not None:
                self.items[str(d["id"])] = Snippet(str(d["id"]), str(d["title"]), str(d.get("code", "")), str(d.get("language", "")),
                                                   [str(t) for t in d.get("tags", [])], str(d.get("project", "")), float(d.get("updated", 0)))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(s) for s in self.items.values()], ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, title: str, code: str = "", language: str = "", tags=(), project: str = "") -> Snippet:
        s = Snippet(uuid.uuid4().hex[:10], title.strip() or "Sans titre", code, language, list(tags), project, time.time())
        self.items[s.id] = s
        self.save()
        return s

    def update(self, sid: str, **fields) -> Snippet:
        s = self.items[sid]
        if "title" in fields:
            s.title = str(fields["title"])
        if "code" in fields:
            s.code = str(fields["code"])
        if "language" in fields:
            s.language = str(fields["language"])
        if "tags" in fields:
            s.tags = list(fields["tags"])
        if "project" in fields:
            s.project = str(fields["project"])
        s.title = s.title.strip() or "Sans titre"
        s.updated = time.time()
        self.save()
        return s

    def delete(self, sid: str) -> bool:
        if self.items.pop(sid, None) is None:
            return False
        self.save()
        return True

    def search(self, query: str = "", project: str = "", tag: str = "", only_project: bool = False) -> list[Snippet]:
        """Les snippets globaux + ceux du projet ; « only_project » ne garde que ceux du projet. Titre > tags > code."""
        q = query.strip().lower()
        scored = []
        for s in self.items.values():
            if s.project and s.project != project:
                continue
            if only_project and s.project != project:
                continue
            if tag and tag.lower() not in s.tags:
                continue
            if q:
                score = (3 if q in s.title.lower() else 0) + (2 if any(q in t for t in s.tags) else 0) + (1 if q in s.code.lower() else 0)
                if not score:
                    continue
            else:
                score = 0
            scored.append((-score, -s.updated, s.title.lower(), s))
        return [t[3] for t in sorted(scored, key=lambda t: t[:3])]

    def all_tags(self) -> list[str]:
        return sorted({t for s in self.items.values() for t in s.tags})


def to_markdown(snippets: list[Snippet]) -> str:
    lines = ["# Snippets", ""]
    for s in snippets:
        lines += [f"## {s.title}", ""]
        if s.tags:
            lines += ["Étiquettes : " + ", ".join(f"`{t}`" for t in s.tags), ""]
        fence = "```"
        while fence in s.code:
            fence += "`"
        lines += [f"{fence}{s.language}", s.code.rstrip("\n"), fence, ""]
    return "\n".join(lines)


def import_markdown_free(text: str) -> list[tuple[str, str, str]]:
    """Relit un export Markdown : [(titre, langage, code)] — pour réimporter ses propres snippets."""
    out, title, lines, lang, fence = [], "", [], "", None
    for line in text.splitlines():
        if fence is None:
            if line.startswith("## "):
                title = line[3:].strip()
            elif line.startswith("```"):
                fence = len(line) - len(line.lstrip("`"))
                lang, lines = line.lstrip("`").strip(), []
        elif line.startswith("`" * fence) and not line.strip("`"):
            out.append((title or "Sans titre", lang, "\n".join(lines)))
            fence = None
        else:
            lines.append(line)
    return out
