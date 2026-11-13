"""Wiki du projet : pages manuelles + pages générées, liens [[Page]], rétroliens, liens cassés, pages périmées, conversion Markdown → HTML."""

from __future__ import annotations

import hashlib
import re
import time
from html import escape

from . import apidoc, diagrams

LINK = re.compile(r"\[\[([^\]\|#\n]+)(?:#[^\]\|\n]*)?(?:\|([^\]\n]+))?\]\]")
PATHISH = re.compile(r"`([\w./\-]+\.[A-Za-z0-9]{1,5})`")
GENERATED = ["Vue d'ensemble", "Architecture", "API interne", "Dépendances", "Historique des changements"]


def slug(name: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", name.strip().lower()).strip().replace(" ", "-")
    return s or "page"


def links(text: str) -> list[str]:
    return [m.group(1).strip() for m in LINK.finditer(text)]


class Wiki:
    def __init__(self, pages: dict | None = None):
        self.pages: dict[str, dict] = pages or {}

    # -- pages ----------------------------------------------------------------------------------
    def set_page(self, name: str, text: str, generated: bool = False, index=None) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Nom de page vide.")
        watch = self._watch_snapshot(text, index) if index is not None else {}
        self.pages[name] = {"text": text, "generated": generated, "updated": time.time(), "watch": watch}

    def delete(self, name: str) -> None:
        self.pages.pop(name, None)

    @staticmethod
    def _watch_snapshot(text: str, index) -> dict:
        return {p: index.files[p]["sha"] for p in dict.fromkeys(PATHISH.findall(text)) if p in index.files}

    # -- liens ------------------------------------------------------------------------------------
    def broken_links(self) -> list[dict]:
        names = {n.lower() for n in self.pages}
        return [{"page": n, "target": t} for n, p in sorted(self.pages.items()) for t in dict.fromkeys(links(p["text"])) if t.lower() not in names]

    def backlinks(self, name: str) -> list[str]:
        low = name.lower()
        return sorted(n for n, p in self.pages.items() if n != name and any(t.lower() == low for t in links(p["text"])))

    def orphans(self) -> list[str]:
        return [n for n in sorted(self.pages) if n != "Vue d'ensemble" and not self.backlinks(n)]

    # -- péremption -------------------------------------------------------------------------------
    def stale(self, index) -> list[dict]:
        out = []
        for n, p in sorted(self.pages.items()):
            if p.get("generated"):
                continue
            changed = [f for f, sha in p.get("watch", {}).items() if f not in index.files or index.files[f]["sha"] != sha]
            if changed:
                out.append({"page": n, "files": changed})
        return out

    def mark_fresh(self, name: str, index) -> None:
        if name in self.pages:
            self.pages[name]["watch"] = self._watch_snapshot(self.pages[name]["text"], index)

    # -- génération --------------------------------------------------------------------------------
    def generate(self, index, project_name: str, history: list | None = None) -> list[str]:
        """(Re)génère les pages automatiques ; ne touche jamais aux pages manuelles. Retourne les pages mises à jour."""
        st = index.stats()
        edges = index.internal_imports()
        langs = "\n".join(f"- {k} : {v} lignes" for k, v in st["loc_by_lang"].items())
        roles = "\n".join(f"- {k} : {v} fichier(s)" for k, v in st["roles"].items())
        entries = [r for r, f in sorted(index.files.items()) if f["role"] == "entrée"]
        builds = [r for r, f in sorted(index.files.items()) if f["role"] == "build"]
        dirs: dict[str, int] = {}
        for r, f in index.files.items():
            if "/" in r and f["role"] not in ("documentation", "données"):
                dirs[r.split("/")[0]] = dirs.get(r.split("/")[0], 0) + 1
        pages = {
            "Vue d'ensemble": (f"# {project_name}\n\n{st['files']} fichiers indexés · {st['symbols']} symboles.\n\n## Langages\n{langs}\n\n## Rôles des fichiers\n{roles}\n\n"
                               "## Points d'entrée\n" + ("\n".join(f"- `{e}`" for e in entries) or "- aucun détecté") + "\n\n## Construction / configuration\n"
                               + ("\n".join(f"- `{b}`" for b in builds) or "- aucun fichier détecté") + "\n\nVoir aussi : [[Architecture]] · [[API interne]] · "
                               "[[Dépendances]] · [[Historique des changements]]\n"),
            "Architecture": ("# Architecture\n\n" + "\n".join(f"- **{d}/** — {n} fichier(s) de code" for d, n in sorted(dirs.items(), key=lambda kv: -kv[1]))
                             + "\n\nDiagramme : voir [[Dépendances]].\n"),
            "API interne": apidoc.api_markdown(index) + "\n",
            "Dépendances": ("# Dépendances internes\n\n" + (f"{len(edges)} relations d'import entre fichiers (résolution par nom : un import ambigu n'est pas relié).\n\n"
                            + "\n".join(f"- `{a}` → `{b}`" for a, b in edges[:300]) if edges else "Aucune relation d'import interne résolue.") + "\n"),
            "Historique des changements": "# Historique des changements\n\n" + (("\n".join(
                f"## {time.strftime('%Y-%m-%d %H:%M', time.localtime(c['time']))}\n- ajoutés : {len(c['added'])}, modifiés : {len(c['modified'])}, supprimés : {len(c['removed'])}\n"
                + "".join(f"  - `{x}`\n" for x in (c['added'] + c['modified'] + c['removed'])[:15]) for c in (history or []))) or "Aucun changement enregistré.") + "\n",
        }
        updated = []
        for name, text in pages.items():
            old = self.pages.get(name)
            if old and old["text"] == text:
                continue
            if old and not old.get("generated"):
                continue                                   # une page manuelle du même nom est conservée
            self.set_page(name, text, generated=True)
            updated.append(name)
        return updated

    def diagram_svg(self, index) -> str:
        return diagrams.svg(sorted(index.files), index.internal_imports())

    def fingerprint(self) -> str:
        return hashlib.sha1("".join(f"{n}{p['text']}" for n, p in sorted(self.pages.items())).encode()).hexdigest()[:10]    # noqa: S324


# ---------------------------------------------------------------------------------------- Markdown → HTML
def inline(text: str, page_href=lambda n: slug(n) + ".html", exists=lambda n: True) -> str:
    t = escape(text)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])_([^_]+)_(?![\w])", r"<em>\1</em>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" rel="noopener">\1</a>', t)

    def wl(m):
        name, label = m.group(1).strip(), (m.group(2) or m.group(1)).strip()
        return f'<a class="{"wiki" if exists(name) else "broken"}" href="{escape(page_href(name))}">{label}</a>'
    return LINK.sub(wl, t)


def md_to_html(text: str, page_href=lambda n: slug(n) + ".html", exists=lambda n: True) -> str:
    out, lines, i = [], text.splitlines(), 0
    in_list = False
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<pre><code>" + escape("\n".join(code)) + "</code></pre>")
        elif re.match(r"^\s*[-*] ", ln):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + inline(re.sub(r"^\s*[-*] ", "", ln), page_href, exists) + "</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            m = re.match(r"^(#{1,6})\s+(.*)", ln)
            if m:
                out.append(f"<h{len(m.group(1))}>{inline(m.group(2), page_href, exists)}</h{len(m.group(1))}>")
            elif ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1]):
                head = [c.strip() for c in ln.strip("|").split("|")]
                i += 2
                rows = []
                while i < len(lines) and lines[i].startswith("|"):
                    rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                    i += 1
                out.append("<table><tr>" + "".join(f"<th>{inline(h)}</th>" for h in head) + "</tr>"
                           + "".join("<tr>" + "".join(f"<td>{inline(c, page_href, exists)}</td>" for c in r) + "</tr>" for r in rows) + "</table>")
                continue
            elif ln.strip():
                out.append("<p>" + inline(ln, page_href, exists) + "</p>")
        i += 1
    if in_list:
        out.append("</ul>")
    return "\n".join(out)
