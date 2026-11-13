"""Couleurs, enregistrement JSON, validation (pur Python)."""

import json
import re

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
KEYS = {"base": "Fond", "text": "Texte", "primary": "Couleur principale", "blue": "Bleu", "mauve": "Mauve",
        "green": "Vert", "red": "Rouge", "yellow": "Jaune"}
DEFAULT_COLORS = {"dark": {"base": "#1e1e2e", "text": "#cdd6f4", "primary": "#89b4fa", "blue": "#89b4fa", "mauve": "#cba6f7",
                           "green": "#a6e3a1", "red": "#f38ba8", "yellow": "#f9e2af"},
                  "light": {"base": "#eff1f5", "text": "#4c4f69", "primary": "#1e66f5", "blue": "#1e66f5", "mauve": "#8839ef",
                            "green": "#40a02b", "red": "#d20f39", "yellow": "#df8e1d"}}
FILE = "themes.json"


def slug(name: str) -> str:
    return "-".join("".join(c.lower() if c.isalnum() else " " for c in name).split()) or "theme"


def clean(colors: dict) -> dict:
    out = {k: str(colors[k]) for k in KEYS if k in colors and HEX.match(str(colors[k]))}
    missing = [k for k in KEYS if k not in out]
    if missing:
        raise ValueError("Couleurs manquantes ou invalides : " + ", ".join(missing))
    return out


def parse_import(text: str) -> dict:
    data = json.loads(text)
    if "colors" not in data:
        data = {"name": "Importé", "colors": data}
    return {"name": str(data.get("name", "Importé"))[:60], "description": str(data.get("description", ""))[:200],
            "colors": clean(data["colors"])}


def export(name: str, colors: dict, description: str = "", author: str = "") -> str:
    return json.dumps({"name": name, "description": description, "author": author, "colors": clean(colors)},
                      ensure_ascii=False, indent=2)


def load_saved(api) -> dict:
    try:
        raw = json.loads(api.read_text(FILE, "{}") or "{}")
    except ValueError:
        return {}
    out = {}
    for theme_id, data in raw.items():
        try:
            out[theme_id] = {"name": data["name"], "description": data.get("description", ""), "colors": clean(data["colors"])}
        except (KeyError, ValueError, TypeError):
            continue
    return out


def save(api, saved: dict) -> None:
    api.write_text(FILE, json.dumps(saved, ensure_ascii=False, indent=1))
