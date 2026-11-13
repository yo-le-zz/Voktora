"""Exports : JSON, Markdown, SVG, HTML interactif, PDF, et exports spécifiques Python / Rust / mixte."""

from __future__ import annotations

FORMATS = {"json": ".json", "md": ".md", "svg": ".svg", "html": ".html", "pdf": ".pdf",
           "python": ".md", "rust": ".md", "mixed": ".md"}
LABELS = {"json": "JSON (graphe complet)", "md": "Markdown (rapport)", "svg": "SVG (vue courante)", "html": "HTML interactif",
          "pdf": "PDF (rapport)", "python": "Python (modules, classes, décorateurs)", "rust": "Rust (caisses, traits, impl)",
          "mixed": "Python × Rust (ponts)"}


def export(analysis, kind: str, path, view: str = "architecture", dark: bool = False) -> None:
    if kind == "json":
        from . import json_x
        json_x.export(analysis, path)
    elif kind == "md":
        from . import md_x
        md_x.export(analysis, path)
    elif kind == "svg":
        from . import svg_x
        svg_x.export(analysis, path, view, dark)
    elif kind == "html":
        from . import html_x
        html_x.export(analysis, path)
    elif kind == "pdf":
        from . import pdf_x
        pdf_x.export(analysis, path)
    elif kind in ("python", "rust", "mixed"):
        from . import specific
        specific.export(analysis, kind, path)
    else:
        raise ValueError(f"Format inconnu : {kind}")
