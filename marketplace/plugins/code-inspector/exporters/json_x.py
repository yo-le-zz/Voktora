from __future__ import annotations

import json


def export(analysis, path, include_graph: bool = True) -> None:
    data = analysis.to_dict()
    if not include_graph:
        data.pop("graph", None)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
