"""
Voktora — plugins.bridge (1.1.1)
Pont commun des plugins non-Python (JavaScript, Rust) vers `PluginAPI` : un nom de méthode + des arguments JSON.

  • nom : camelCase (JS) ou snake_case (Rust) → méthode publique de l'API ; « options.xxx » → api.options ; « settings.xxx » ;
  • les arguments `{"__fn": id}` deviennent des fonctions Python qui rappellent le plugin ;
  • retour : JSON, ou {"__error": "..."} (le plugin décide quoi en faire) ; les objets Qt ne traversent pas (→ null).
Les permissions sont vérifiées par l'API elle-même : ce pont ne les contourne pas, il ne fait que traduire.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import detect

BLOCKED = frozenset({"main_window", "run_async", "icon", "run"})           # objets Qt / threads : hors de portée


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set | frozenset | tuple):
        return list(value)
    return None


def context_to_dict(ctx: Any) -> dict:
    return {"projectPath": str(ctx.project_path) if ctx.project_path else None,
            "data": getattr(ctx, "data", {}), "args": getattr(ctx, "args", {})}


class ApiBridge:
    def __init__(self, api: Any, make_callback: Callable[[int], Callable[..., Any]]) -> None:
        self.api = api
        self._make_callback = make_callback

    def decode(self, value: Any) -> Any:
        if isinstance(value, dict):
            if set(value) == {"__fn"}:
                return self._make_callback(int(value["__fn"]))
            return {k: self.decode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.decode(v) for v in value]
        return value

    def dispatch(self, name: str, args: list) -> str:
        """JSON du résultat, ou {"__error": ...}. Ne lève jamais."""
        try:
            target: Any = self.api
            method = detect.camel_to_snake(name)
            if name.startswith("options."):
                target, method = self.api.options, detect.camel_to_snake(name[len("options."):])
            elif name.startswith("settings."):
                target, method = self.api.settings, detect.camel_to_snake(name[len("settings."):])
            if method.startswith("_") or method in BLOCKED or not callable(getattr(target, method, None)):
                raise AttributeError(f"« {name} » n'existe pas dans l'API de plugins.")
            result = getattr(target, method)(*[self.decode(a) for a in args])
            return "" if result is None else json.dumps(result, default=json_default)
        except Exception as exc:  # noqa: BLE001 — renvoyé au plugin
            return json.dumps({"__error": f"{type(exc).__name__}: {exc}"})
