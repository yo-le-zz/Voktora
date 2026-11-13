from __future__ import annotations

from ..services import layout, views
from .common import svg_view

VIEW_BUILDERS = {
    "architecture": lambda a, **kw: views.architecture(a.graph, **kw),
    "files": lambda a, **kw: views.files(a.graph, **kw),
    "classes": lambda a, **kw: views.classes(a.graph, **kw),
    "calls": lambda a, **kw: views.calls(a.graph, **kw),
    "ffi": lambda a, **kw: views.ffi(a.graph),
}


def render(analysis, view_name: str = "architecture", dark: bool = False, **kwargs) -> str:
    v = VIEW_BUILDERS[view_name](analysis, **kwargs)
    return svg_view(v, layout.layout(v), dark)


def export(analysis, path, view_name: str = "architecture", dark: bool = False, **kwargs) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(analysis, view_name, dark, **kwargs))
