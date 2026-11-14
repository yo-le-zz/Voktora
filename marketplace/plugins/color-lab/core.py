"""Color Lab — conversions de couleurs, contraste WCAG, palettes (sans Qt)."""

from __future__ import annotations

import colorsys
import re

RGB = tuple[int, int, int]
_HEX = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{6})$", re.I)
_FUNC = re.compile(r"^(rgb|hsl)a?\(\s*([^)]*)\)$", re.I)


def parse(text: str) -> RGB:
    """#abc, #aabbcc, rgb(1,2,3), hsl(210, 50%, 40%) → (r, g, b). ValueError si illisible."""
    t = (text or "").strip()
    m = _HEX.match(t)
    if m:
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    m = _FUNC.match(t)
    if m:
        nums = [float(x.rstrip("%").rstrip("deg")) for x in re.split(r"[,\s/]+", m.group(2).strip()) if x][:3]
        if len(nums) == 3:
            if m.group(1).lower() == "rgb":
                return tuple(max(0, min(255, round(n))) for n in nums)  # type: ignore[return-value]
            h, s, light = nums[0] % 360 / 360, max(0, min(100, nums[1])) / 100, max(0, min(100, nums[2])) / 100
            r, g, b = colorsys.hls_to_rgb(h, light, s)
            return round(r * 255), round(g * 255), round(b * 255)
    raise ValueError(f"Couleur illisible : {text!r}")


def to_hex(c: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*c)


def to_hsl(c: RGB) -> tuple[int, int, int]:
    h, light, s = colorsys.rgb_to_hls(*(v / 255 for v in c))
    return round(h * 360) % 360, round(s * 100), round(light * 100)


def formats(c: RGB) -> dict[str, str]:
    h, s, light = to_hsl(c)
    return {"HEX": to_hex(c).upper(), "RGB": f"rgb({c[0]}, {c[1]}, {c[2]})", "HSL": f"hsl({h}, {s}%, {light}%)"}


def luminance(c: RGB) -> float:
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: RGB, b: RGB) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def verdict(ratio: float) -> dict[str, bool]:
    """Seuils WCAG 2.x : texte normal AA 4,5 / AAA 7 ; grand texte AA 3 / AAA 4,5 ; composants d'interface 3."""
    return {"AA": ratio >= 4.5, "AAA": ratio >= 7, "AA grand texte": ratio >= 3, "AAA grand texte": ratio >= 4.5, "Composants (3:1)": ratio >= 3}


def best_text(bg: RGB) -> RGB:
    """Noir ou blanc, selon le meilleur contraste sur `bg`."""
    return (0, 0, 0) if contrast(bg, (0, 0, 0)) >= contrast(bg, (255, 255, 255)) else (255, 255, 255)


def fix_contrast(fg: RGB, bg: RGB, target: float = 4.5) -> RGB:
    """Éclaircit ou assombrit `fg` (teinte conservée) jusqu'au contraste visé ; renvoie noir/blanc si impossible."""
    if contrast(fg, bg) >= target:
        return fg
    h, light, s = colorsys.rgb_to_hls(*(v / 255 for v in fg))
    direction = 1 if luminance(bg) < 0.5 else -1
    for _ in range(100):
        light = max(0.0, min(1.0, light + direction * 0.01))
        cand = tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, light, s))
        if contrast(cand, bg) >= target:  # type: ignore[arg-type]
            return cand  # type: ignore[return-value]
        if light in (0.0, 1.0):
            break
    return best_text(bg)


def _rotate(c: RGB, degrees: float) -> RGB:
    h, light, s = colorsys.rgb_to_hls(*(v / 255 for v in c))
    r, g, b = colorsys.hls_to_rgb((h + degrees / 360) % 1, light, s)
    return round(r * 255), round(g * 255), round(b * 255)


def palettes(c: RGB) -> dict[str, list[RGB]]:
    h, light, s = colorsys.rgb_to_hls(*(v / 255 for v in c))

    def shade(l2):
        r, g, b = colorsys.hls_to_rgb(h, max(0, min(1, l2)), s)
        return round(r * 255), round(g * 255), round(b * 255)

    return {
        "Complémentaire": [c, _rotate(c, 180)],
        "Analogue": [_rotate(c, -30), c, _rotate(c, 30)],
        "Triade": [c, _rotate(c, 120), _rotate(c, 240)],
        "Tétrade": [c, _rotate(c, 90), _rotate(c, 180), _rotate(c, 270)],
        "Nuances": [shade(x / 100) for x in (92, 80, 65, 50, 35, 20, 10)],
    }
