"""
Voktora — markdown_lite.py (1.1.1)
Convertit du Markdown courant en HTML compatible avec le sous-ensemble de HTML de Qt (QTextBrowser).

Sûr par construction : tout le texte est échappé AVANT la mise en forme, seuls les liens http(s)/mailto
sont gardés, aucun HTML brut n'est jamais transmis. Prend en charge : titres, gras, italique, ~~barré~~,
`code`, blocs ``` avec langage, listes (à puces, numérotées, imbriquées par indentation), citations,
règles horizontales, tableaux, liens.
"""

from __future__ import annotations

import html
import re

_FENCE = re.compile(r"^\s*(```|~~~)\s*([\w+#.-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_NUMBER = re.compile(r"^(\s*)(\d{1,9})[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)")
_URL_OK = re.compile(r"^(https?://|mailto:)", re.IGNORECASE)

DEFAULT_COLORS = {"code_bg": "#11111b", "code_fg": "#cdd6f4", "inline_bg": "#313244", "link": "#89b4fa",
                  "quote": "#7f849c", "border": "#45475a", "head": "#cba6f7"}


def _inline(text: str, c: dict) -> str:
    """Mise en forme dans une ligne (le texte reçu est déjà échappé)."""
    spans: list[str] = []

    def stash(m: re.Match) -> str:
        spans.append(f"<code style='background:{c['inline_bg']};color:{c['code_fg']};"
                     f"font-family:monospace'>&nbsp;{m.group(1)}&nbsp;</code>")
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", stash, text)

    def link(m: re.Match) -> str:
        url = html.unescape(m.group(2))
        if not _URL_OK.match(url):
            return m.group(0)
        return f"<a href='{html.escape(url, quote=True)}' style='color:{c['link']}'>{m.group(1)}</a>"

    text = _LINK.sub(link, text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def render(text: str, colors: dict | None = None) -> str:
    """HTML (fragment) pour `text`. Tolérant aux Markdown incomplets (flux en cours d'écriture)."""
    c = {**DEFAULT_COLORS, **(colors or {})}
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    paragraph: list[str] = []
    list_stack: list[tuple[int, str]] = []          # (indentation, balise)

    def flush_paragraph() -> None:
        if paragraph:
            out.append("<p style='margin:4px 0'>" + "<br>".join(_inline(html.escape(p), c) for p in paragraph) + "</p>")
            paragraph.clear()

    def close_lists(to: int = 0) -> None:
        while len(list_stack) > to:
            out.append(f"</{list_stack.pop()[1]}>")

    while i < n:
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            flush_paragraph()
            close_lists()
            marker, lang = fence.group(1), fence.group(2)
            i += 1
            body: list[str] = []
            while i < n and not lines[i].strip().startswith(marker):
                body.append(lines[i])
                i += 1
            i += 1                                   # saute la clôture (absente si le flux n'est pas fini)
            head = (f"<div style='color:{c['quote']};font-size:11px'>{html.escape(lang)}</div>" if lang else "")
            out.append(f"<table width='100%' cellspacing='0' cellpadding='8' style='margin:6px 0'><tr>"
                       f"<td style='background:{c['code_bg']};color:{c['code_fg']}'>{head}"
                       f"<pre style='margin:0;font-family:monospace'>{html.escape(chr(10).join(body))}</pre></td></tr></table>")
            continue
        if not line.strip():
            flush_paragraph()
            close_lists()
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            close_lists()
            level = len(heading.group(1))
            size = {1: 20, 2: 17, 3: 15}.get(level, 14)
            out.append(f"<p style='margin:10px 0 4px 0;font-size:{size}px;color:{c['head']}'><b>"
                       f"{_inline(html.escape(heading.group(2)), c)}</b></p>")
            i += 1
            continue
        if _RULE.match(line):
            flush_paragraph()
            close_lists()
            out.append(f"<hr style='color:{c['border']}'>")
            i += 1
            continue
        if line.lstrip().startswith(">"):
            flush_paragraph()
            close_lists()
            quoted: list[str] = []
            while i < n and lines[i].lstrip().startswith(">"):
                quoted.append(lines[i].lstrip()[1:].lstrip())
                i += 1
            out.append(f"<blockquote style='color:{c['quote']};margin:4px 0 4px 8px'>"
                       + "<br>".join(_inline(html.escape(q), c) for q in quoted) + "</blockquote>")
            continue
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "|" in lines[i + 1]:
            flush_paragraph()
            close_lists()
            header = _split_row(line)
            i += 2
            rows: list[list[str]] = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            cells = "".join(f"<th style='border:1px solid {c['border']}' align='left'>{_inline(html.escape(h), c)}</th>"
                            for h in header)
            body_rows = "".join(
                "<tr>" + "".join(f"<td style='border:1px solid {c['border']}'>{_inline(html.escape(x), c)}</td>"
                                 for x in row) + "</tr>" for row in rows)
            out.append(f"<table cellspacing='0' cellpadding='4' style='margin:6px 0'><tr>{cells}</tr>{body_rows}</table>")
            continue
        item = _BULLET.match(line) or _NUMBER.match(line)
        if item:
            flush_paragraph()
            indent = len(item.group(1).expandtabs(4))
            tag = "ul" if _BULLET.match(line) else "ol"
            while list_stack and list_stack[-1][0] > indent:
                out.append(f"</{list_stack.pop()[1]}>")
            if not list_stack or list_stack[-1][0] < indent:
                list_stack.append((indent, tag))
                out.append(f"<{tag} style='margin:2px 0 2px 0'>")
            elif list_stack[-1][1] != tag:
                out.append(f"</{list_stack.pop()[1]}>")
                list_stack.append((indent, tag))
                out.append(f"<{tag} style='margin:2px 0 2px 0'>")
            out.append(f"<li>{_inline(html.escape(item.group(3)), c)}</li>")
            i += 1
            continue
        close_lists()
        paragraph.append(line)
        i += 1
    flush_paragraph()
    close_lists()
    return "".join(out)
