"""Thèmes intégrés 1.0.6 : tous chargeables, QSS valide, texte lisible sur le fond."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "voktora"))

import theme_manager  # noqa: E402
import theme_presets  # noqa: E402


def _luminance(hex_color: str) -> float:
    def channel(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = theme_presets._rgb(hex_color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_many_presets_available(isolated_data_dir):
    names = theme_manager.get_available_themes()
    assert len(names) >= 25
    assert {"default", "light", "dracula", "nord", "tokyo_night", "high_contrast"} <= set(names)


@pytest.mark.parametrize("key", sorted(theme_presets.PRESET_THEMES))
def test_preset_is_valid_and_readable(isolated_data_dir, key):
    theme = theme_manager.load_theme(key)
    colors = theme.get("colors", theme)
    assert theme_manager._build_qss({**theme, **colors}).strip()
    assert _contrast(colors["text"], colors["base"]) >= 4.5
    assert _contrast(colors["subtext0"], colors["base"]) >= 3.0
    assert all(v.startswith("#") and len(v) == 7 for v in colors.values())
