"""
Voktora — plugins.options (API de plugins v5, Voktora 1.1.1)
Options de configuration d'un plugin, déclarées en une ligne chacune : Voktora construit LUI-MÊME l'onglet de
réglages (Plugins → Options), enregistre les valeurs, les synchronise entre PC et prévient le plugin des changements.

    def on_load(api):
        o = api.options
        o.group("Apparence")
        o.add_choice("style", "Style", ["clair", "sombre"], default="sombre")
        o.add_int("taille", "Taille du texte", default=12, min=8, max=32, help="en points")
        o.add_bool("gras", "Titres en gras", default=True)
        o.on_change(lambda key, value: print(key, value))
        taille = o.get("taille")

Types : bool, text, multiline, int, float, choice, color, path, shortcut. `visible_if=("clé", valeur)` masque
une option tant qu'une autre n'a pas cette valeur. Les valeurs sont toujours contrôlées (type, bornes, choix) :
un fichier de réglages modifié à la main ne peut pas donner une valeur invalide au plugin.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

OPTIONS_KEY = "_options"                      # clé dans settings.json du plugin (donc synchronisée avec lui)
TYPES = ("bool", "text", "multiline", "int", "float", "choice", "color", "path", "shortcut")
_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
MAX_TEXT = 20000
MAX_OPTIONS = 200


class OptionError(ValueError):
    """Déclaration ou valeur d'option invalide."""


@dataclass
class Option:
    key: str
    type: str
    label: str
    default: Any
    group: str = ""
    help: str = ""
    choices: list[str] = field(default_factory=list)
    min: float | None = None
    max: float | None = None
    step: float | None = None
    path_kind: str = "file"                   # file | dir | save
    visible_if: tuple[str, Any] | None = None

    def coerce(self, value: Any) -> Any:
        """Valeur contrôlée, ou OptionError. Ne modifie rien."""
        kind = self.type
        if kind == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lower() in ("true", "false", "1", "0", "oui", "non"):
                return value.lower() in ("true", "1", "oui")
            raise OptionError(f"« {self.key} » : booléen attendu.")
        if kind in ("int", "float"):
            if isinstance(value, bool) or not isinstance(value, int | float | str):
                raise OptionError(f"« {self.key} » : nombre attendu.")
            try:
                number = int(value) if kind == "int" else float(value)
            except ValueError as exc:
                raise OptionError(f"« {self.key} » : nombre attendu.") from exc
            if self.min is not None:
                number = max(number, int(self.min) if kind == "int" else self.min)
            if self.max is not None:
                number = min(number, int(self.max) if kind == "int" else self.max)
            return number
        if not isinstance(value, str):
            raise OptionError(f"« {self.key} » : texte attendu.")
        if len(value) > MAX_TEXT:
            raise OptionError(f"« {self.key} » : texte trop long.")
        if kind == "choice":
            if value not in self.choices:
                raise OptionError(f"« {self.key} » : valeur hors de {self.choices}.")
        elif kind == "color" and not _COLOR.match(value):
            raise OptionError(f"« {self.key} » : couleur #rrggbb attendue.")
        elif kind in ("text", "path", "shortcut") and "\n" in value:
            raise OptionError(f"« {self.key} » : une seule ligne attendue.")
        return value


@dataclass
class OptionButton:
    label: str
    handler: Callable[[], None]
    group: str = ""
    help: str = ""


class PluginOptions:
    """Options d'UN plugin. Créée à chaque chargement du plugin ; `store` = PluginSettings du plugin."""

    def __init__(self, store: Any, on_error: Callable[[str], None] | None = None) -> None:
        self._store = store
        self._group = ""
        self._options: dict[str, Option] = {}
        self.buttons: list[OptionButton] = []
        self._listeners: list[Callable[[str, Any], None]] = []
        self._on_error = on_error or (lambda message: None)

    # -- déclaration ----------------------------------------------------------------
    def group(self, name: str) -> PluginOptions:
        """Les options déclarées ensuite sont rangées sous ce titre."""
        self._group = str(name)[:60]
        return self

    def _add(self, key: str, kind: str, label: str, default: Any, **extra: Any) -> Option:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_.-]{0,60}$", key or ""):
            raise OptionError(f"Clé d'option invalide : {key!r}.")
        if key in self._options:
            raise OptionError(f"L'option « {key} » est déjà déclarée.")
        if len(self._options) >= MAX_OPTIONS:
            raise OptionError("Trop d'options.")
        option = Option(key=key, type=kind, label=str(label)[:80] or key, default=default, group=self._group, **extra)
        option.default = option.coerce(default) if default is not None else option.coerce(self._zero(option))
        self._options[key] = option
        return option

    @staticmethod
    def _zero(option: Option) -> Any:
        return {"bool": False, "int": 0, "float": 0.0, "choice": (option.choices or [""])[0],
                "color": "#000000"}.get(option.type, "")

    def add_bool(self, key: str, label: str, default: bool = False, help: str = "", visible_if=None) -> None:  # noqa: A002
        self._add(key, "bool", label, default, help=help, visible_if=visible_if)

    def add_text(self, key: str, label: str, default: str = "", help: str = "", visible_if=None) -> None:  # noqa: A002
        self._add(key, "text", label, default, help=help, visible_if=visible_if)

    def add_multiline(self, key: str, label: str, default: str = "", help: str = "", visible_if=None) -> None:  # noqa: A002
        self._add(key, "multiline", label, default, help=help, visible_if=visible_if)

    def add_int(self, key: str, label: str, default: int = 0, min: int | None = None, max: int | None = None,  # noqa: A002
                step: int = 1, help: str = "", visible_if=None) -> None:  # noqa: A002
        self._add(key, "int", label, default, min=min, max=max, step=step, help=help, visible_if=visible_if)

    def add_float(self, key: str, label: str, default: float = 0.0, min: float | None = None,  # noqa: A002
                  max: float | None = None, step: float = 0.1, help: str = "", visible_if=None) -> None:  # noqa: A002
        self._add(key, "float", label, default, min=min, max=max, step=step, help=help, visible_if=visible_if)

    def add_choice(self, key: str, label: str, choices: list[str], default: str | None = None,
                   help: str = "", visible_if=None) -> None:  # noqa: A002
        if not choices or not all(isinstance(c, str) for c in choices):
            raise OptionError("add_choice : liste de textes non vide attendue.")
        self._add(key, "choice", label, default if default is not None else choices[0], choices=list(choices),
                  help=help, visible_if=visible_if)

    def add_color(self, key: str, label: str, default: str = "#89b4fa", help: str = "", visible_if=None) -> None:  # noqa: A002
        self._add(key, "color", label, default, help=help, visible_if=visible_if)

    def add_path(self, key: str, label: str, default: str = "", kind: str = "file", help: str = "",  # noqa: A002
                 visible_if=None) -> None:
        if kind not in ("file", "dir", "save"):
            raise OptionError("add_path : kind vaut « file », « dir » ou « save ».")
        self._add(key, "path", label, default, path_kind=kind, help=help, visible_if=visible_if)

    def add_shortcut(self, key: str, label: str, default: str = "", help: str = "", visible_if=None) -> None:  # noqa: A002
        self._add(key, "shortcut", label, default, help=help, visible_if=visible_if)

    def add_button(self, label: str, handler: Callable[[], None], help: str = "") -> None:  # noqa: A002
        """Bouton d'action dans le panneau (ex. « Vider le cache »)."""
        self.buttons.append(OptionButton(str(label)[:60], handler, self._group, help))

    # -- lecture / écriture -----------------------------------------------------------
    def schema(self) -> list[Option]:
        return list(self._options.values())

    def _stored(self) -> dict:
        data = self._store.get(OPTIONS_KEY, {})
        return data if isinstance(data, dict) else {}

    def get(self, key: str, default: Any = None) -> Any:
        option = self._options.get(key)
        if option is None:
            raise OptionError(f"Option inconnue : « {key} ».")
        stored = self._stored()
        if key in stored:
            try:
                return option.coerce(stored[key])
            except OptionError:
                pass                                   # valeur invalide : retombe sur la valeur par défaut
        return option.default if default is None else default

    def values(self) -> dict[str, Any]:
        return {key: self.get(key) for key in self._options}

    def set(self, key: str, value: Any) -> Any:
        option = self._options.get(key)
        if option is None:
            raise OptionError(f"Option inconnue : « {key} ».")
        clean = option.coerce(value)
        before = self.get(key)
        data = dict(self._stored())
        data[key] = clean
        self._store.set(OPTIONS_KEY, data)
        if clean != before:
            self._notify(key, clean)
        return clean

    def reset(self, key: str | None = None) -> None:
        """Remet une option (ou toutes) à sa valeur par défaut."""
        keys = [key] if key else list(self._options)
        data = {k: v for k, v in self._stored().items() if k not in keys}
        self._store.set(OPTIONS_KEY, data)
        for k in keys:
            if k in self._options:
                self._notify(k, self._options[k].default)

    def on_change(self, callback: Callable[[str, Any], None]) -> None:
        """`callback(clé, valeur)` est appelé à chaque changement (depuis le panneau de réglages ou `set`)."""
        self._listeners.append(callback)

    def _notify(self, key: str, value: Any) -> None:
        for callback in list(self._listeners):
            try:
                callback(key, value)
            except Exception as exc:  # noqa: BLE001 — un plugin ne doit pas casser le panneau
                self._on_error(f"on_change({key}) : {exc}")

    def is_visible(self, option: Option) -> bool:
        if not option.visible_if:
            return True
        other, wanted = option.visible_if
        return other in self._options and self.get(other) == wanted
