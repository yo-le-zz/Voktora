#!/usr/bin/env python3
"""Génère les thèmes de la boutique (marketplace/shops/themes/items/<id>/) depuis la table ci-dessous.

  python tools/gen_shop_themes.py        # (ré)écrit les dossiers puis lancez : python tools/shop_tool.py build-index

Chaque ligne : id, nom, description, base, texte, bleu, mauve, vert, rouge, jaune, couleur principale.
Les palettes s'inspirent de thèmes d'éditeur connus (le nom d'origine est cité dans la description).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "marketplace" / "shops" / "themes" / "items"

T = [
    ("dracula", "Dracula", "Violet profond, accents vifs, inspiré de Dracula.", "#282a36", "#f8f8f2", "#8be9fd", "#bd93f9", "#50fa7b", "#ff5555", "#f1fa8c", "#bd93f9"),
    ("gruvbox-dark", "Gruvbox Dark", "Tons chauds contrastés, inspiré de Gruvbox.", "#282828", "#ebdbb2", "#83a598", "#d3869b", "#b8bb26", "#fb4934", "#fabd2f", "#fe8019"),
    ("gruvbox-light", "Gruvbox Light", "Papier crème, inspiré de Gruvbox (clair).", "#fbf1c7", "#3c3836", "#076678", "#8f3f71", "#79740e", "#9d0006", "#b57614", "#af3a03"),
    ("tokyo-night", "Tokyo Night", "Bleu nuit et néons discrets, inspiré de Tokyo Night.", "#1a1b26", "#c0caf5", "#7aa2f7", "#bb9af7", "#9ece6a", "#f7768e", "#e0af68", "#7aa2f7"),
    ("tokyo-storm", "Tokyo Storm", "Variante plus claire de Tokyo Night.", "#24283b", "#c0caf5", "#7aa2f7", "#bb9af7", "#9ece6a", "#f7768e", "#e0af68", "#bb9af7"),
    ("one-dark", "One Dark", "Gris-bleu sobre, inspiré d'Atom One Dark.", "#282c34", "#abb2bf", "#61afef", "#c678dd", "#98c379", "#e06c75", "#e5c07b", "#61afef"),
    ("monokai", "Monokai", "Fond sombre, vert et rose électriques, inspiré de Monokai.", "#272822", "#f8f8f2", "#66d9ef", "#ae81ff", "#a6e22e", "#f92672", "#e6db74", "#a6e22e"),
    ("solarized-dark", "Solarized Dark", "Palette scientifique à faible fatigue visuelle.", "#002b36", "#93a1a1", "#268bd2", "#6c71c4", "#859900", "#dc322f", "#b58900", "#2aa198"),
    ("solarized-light", "Solarized Light", "Solarized sur fond clair.", "#fdf6e3", "#586e75", "#268bd2", "#6c71c4", "#859900", "#dc322f", "#b58900", "#2aa198"),
    ("latte", "Catppuccin Latte", "Pastels doux sur fond clair, inspiré de Catppuccin.", "#eff1f5", "#4c4f69", "#1e66f5", "#8839ef", "#40a02b", "#d20f39", "#df8e1d", "#8839ef"),
    ("frappe", "Catppuccin Frappé", "Pastels sur gris-bleu moyen, inspiré de Catppuccin.", "#303446", "#c6d0f5", "#8caaee", "#ca9ee6", "#a6d189", "#e78284", "#e5c890", "#ca9ee6"),
    ("macchiato", "Catppuccin Macchiato", "Pastels sur fond sombre, inspiré de Catppuccin.", "#24273a", "#cad3f5", "#8aadf4", "#c6a0f6", "#a6da95", "#ed8796", "#eed49f", "#c6a0f6"),
    ("rose-pine", "Rosé Pine", "Rose poudré et pin, inspiré de Rosé Pine.", "#191724", "#e0def4", "#9ccfd8", "#c4a7e7", "#31748f", "#eb6f92", "#f6c177", "#ebbcba"),
    ("rose-pine-dawn", "Rosé Pine Dawn", "Rosé Pine clair.", "#faf4ed", "#575279", "#56949f", "#907aa9", "#286983", "#b4637a", "#ea9d34", "#d7827e"),
    ("everforest", "Everforest", "Verts forestiers apaisants, inspiré d'Everforest.", "#2d353b", "#d3c6aa", "#7fbbb3", "#d699b6", "#a7c080", "#e67e80", "#dbbc7f", "#a7c080"),
    ("ayu-dark", "Ayu Dark", "Noir bleuté et orange, inspiré d'Ayu.", "#0b0e14", "#bfbdb6", "#59c2ff", "#d2a6ff", "#aad94c", "#f07178", "#e6b450", "#ffb454"),
    ("ayu-mirage", "Ayu Mirage", "Ayu à contraste adouci.", "#1f2430", "#cccac2", "#73d0ff", "#dfbfff", "#d5ff80", "#f28779", "#ffd173", "#ffcc66"),
    ("ayu-light", "Ayu Light", "Ayu clair, lumineux.", "#fafafa", "#5c6166", "#399ee6", "#a37acc", "#86b300", "#f07171", "#f2ae49", "#ff9940"),
    ("material-ocean", "Material Ocean", "Bleu-gris profond, inspiré de Material Theme.", "#0f111a", "#a6accd", "#82aaff", "#c792ea", "#c3e88d", "#f07178", "#ffcb6b", "#82aaff"),
    ("palenight", "Palenight", "Violet-gris nocturne, inspiré de Material Palenight.", "#292d3e", "#a6accd", "#82aaff", "#c792ea", "#c3e88d", "#f07178", "#ffcb6b", "#c792ea"),
    ("nightfox", "Nightfox", "Bleus froids et rouille, inspiré de Nightfox.", "#192330", "#cdcecf", "#719cd6", "#9d79d6", "#81b29a", "#c94f6d", "#dbc074", "#719cd6"),
    ("kanagawa", "Kanagawa", "Encre japonaise et pastels fanés, inspiré de Kanagawa.", "#1f1f28", "#dcd7ba", "#7e9cd8", "#957fb8", "#98bb6c", "#e82424", "#e6c384", "#7e9cd8"),
    ("cobalt", "Cobalt", "Bleu cobalt saturé, inspiré de Cobalt.", "#193549", "#ffffff", "#0088ff", "#9a5feb", "#3ad900", "#ff628c", "#ffc600", "#ffc600"),
    ("github-dark", "GitHub Dark", "Gris GitHub sobre.", "#0d1117", "#e6edf3", "#58a6ff", "#bc8cff", "#3fb950", "#f85149", "#d29922", "#58a6ff"),
    ("github-light", "GitHub Light", "Blanc GitHub, très lisible.", "#ffffff", "#1f2328", "#0969da", "#8250df", "#1a7f37", "#cf222e", "#9a6700", "#0969da"),
    ("synthwave", "Synthwave", "Violet nuit et rose fluo, esprit années 80.", "#262335", "#ffffff", "#36f9f6", "#b893ce", "#72f1b8", "#fe4450", "#fede5d", "#ff7edb"),
    ("oceanic", "Oceanic", "Bleu océan, inspiré d'Oceanic Next.", "#1b2b34", "#d8dee9", "#6699cc", "#c594c5", "#99c794", "#ec5f67", "#fac863", "#6699cc"),
    ("horizon", "Horizon", "Crépuscule rose et orangé.", "#1c1e26", "#d5d8da", "#26bbd9", "#b877db", "#29d398", "#e95678", "#fab795", "#e95678"),
    ("zenburn", "Zenburn", "Gris chauds peu fatigants, inspiré de Zenburn.", "#3f3f3f", "#dcdccc", "#8cd0d3", "#dc8cc3", "#7f9f7f", "#cc9393", "#f0dfaf", "#f0dfaf"),
    ("tomorrow-night", "Tomorrow Night", "Classique des éditeurs, doux et neutre.", "#1d1f21", "#c5c8c6", "#81a2be", "#b294bb", "#b5bd68", "#cc6666", "#f0c674", "#81a2be"),
    ("night-owl", "Night Owl", "Bleu nuit pensé pour la nuit, inspiré de Night Owl.", "#011627", "#d6deeb", "#82aaff", "#c792ea", "#addb67", "#ef5350", "#ecc48d", "#7fdbca"),
    ("moonlight", "Moonlight", "Indigo lunaire, inspiré de Moonlight.", "#222436", "#c8d3f5", "#82aaff", "#c099ff", "#c3e88d", "#ff757f", "#ffc777", "#82aaff"),
    ("poimandres", "Poimandres", "Minimal bleu-vert sur fond encre.", "#1b1e28", "#a6accd", "#89ddff", "#a6accd", "#5de4c7", "#d0679d", "#fffac2", "#5de4c7"),
    ("oled-black", "OLED Noir", "Noir pur : économise les écrans OLED.", "#000000", "#e6e6e6", "#4aa3ff", "#b48cff", "#4ade80", "#ff5c5c", "#fbbf24", "#4aa3ff"),
    ("papier", "Papier", "Blanc cassé encre noire, pour lire longtemps.", "#f7f5f0", "#2b2b2b", "#2f6fb2", "#7a4fa0", "#3a7d44", "#b3392f", "#a8741a", "#2f6fb2"),
    ("sepia", "Sépia", "Fond jauni façon livre ancien.", "#f4ecd8", "#433422", "#2b6a8c", "#7b4a8b", "#4f7a28", "#a1362a", "#a77310", "#8b5e34"),
    ("contraste-sombre", "Contraste élevé (sombre)", "Contrastes maximaux, accessibilité.", "#000000", "#ffffff", "#6fc3ff", "#ff9cf1", "#7dff8a", "#ff6b6b", "#ffee58", "#ffee58"),
    ("contraste-clair", "Contraste élevé (clair)", "Contrastes maximaux sur fond blanc.", "#ffffff", "#000000", "#0033cc", "#6a0dad", "#006400", "#b00000", "#7a5200", "#0033cc"),
    ("foret", "Forêt", "Verts profonds et mousse.", "#14201a", "#d6e5d8", "#6fb3b8", "#b48ead", "#8fcf7a", "#d9776b", "#d9c26b", "#8fcf7a"),
    ("sakura", "Sakura", "Roses de cerisier sur fond clair.", "#fff5f7", "#4a3340", "#4d7ea8", "#a05a9e", "#5a8f5a", "#c2415d", "#b9822b", "#d6567a"),
    ("lavande", "Lavande", "Violets doux, lumineux.", "#f5f2fb", "#322b4a", "#4668c5", "#7b4fd0", "#3d8b5f", "#c0434f", "#a97a1e", "#7b4fd0"),
    ("charbon", "Charbon", "Gris neutre, accent orange.", "#1e1e1e", "#d4d4d4", "#569cd6", "#c586c0", "#6a9955", "#f44747", "#dcdcaa", "#ce9178"),
    ("minuit", "Minuit", "Bleu marine très sombre.", "#0a1128", "#dbe4ff", "#5b8def", "#9d7bff", "#46d19a", "#ff6b81", "#ffd166", "#5b8def"),
    ("corail", "Corail", "Fond sombre chaud, accent corail.", "#231a1d", "#f1e4e1", "#6db7c9", "#c49be0", "#8fcb8a", "#ff6f61", "#f2c46d", "#ff6f61"),
    ("menthe-glacee", "Menthe glacée", "Clair, vert d'eau et bleu pâle.", "#effaf6", "#1f3a33", "#2b7a9e", "#6b5bb0", "#2f8f5b", "#c0473d", "#a1761c", "#2f8f5b"),
]


def main() -> None:
    for tid, name, desc, base, text, blue, mauve, green, red, yellow, primary in T:
        folder = ROOT / tid
        folder.mkdir(parents=True, exist_ok=True)
        colors = {"base": base, "text": text, "blue": blue, "mauve": mauve, "green": green, "red": red, "yellow": yellow,
                  "primary": primary}
        item = {"id": tid, "name": name, "version": "1.0.0", "author": "yolezz", "description": desc,
                "tags": ["thème", "clair" if _light(base) else "sombre"],
                "colors": [base, text, blue, mauve, green, red, yellow]}
        (folder / "item.json").write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (folder / "theme.json").write_text(json.dumps({"name": name, "description": desc, "colors": colors},
                                                      indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(len(T), "thèmes écrits")


def _light(hex_color: str) -> bool:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return (0.299 * r + 0.587 * g + 0.114 * b) > 140


if __name__ == "__main__":
    main()
