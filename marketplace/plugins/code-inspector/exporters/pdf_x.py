"""Export PDF via Qt (QPdfWriter) : rapport Markdown mis en page + schéma d'architecture."""

from __future__ import annotations

import re

from ..services import layout, views
from .common import svg_view
from .md_x import report_md


def export(a, path) -> None:
    from PySide6.QtCore import QByteArray, QMarginsF, QSizeF
    from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextCursor, QTextDocument
    from PySide6.QtSvg import QSvgRenderer

    md = re.sub(r"```mermaid.*?```", "", report_md(a, max_functions=120), flags=re.S)
    doc = QTextDocument()
    doc.setMarkdown(md)
    v = views.architecture(a.graph)
    if v["nodes"]:
        svg = svg_view(v, layout.layout(v), title=False)
        r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        size = r.defaultSize()
        scale = min(1.0, 1400 / max(size.width(), 1))
        img = QImage(max(int(size.width() * scale), 1), max(int(size.height() * scale), 1), QImage.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        r.render(p)
        p.end()
        doc.addResource(3, "arch.png", img)
        cur = QTextCursor(doc)
        cur.setPosition(0)
        cur.insertHtml("<h2>Schéma d'architecture</h2><img src='arch.png' width='640'><br>")
    w = QPdfWriter(str(path))
    w.setPageSize(QPageSize(QPageSize.A4))
    w.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Millimeter)
    w.setTitle("Code Inspector")
    doc.setPageSize(QSizeF(w.width(), w.height()))
    doc.print_(w)
