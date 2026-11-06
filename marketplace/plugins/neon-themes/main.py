"""Neon Themes — ajoute des thèmes avec register_theme.

Seules quelques couleurs sont nécessaires : Voktora complète les autres.
"""

THEMES = {
    "neon-night": ("Neon Night", {
        "base": "#0b0b1e", "text": "#f5f5ff", "blue": "#00f0ff", "mauve": "#ff2bd6",
        "green": "#39ff88", "red": "#ff3860", "yellow": "#fff95b", "primary": "#ff2bd6"}),
    "coffee": ("Coffee", {
        "base": "#2a211c", "text": "#f0e4d7", "blue": "#d4a373", "mauve": "#c08497",
        "green": "#a3b18a", "red": "#e07a5f", "yellow": "#e9c46a", "primary": "#d4a373"}),
    "mint": ("Mint", {
        "base": "#f3fbf7", "text": "#1d3b32", "blue": "#0f9d78", "mauve": "#7b61c9",
        "green": "#2e9e5b", "red": "#d64545", "yellow": "#c98a00", "primary": "#0f9d78"}),
}


def on_load(api):
    for key, (name, colors) in THEMES.items():
        api.register_theme(key, name, colors)
