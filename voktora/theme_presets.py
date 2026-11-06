"""
Voktora — theme_presets
Thèmes intégrés supplémentaires (1.0.6). Chaque thème est décrit par quelques couleurs de base ;
les nuances (surfaces, contours, textes secondaires) sont dérivées automatiquement, ce qui garantit
des contrastes cohérents et garde ce fichier court.

Format d'une entrée : (id, nom, description, sombre?, fond, texte, primaire, accent2, rouge, vert,
jaune, orange, turquoise)
"""

from __future__ import annotations

from typing import Any


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(round(v)))) for v in (r, g, b)))


def _mix(a: str, b: str, ratio: float) -> str:
    """`ratio` de a, le reste de b."""
    (r1, g1, b1), (r2, g2, b2) = _rgb(a), _rgb(b)
    return _hex(r1 * ratio + r2 * (1 - ratio), g1 * ratio + g2 * (1 - ratio), b1 * ratio + b2 * (1 - ratio))


def build(name: str, description: str, dark: bool, base: str, text: str, primary: str, accent: str,
          red: str, green: str, yellow: str, orange: str, teal: str) -> dict[str, Any]:
    mantle = _mix(base, "#000000", 0.86 if dark else 0.95)
    crust = _mix(base, "#000000", 0.72 if dark else 0.90)
    colors = {
        "base": base, "mantle": mantle, "crust": crust,
        "surface0": _mix(base, text, 0.90), "surface1": _mix(base, text, 0.82),
        "surface2": _mix(base, text, 0.72),
        "overlay0": _mix(base, text, 0.58), "overlay1": _mix(base, text, 0.46),
        "text": text,
        "subtext1": _mix(text, base, 0.88), "subtext0": _mix(text, base, 0.74),
        "blue": primary, "lavender": _mix(primary, accent, 0.5), "sapphire": _mix(primary, teal, 0.5),
        "sky": _mix(primary, teal, 0.3), "teal": teal, "green": green, "yellow": yellow,
        "peach": orange, "maroon": _mix(red, orange, 0.7), "red": red, "mauve": accent,
        "flamingo": _mix(red, accent, 0.55), "rosewater": _mix(red, text, 0.55),
        "primary": primary,
    }
    return {"name": name, "description": description, "colors": colors}


# id, nom, description, sombre, base, texte, primaire, accent, rouge, vert, jaune, orange, turquoise
_SPECS: list[tuple] = [
    ("dracula", "Dracula", "Violet profond et néons pastel.", True,
     "#282a36", "#f8f8f2", "#bd93f9", "#ff79c6", "#ff5555", "#50fa7b", "#f1fa8c", "#ffb86c", "#8be9fd"),
    ("nord", "Nord", "Bleu glacier, calme et lisible.", True,
     "#2e3440", "#eceff4", "#88c0d0", "#b48ead", "#bf616a", "#a3be8c", "#ebcb8b", "#d08770", "#8fbcbb"),
    ("gruvbox_dark", "Gruvbox Dark", "Tons chauds rétro, contraste doux.", True,
     "#282828", "#ebdbb2", "#83a598", "#d3869b", "#fb4934", "#b8bb26", "#fabd2f", "#fe8019", "#8ec07c"),
    ("gruvbox_light", "Gruvbox Light", "Papier crème et couleurs terreuses.", False,
     "#fbf1c7", "#3c3836", "#076678", "#8f3f71", "#9d0006", "#79740e", "#b57614", "#af3a03", "#427b58"),
    ("solarized_dark", "Solarized Dark", "La classique palette Solarized sombre.", True,
     "#002b36", "#93a1a1", "#268bd2", "#6c71c4", "#dc322f", "#859900", "#b58900", "#cb4b16", "#2aa198"),
    ("solarized_light", "Solarized Light", "La classique palette Solarized claire.", False,
     "#fdf6e3", "#586e75", "#268bd2", "#6c71c4", "#dc322f", "#859900", "#b58900", "#cb4b16", "#2aa198"),
    ("tokyo_night", "Tokyo Night", "Nuit urbaine bleu-violet.", True,
     "#1a1b26", "#c0caf5", "#7aa2f7", "#bb9af7", "#f7768e", "#9ece6a", "#e0af68", "#ff9e64", "#73daca"),
    ("one_dark", "One Dark", "Le thème d'Atom, sobre et équilibré.", True,
     "#282c34", "#abb2bf", "#61afef", "#c678dd", "#e06c75", "#98c379", "#e5c07b", "#d19a66", "#56b6c2"),
    ("monokai", "Monokai", "Fond sombre, couleurs vives et franches.", True,
     "#272822", "#f8f8f2", "#66d9ef", "#ae81ff", "#f92672", "#a6e22e", "#e6db74", "#fd971f", "#66d9ef"),
    ("rose_pine", "Rosé Pine", "Rose poudré, velours et forêt de nuit.", True,
     "#191724", "#e0def4", "#c4a7e7", "#ebbcba", "#eb6f92", "#9ccfd8", "#f6c177", "#ebbcba", "#31748f"),
    ("rose_pine_dawn", "Rosé Pine Dawn", "Aube rosée, clair et doux.", False,
     "#faf4ed", "#575279", "#907aa9", "#d7827e", "#b4637a", "#56949f", "#ea9d34", "#d7827e", "#286983"),
    ("catppuccin_macchiato", "Catppuccin Macchiato", "Mocha en plus clair, toujours pastel.", True,
     "#24273a", "#cad3f5", "#8aadf4", "#c6a0f6", "#ed8796", "#a6da95", "#eed49f", "#f5a97f", "#8bd5ca"),
    ("catppuccin_frappe", "Catppuccin Frappé", "Gris-bleu tamisé et pastel.", True,
     "#303446", "#c6d0f5", "#8caaee", "#ca9ee6", "#e78284", "#a6d189", "#e5c890", "#ef9f76", "#81c8be"),
    ("ayu_mirage", "Ayu Mirage", "Bleu ardoise avec accents orangés.", True,
     "#1f2430", "#cccac2", "#73d0ff", "#dfbfff", "#f28779", "#d5ff80", "#ffd173", "#ffad66", "#95e6cb"),
    ("everforest", "Everforest", "Vert forêt apaisant, peu fatigant.", True,
     "#2d353b", "#d3c6aa", "#7fbbb3", "#d699b6", "#e67e80", "#a7c080", "#dbbc7f", "#e69875", "#83c092"),
    ("kanagawa", "Kanagawa", "Encre et vagues, inspiré de l'estampe japonaise.", True,
     "#1f1f28", "#dcd7ba", "#7e9cd8", "#957fb8", "#e82424", "#98bb6c", "#e6c384", "#ffa066", "#7aa89f"),
    ("synthwave", "Synthwave", "Néons rétro-futuristes violet et rose.", True,
     "#262335", "#ffffff", "#36f9f6", "#ff7edb", "#fe4450", "#72f1b8", "#fede5d", "#ff8b39", "#03edf9"),
    ("midnight_oled", "Midnight OLED", "Noir pur pour écrans OLED, économe.", True,
     "#000000", "#e6e6e6", "#4dabf7", "#b197fc", "#ff6b6b", "#69db7c", "#ffd43b", "#ffa94d", "#38d9a9"),
    ("sunset", "Sunset", "Crépuscule : prune, orange et corail.", True,
     "#2b1d2e", "#ffe8d6", "#ff9f68", "#ff6f91", "#ff5d73", "#9bdeac", "#ffd166", "#ff9f68", "#6bd6c9"),
    ("forest", "Forest", "Vert profond et mousse, ambiance sous-bois.", True,
     "#16211a", "#dbead8", "#7bc47f", "#c8b6ff", "#e5736d", "#8fd694", "#e3d26f", "#e8a35c", "#5ec8b4"),
    ("sakura", "Sakura", "Clair et rose pâle, léger comme un cerisier.", False,
     "#fff5f7", "#5b3a4a", "#d6336c", "#9c36b5", "#c92a2a", "#2b8a3e", "#e8890c", "#e8590c", "#0b7285"),
    ("paper", "Paper", "Clair sépia, comme une page imprimée.", False,
     "#f4ecd8", "#433422", "#2f6690", "#7b4b94", "#b23a48", "#4f772d", "#b8860b", "#c4651d", "#3a7d7c"),
    ("arctic", "Arctic", "Clair et frais, bleus glacés.", False,
     "#f0f6fb", "#1f3a52", "#1971c2", "#7048e8", "#e03131", "#2f9e44", "#e67700", "#d9480f", "#0c8599"),
    ("high_contrast", "High Contrast", "Contraste maximal pour une lisibilité accrue.", True,
     "#000000", "#ffffff", "#00b7ff", "#ff7bff", "#ff5c5c", "#4dff88", "#ffee33", "#ffa033", "#33ffe0"),
]

PRESET_THEMES: dict[str, dict[str, Any]] = {
    spec[0]: build(spec[1], spec[2], *spec[3:]) for spec in _SPECS
}
