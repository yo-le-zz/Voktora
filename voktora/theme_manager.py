"""
theme_manager.py — Gestionnaire de thèmes Voktora
Version : 1.0.1
Thèmes built-in : default (dark), light, crt_cyberpunk.
Thèmes personnalisés stockés dans data/themes/*.json.

Deux formats de thème sont supportés :
  • Format natif  : {"name":…, "colors": {"base":…, "text":…, …}}
  • Format legacy : {"name":…, "colors": {"background":…, "accent":…, …}}
                   (+ champ "gradients" optionnel ignoré sans erreur)

API publique :
    THEMES_DIR              : Path
    get_available_themes()  : list[str]
    load_theme(name)        : dict   (toujours normalisé en format natif)
    set_theme(name)         : None   (persiste dans app_config, sans toucher au reste)
    apply_theme_to_app(app) : None
    import_theme(path)      : str
    export_theme(name, dest): Path
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import core

# ── Chemins ───────────────────────────────────────────────────────────────────

THEMES_DIR: Path = core.get_data_dir() / "themes"


def _ensure_themes_dir() -> None:
    THEMES_DIR.mkdir(parents=True, exist_ok=True)


# ── Mapping legacy → natif ────────────────────────────────────────────────────
# Convertit les clés d'un thème "format ancien" vers les clés internes.

_LEGACY_MAP: dict[str, str] = {
    "background":   "base",
    "surface":      "mantle",
    "panel":        "surface0",
    "text":         "text",
    "text_secondary": "subtext1",
    "accent":       "blue",
    "primary":      "primary",
    "success":      "green",
    "warning":      "yellow",
    "danger":       "red",
    "border":       "surface2",
    # variantes
    "bg":           "base",
    "fg":           "text",
    "highlight":    "blue",
    "secondary":    "subtext0",
    "error":        "red",
    "info":         "sapphire",
}

_NATIVE_KEYS = {
    "base", "mantle", "crust", "surface0", "surface1", "surface2",
    "overlay0", "overlay1", "text", "subtext1", "subtext0",
    "blue", "lavender", "sapphire", "sky", "teal", "green",
    "yellow", "peach", "maroon", "red", "mauve", "flamingo", "rosewater",
    "primary",
}


def _normalize_colors(colors: dict) -> dict:
    """
    Accepte n'importe quel dict de couleurs (natif ou legacy) et retourne
    un dict normalisé avec les clés internes.
    Les clés déjà natives sont gardées telles quelles.
    Les clés legacy sont mappées. Les clés inconnues sont ignorées.
    Les clés manquantes sont complétées par des valeurs raisonnables
    dérivées de ce qui est présent.
    """
    out: dict[str, str] = {}

    for k, v in colors.items():
        if k in _NATIVE_KEYS:
            out[k] = v
        elif k in _LEGACY_MAP:
            out[_LEGACY_MAP[k]] = v

    # Complétion des clés manquantes à partir des clés présentes
    base    = out.get("base", "#1e1e2e")
    text    = out.get("text", "#cdd6f4")
    blue    = out.get("blue", "#89b4fa")
    surface = out.get("surface0", out.get("mantle", "#313244"))

    defaults = {
        "base":      base,
        "mantle":    _darken(base, 0.05),
        "crust":     _darken(base, 0.10),
        "surface0":  surface,
        "surface1":  out.get("surface1", _lighten(surface, 0.05)),
        "surface2":  out.get("surface2", _lighten(surface, 0.10)),
        "overlay0":  out.get("overlay0", "#6c7086"),
        "overlay1":  out.get("overlay1", "#7f849c"),
        "text":      text,
        "subtext1":  out.get("subtext1", _mix(text, base, 0.8)),
        "subtext0":  out.get("subtext0", _mix(text, base, 0.6)),
        "blue":      blue,
        "lavender":  out.get("lavender", blue),
        "sapphire":  out.get("sapphire", blue),
        "sky":       out.get("sky",      blue),
        "teal":      out.get("teal",     out.get("green", "#94e2d5")),
        "green":     out.get("green",    "#a6e3a1"),
        "yellow":    out.get("yellow",   "#f9e2af"),
        "peach":     out.get("peach",    "#fab387"),
        "maroon":    out.get("maroon",   "#eba0ac"),
        "red":       out.get("red",      "#f38ba8"),
        "mauve":     out.get("mauve",    "#cba6f7"),
        "flamingo":  out.get("flamingo", "#f2cdcd"),
        "rosewater": out.get("rosewater","#f5e0dc"),
        "primary":   out.get("primary",  blue),
    }

    for k, v in defaults.items():
        out.setdefault(k, v)

    return out


# ── Petits helpers de manipulation de couleurs ────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        return 128, 128, 128


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}"


def _darken(h: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(h)
    d = int(255 * amount)
    return _rgb_to_hex(r - d, g - d, b - d)


def _lighten(h: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(h)
    d = int(255 * amount)
    return _rgb_to_hex(r + d, g + d, b + d)


def _mix(a: str, b: str, ratio: float) -> str:
    r1, g1, b1 = _hex_to_rgb(a)
    r2, g2, b2 = _hex_to_rgb(b)
    return _rgb_to_hex(
        int(r1 * ratio + r2 * (1 - ratio)),
        int(g1 * ratio + g2 * (1 - ratio)),
        int(b1 * ratio + b2 * (1 - ratio)),
    )


# ══════════════════════════════════════════════════════════════════════════════
# THÈMES BUILT-IN
# ══════════════════════════════════════════════════════════════════════════════

_BUILTIN_THEMES: dict[str, dict[str, Any]] = {

    "default": {
        "name":        "Default Dark",
        "description": "Thème sombre par défaut — palette Catppuccin Mocha.",
        "colors": {
            "base":       "#1e1e2e",
            "mantle":     "#181825",
            "crust":      "#11111b",
            "surface0":   "#313244",
            "surface1":   "#45475a",
            "surface2":   "#585b70",
            "overlay0":   "#6c7086",
            "overlay1":   "#7f849c",
            "text":       "#cdd6f4",
            "subtext1":   "#bac2de",
            "subtext0":   "#a6adc8",
            "blue":       "#89b4fa",
            "lavender":   "#b4befe",
            "sapphire":   "#74c7ec",
            "sky":        "#89dceb",
            "teal":       "#94e2d5",
            "green":      "#a6e3a1",
            "yellow":     "#f9e2af",
            "peach":      "#fab387",
            "maroon":     "#eba0ac",
            "red":        "#f38ba8",
            "mauve":      "#cba6f7",
            "flamingo":   "#f2cdcd",
            "rosewater":  "#f5e0dc",
            "primary":    "#89b4fa",
        },
    },

    "light": {
        "name":        "Light",
        "description": "Thème clair — palette Catppuccin Latte.",
        "colors": {
            "base":       "#eff1f5",
            "mantle":     "#e6e9ef",
            "crust":      "#dce0e8",
            "surface0":   "#ccd0da",
            "surface1":   "#bcc0cc",
            "surface2":   "#acb0be",
            "overlay0":   "#9ca0b0",
            "overlay1":   "#8c8fa1",
            "text":       "#4c4f69",
            "subtext1":   "#5c5f77",
            "subtext0":   "#6c6f85",
            "blue":       "#1e66f5",
            "lavender":   "#7287fd",
            "sapphire":   "#209fb5",
            "sky":        "#04a5e5",
            "teal":       "#179299",
            "green":      "#40a02b",
            "yellow":     "#df8e1d",
            "peach":      "#fe640b",
            "maroon":     "#e64553",
            "red":        "#d20f39",
            "mauve":      "#8839ef",
            "flamingo":   "#dd7878",
            "rosewater":  "#dc8a78",
            "primary":    "#1e66f5",
        },
    },

    "crt_cyberpunk": {
        "name":        "CRT Cyberpunk",
        "description": "Deep navy, phosphor green, electric blue — terminal cyberpunk.",
        "colors": {
            "base":       "#0a0e1a",
            "mantle":     "#060910",
            "crust":      "#030508",
            "surface0":   "#0d1526",
            "surface1":   "#121d32",
            "surface2":   "#1a2844",
            "overlay0":   "#2a3d5e",
            "overlay1":   "#3a527a",
            "text":       "#00ff88",
            "subtext1":   "#00cc6a",
            "subtext0":   "#009950",
            "blue":       "#00d4ff",
            "lavender":   "#7b8cff",
            "sapphire":   "#00b8d9",
            "sky":        "#00e5ff",
            "teal":       "#00bfa5",
            "green":      "#00ff88",
            "yellow":     "#ffea00",
            "peach":      "#ff6e00",
            "maroon":     "#ff2d55",
            "red":        "#ff073a",
            "mauve":      "#d600ff",
            "flamingo":   "#ff4d9e",
            "rosewater":  "#ff80ab",
            "primary":    "#00d4ff",
        },
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE
# ══════════════════════════════════════════════════════════════════════════════

def get_available_themes() -> list[str]:
    _ensure_themes_dir()
    names = list(_BUILTIN_THEMES.keys())
    for f in sorted(THEMES_DIR.glob("*.json")):
        if f.stem not in names:
            names.append(f.stem)
    return names


def load_theme(name: str) -> dict:
    """
    Charge un thème par son nom et le normalise (legacy → natif).
    Lève KeyError si introuvable.
    """
    if name in _BUILTIN_THEMES:
        t = dict(_BUILTIN_THEMES[name])
        t["colors"] = _normalize_colors(t["colors"])
        return t

    _ensure_themes_dir()
    path = THEMES_DIR / f"{name}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Format de thème invalide.")
            # Normaliser les couleurs (supporte legacy et natif)
            if "colors" in data:
                data["colors"] = _normalize_colors(data["colors"])
            # Ignorer "gradients" sans erreur
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON invalide dans le thème '{name}': {e}") from e

    raise KeyError(f"Thème introuvable : '{name}'")


def set_theme(name: str) -> None:
    """
    Persiste le thème dans app_config SANS écraser le reste du config.json.
    Utilise set_app_config() qui fait la fusion correctement.
    """
    app_cfg = core.get_app_config()
    app_cfg["theme"] = name
    core.set_app_config(app_cfg)


def apply_theme_to_app(app) -> None:
    if app is None:
        return
    app_cfg    = core.get_app_config()
    theme_name = app_cfg.get("theme", "default")
    try:
        theme = load_theme(theme_name)
    except (KeyError, ValueError):
        theme = load_theme("default")
    qss = _build_qss(theme)
    app.setStyleSheet(qss)


def import_theme(path: Path) -> str:
    _ensure_themes_dir()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Le fichier doit être un objet JSON.")
        # Accepter les deux formats (avec ou sans 'colors')
        if "colors" not in data and not any(k in data for k in _LEGACY_MAP):
            raise ValueError(
                "Le fichier ne contient ni clé 'colors' ni couleurs reconnues."
            )
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalide : {e}") from e

    name = path.stem
    if name in _BUILTIN_THEMES:
        raise FileExistsError(
            f"Le nom '{name}' est réservé à un thème built-in. Renommez le fichier."
        )
    dest = THEMES_DIR / f"{name}.json"
    if dest.exists():
        raise FileExistsError(
            f"Un thème nommé '{name}' existe déjà. Supprimez-le d'abord."
        )
    shutil.copy2(path, dest)
    return name


def export_theme(name: str, dest: Path) -> Path:
    theme = load_theme(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(theme, indent=2, ensure_ascii=False), encoding="utf-8")
    return dest


# ══════════════════════════════════════════════════════════════════════════════
# GÉNÉRATION QSS
# ══════════════════════════════════════════════════════════════════════════════

def _c(theme: dict, key: str, fallback: str = "#888888") -> str:
    return theme.get("colors", {}).get(key, fallback)


def _build_qss(theme: dict) -> str:
    c = lambda key, fb="#888888": _c(theme, key, fb)

    base_hex = c("base", "#1e1e2e").lstrip("#")
    try:
        r, g, b = int(base_hex[0:2], 16), int(base_hex[2:4], 16), int(base_hex[4:6], 16)
        is_light = (r * 0.299 + g * 0.587 + b * 0.114) > 127
    except Exception:
        is_light = False

    is_terminal = "crt" in theme.get("name", "").lower() or "terminal" in theme.get("name", "").lower()
    font_family = "'JetBrains Mono', 'Consolas', 'DejaVu Sans Mono', monospace" if is_terminal else "sans-serif"
    font_size   = "12px" if is_terminal else "13px"

    return f"""
/* ── Voktora QSS — thème : {theme.get('name', 'custom')} ── */

QWidget {{
    background-color: {c('base')};
    color: {c('text')};
    font-family: {font_family};
    font-size: {font_size};
    border: none;
    outline: none;
}}
QMainWindow, QDialog {{
    background-color: {c('base')};
}}
QGroupBox {{
    background-color: {c('mantle')};
    border: 1px solid {c('surface1')};
    border-radius: 6px;
    margin-top: 18px;
    padding: 8px 6px 6px 6px;
    font-weight: bold;
    color: {c('subtext1')};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: {c('blue')};
    font-weight: bold;
}}
QPushButton {{
    background-color: {c('surface0')};
    color: {c('text')};
    border: 1px solid {c('surface2')};
    border-radius: 5px;
    padding: 5px 14px;
}}
QPushButton:hover {{
    background-color: {c('surface1')};
    border-color: {c('blue')};
    color: {c('blue')};
}}
QPushButton:pressed {{
    background-color: {c('surface2')};
}}
QPushButton:disabled {{
    background-color: {c('mantle')};
    color: {c('overlay0')};
    border-color: {c('surface0')};
}}
QPushButton#primary {{
    background-color: {c('blue')};
    color: {c('base')};
    border: none;
    font-weight: bold;
}}
QPushButton#primary:hover {{
    background-color: {c('lavender')};
    color: {c('base')};
}}
QPushButton#primary:pressed {{
    background-color: {c('sapphire')};
}}
QPushButton#danger {{
    background-color: {c('red')};
    color: {c('base')};
    border: none;
    font-weight: bold;
}}
QPushButton#danger:hover {{
    background-color: {c('maroon')};
}}
QPushButton#subtle {{
    background-color: transparent;
    color: {c('subtext0')};
    border: 1px solid {c('surface1')};
}}
QPushButton#subtle:hover {{
    background-color: {c('surface0')};
    color: {c('text')};
}}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {c('mantle')};
    color: {c('text')};
    border: 1px solid {c('surface1')};
    border-radius: 4px;
    padding: 4px 7px;
    selection-background-color: {c('blue')};
    selection-color: {c('base')};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {c('blue')};
}}
QLineEdit:disabled, QTextEdit:disabled {{
    background-color: {c('crust')};
    color: {c('overlay0')};
}}
QComboBox {{
    background-color: {c('mantle')};
    color: {c('text')};
    border: 1px solid {c('surface1')};
    border-radius: 4px;
    padding: 4px 7px;
    min-width: 80px;
}}
QComboBox:hover {{
    border-color: {c('blue')};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid {c('surface1')};
    border-radius: 0 4px 4px 0;
}}
QComboBox QAbstractItemView {{
    background-color: {c('mantle')};
    color: {c('text')};
    border: 1px solid {c('surface1')};
    selection-background-color: {c('surface0')};
    selection-color: {c('blue')};
    outline: none;
}}
QListWidget, QTreeWidget, QTableWidget {{
    background-color: {c('mantle')};
    color: {c('text')};
    border: 1px solid {c('surface0')};
    border-radius: 4px;
    alternate-background-color: {c('crust')};
    gridline-color: {c('surface0')};
    outline: none;
}}
QListWidget::item, QTreeWidget::item, QTableWidget::item {{
    padding: 4px 6px;
    border-radius: 3px;
}}
QListWidget::item:selected, QTreeWidget::item:selected,
QTableWidget::item:selected {{
    background-color: {c('surface0')};
    color: {c('blue')};
}}
QListWidget::item:hover, QTreeWidget::item:hover,
QTableWidget::item:hover {{
    background-color: {c('surface0')};
}}
QHeaderView::section {{
    background-color: {c('crust')};
    color: {c('subtext0')};
    border: none;
    border-right: 1px solid {c('surface0')};
    border-bottom: 1px solid {c('surface0')};
    padding: 4px 8px;
    font-weight: bold;
}}
QTabWidget::pane {{
    border: 1px solid {c('surface0')};
    border-radius: 4px;
    background-color: {c('base')};
}}
QTabBar::tab {{
    background-color: {c('mantle')};
    color: {c('subtext0')};
    border: 1px solid {c('surface0')};
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    padding: 6px 16px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {c('base')};
    color: {c('blue')};
    border-color: {c('surface1')};
    font-weight: bold;
}}
QTabBar::tab:hover:!selected {{
    background-color: {c('surface0')};
    color: {c('text')};
}}
QMenuBar {{
    background-color: {c('mantle')};
    color: {c('text')};
    border-bottom: 1px solid {c('surface0')};
}}
QMenuBar::item:selected {{
    background-color: {c('surface0')};
    color: {c('blue')};
}}
QMenu {{
    background-color: {c('mantle')};
    color: {c('text')};
    border: 1px solid {c('surface1')};
    border-radius: 4px;
    padding: 4px 0;
}}
QMenu::item {{
    padding: 5px 28px 5px 16px;
}}
QMenu::item:selected {{
    background-color: {c('surface0')};
    color: {c('blue')};
}}
QMenu::separator {{
    height: 1px;
    background: {c('surface0')};
    margin: 4px 8px;
}}
QScrollBar:vertical {{
    background: {c('mantle')};
    width: 10px;
    border-radius: 5px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {c('surface2')};
    min-height: 24px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c('blue')};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {c('mantle')};
    height: 10px;
    border-radius: 5px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {c('surface2')};
    min-width: 24px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {c('blue')};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QSplitter::handle {{
    background-color: {c('surface0')};
}}
QSplitter::handle:hover {{
    background-color: {c('blue')};
}}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical   {{ height: 3px; }}
QProgressBar {{
    background-color: {c('mantle')};
    color: {c('text')};
    border: 1px solid {c('surface0')};
    border-radius: 4px;
    text-align: center;
    height: 14px;
}}
QProgressBar::chunk {{
    background-color: {c('blue')};
    border-radius: 3px;
}}
QCheckBox, QRadioButton {{
    color: {c('text')};
    spacing: 8px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {c('surface2')};
    border-radius: 3px;
    background-color: {c('mantle')};
}}
QCheckBox::indicator:checked {{
    background-color: {c('blue')};
    border-color: {c('blue')};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QRadioButton::indicator:checked {{
    background-color: {c('blue')};
    border-color: {c('blue')};
}}
QSlider::groove:horizontal {{
    background: {c('surface0')};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {c('blue')};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {c('blue')};
    border-radius: 2px;
}}
QToolTip {{
    background-color: {c('surface0')};
    color: {c('text')};
    border: 1px solid {c('surface2')};
    border-radius: 4px;
    padding: 4px 8px;
    opacity: 230;
}}
QLabel {{
    color: {c('text')};
    background: transparent;
}}
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {c('surface1')};
}}
QStatusBar {{
    background-color: {c('crust')};
    color: {c('subtext0')};
    border-top: 1px solid {c('surface0')};
}}
QStatusBar::item {{ border: none; }}
QToolBar {{
    background-color: {c('mantle')};
    border-bottom: 1px solid {c('surface0')};
    spacing: 4px;
    padding: 2px 4px;
}}
QToolButton {{
    background-color: transparent;
    color: {c('text')};
    border-radius: 4px;
    padding: 4px 6px;
}}
QToolButton:hover {{
    background-color: {c('surface0')};
    color: {c('blue')};
}}
QToolButton:pressed {{
    background-color: {c('surface1')};
}}
QDockWidget::title {{
    background-color: {c('mantle')};
    color: {c('subtext1')};
    padding: 4px 8px;
    border-bottom: 1px solid {c('surface0')};
    font-weight: bold;
}}
"""
