#!/usr/bin/env python3
"""Génère les packs d'icônes de la boutique (marketplace/shops/icons/items/<id>/*.svg).

Une géométrie (grille 24×24) = (formes remplissables, traits) ; chaque pack applique son style : épaisseur, extrémités,
remplissage, couleur. `currentColor` suit la couleur du texte du thème (Voktora le remplace à l'affichage).
Les noms de fichiers sont des noms d'icônes MDI : une icône absente du pack garde l'icône d'origine.

  python tools/gen_shop_icons.py && python tools/shop_tool.py validate && python tools/shop_tool.py build-index
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "marketplace" / "shops" / "icons" / "items"

# id : (formes remplissables, traits, [noms MDI])
G: dict[str, tuple[str, str, list[str]]] = {
    "folder": ('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>', "",
               ["folder", "folder-outline", "folder-multiple", "folder-star"]),
    "folder-open": ('<path d="M3 19l2.5-8H22l-2.5 8z"/>', '<path d="M3 19V7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v2"/>',
                    ["folder-open", "folder-open-outline"]),
    "folder-plus": ('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
                    '<path d="M12 10v6M9 13h6"/>', ["folder-plus", "folder-plus-outline"]),
    "file": ('<path d="M6 3h8l4 4v14H6z"/>', '<path d="M14 3v4h4"/>', ["file", "file-outline"]),
    "file-document": ('<path d="M6 3h8l4 4v14H6z"/>', '<path d="M14 3v4h4M9 12h6M9 16h6"/>',
                      ["file-document", "file-document-outline", "text-box-outline", "note-text-outline"]),
    "plus": ("", '<path d="M12 5v14M5 12h14"/>', ["plus", "plus-thick"]),
    "plus-circle": ('<circle cx="12" cy="12" r="9"/>', '<path d="M12 8v8M8 12h8"/>', ["plus-circle-outline", "plus-circle"]),
    "minus": ("", '<path d="M5 12h14"/>', ["minus"]),
    "minus-circle": ('<circle cx="12" cy="12" r="9"/>', '<path d="M8 12h8"/>', ["minus-circle-outline", "minus-circle"]),
    "close": ("", '<path d="M6 6l12 12M18 6L6 18"/>', ["close", "window-close"]),
    "check": ("", '<path d="M5 12.5l4.5 4.5L19 7"/>', ["check", "check-bold"]),
    "check-circle": ('<circle cx="12" cy="12" r="9"/>', '<path d="M8 12.5l3 3 5-6"/>', ["check-circle-outline", "check-circle"]),
    "pencil": ('<path d="M4 20l1-4L16.5 4.5a2 2 0 0 1 3 3L8 19z"/>', '<path d="M14 7l3 3"/>', ["pencil", "pencil-outline"]),
    "pencil-circle": ('<circle cx="12" cy="12" r="9"/>', '<path d="M8.5 15.5l.7-2.8 5.3-5.3a1.4 1.4 0 0 1 2 2l-5.3 5.3z"/>',
                      ["pencil-circle-outline", "pencil-circle"]),
    "delete": ('<path d="M7 7l1 13h8l1-13z"/>', '<path d="M5 7h14M9 7V4h6v3M10 11v6M14 11v6"/>',
               ["delete", "delete-outline", "trash-can", "trash-can-outline"]),
    "magnify": ('<circle cx="10.5" cy="10.5" r="6"/>', '<path d="M15 15l5 5"/>', ["magnify"]),
    "magnify-scan": ("", '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/>'
                     '<circle cx="12" cy="12" r="3.5"/>', ["magnify-scan"]),
    "cog": ('<circle cx="12" cy="12" r="3"/>', '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
            ["cog", "cog-outline", "tune"]),
    "play": ('<path d="M7 4l13 8-13 8z"/>', "", ["play", "play-outline", "play-circle-outline"]),
    "pause": ("", '<path d="M8 5v14M16 5v14"/>', ["pause"]),
    "pause-circle": ('<circle cx="12" cy="12" r="9"/>', '<path d="M10 9v6M14 9v6"/>', ["pause-circle-outline", "pause-circle"]),
    "stop": ('<rect x="6" y="6" width="12" height="12" rx="1"/>', "", ["stop"]),
    "refresh": ("", '<path d="M20 11a8 8 0 1 0-2 5.5M20 4v7h-7"/>', ["refresh", "reload", "sync"]),
    "update": ("", '<path d="M12 7v5l3 2M21 12a9 9 0 1 1-3-6.7M21 4v5h-5"/>', ["update"]),
    "history": ("", '<path d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5M12 8v4l3 2"/>', ["history", "backup-restore", "restore", "restore-alert"]),
    "star": ('<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>', "", ["star", "star-outline"]),
    "puzzle": ('<path d="M10 4a2 2 0 0 1 4 0v2h4v4h-2a2 2 0 0 0 0 4h2v4H4v-4h2a2 2 0 0 0 0-4H4V6h6z"/>', "",
               ["puzzle", "puzzle-outline"]),
    "alert-circle": ('<circle cx="12" cy="12" r="9"/>', '<path d="M12 7.5v5.5M12 16.5v.5"/>', ["alert-circle-outline", "alert-circle"]),
    "alert": ('<path d="M12 3l10 18H2z"/>', '<path d="M12 10v5M12 18v.5"/>', ["alert", "alert-outline"]),
    "information": ('<circle cx="12" cy="12" r="9"/>', '<path d="M12 11v6M12 7.5v.5"/>', ["information-outline", "information"]),
    "help": ('<circle cx="12" cy="12" r="9"/>', '<path d="M9.5 9.5a2.6 2.6 0 1 1 3.6 2.4c-.8.4-1.1 1-1.1 1.8M12 17v.5"/>',
             ["help-circle-outline", "help-circle"]),
    "git": ('<circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="8" r="2"/>',
            '<path d="M6 8v8M18 10c0 5-8 3-10 7"/>', ["git", "source-branch", "source-fork"]),
    "console": ('<rect x="3" y="4" width="18" height="16" rx="2"/>', '<path d="M7 9l3 3-3 3M12 16h5"/>',
                ["console", "console-line"]),
    "code-braces": ("", '<path d="M9 4C6 4 7 9 4 12c3 3 2 8 5 8M15 4c3 0 2 5 5 8-3 3-2 8-5 8"/>',
                    ["code-braces", "code-json", "xml"]),
    "code-tags": ("", '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 5l-4 14"/>', ["code-tags", "language-python", "language-javascript"]),
    "arrow-up": ("", '<path d="M12 19V5M6 11l6-6 6 6"/>', ["arrow-up", "arrow-up-bold"]),
    "arrow-down": ("", '<path d="M12 5v14M6 13l6 6 6-6"/>', ["arrow-down", "arrow-down-bold"]),
    "arrow-left": ("", '<path d="M19 12H5M11 6l-6 6 6 6"/>', ["arrow-left", "chevron-left"]),
    "arrow-right": ("", '<path d="M5 12h14M13 6l6 6-6 6"/>', ["arrow-right", "chevron-right"]),
    "content-save": ('<path d="M5 3h11l3 3v15H5z"/>', '<path d="M8 3v6h7V3M8 21v-7h8v7"/>',
                     ["content-save", "content-save-outline", "content-save-plus-outline", "floppy"]),
    "harddisk": ('<rect x="3" y="13" width="18" height="7" rx="2"/>', '<path d="M3 13l3-8h12l3 8M7 16.5h2"/>', ["harddisk", "database-outline"]),
    "shield": ('<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>', "", ["shield-outline", "shield"]),
    "shield-check": ('<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>', '<path d="M8.5 12l2.5 2.5L16 9.5"/>',
                     ["shield-check-outline", "shield-check"]),
    "palette": ('<path d="M12 3a9 9 0 1 0 0 18c1.5 0 2-1 1.5-2.2-.6-1.3.3-2.8 1.8-2.8H18a3 3 0 0 0 3-3C21 6.5 17 3 12 3z"/>',
                '<path d="M7.5 11h.01M10 7.5h.01M14.5 7.5h.01M17 11h.01"/>', ["palette-outline", "palette", "format-paint"]),
    "storefront": ('<path d="M4 9l1-5h14l1 5v11H4z"/>', '<path d="M4 9a2.5 2.5 0 0 0 5 0 2.5 2.5 0 0 0 6 0 2.5 2.5 0 0 0 5 0M10 20v-6h4v6"/>',
                   ["storefront-outline", "storefront", "store"]),
    "chart-bar": ("", '<path d="M5 20V11M12 20V5M19 20v-7"/>', ["chart-bar", "poll"]),
    "chart-line": ("", '<path d="M3 20h18M4 16l5-5 4 3 7-8"/>', ["chart-line", "chart-timeline-variant"]),
    "tag": ('<path d="M3 12V4h8l10 10-8 8z"/>', '<path d="M7.5 8h.01"/>', ["tag-outline", "tag"]),
    "circle": ('<circle cx="12" cy="12" r="8"/>', "", ["circle", "circle-outline", "circle-medium"]),
    "flash": ('<path d="M13 2L5 14h6l-1 8 8-12h-6z"/>', "", ["flash", "lightning-bolt", "lightning-bolt-outline"]),
    "rocket": ('<path d="M14 4c3 0 6 3 6 6-3 5-5 7-8 9l-3-3c2-3 4-5 5-12z"/>', '<path d="M7 14l-3 1 2-4M9 17l-1 3 4-2"/><circle cx="14.5" cy="9.5" r="1.3"/>',
               ["rocket-launch", "rocket", "rocket-outline"]),
    "broom": ('<path d="M4 21c0-4 3-8 6-11l4 4c-3 3-7 6-10 7z"/>', '<path d="M19 3l-7 8"/>', ["broom"]),
    "compare": ("", '<path d="M9 3H5v18h4M15 3h4v18h-4M12 6v12"/>', ["compare", "compare-horizontal"]),
    "swap": ("", '<path d="M4 8h14M14 4l4 4-4 4M20 16H6M10 12l-4 4 4 4"/>', ["swap-horizontal", "swap-vertical"]),
    "tune": ("", '<path d="M4 7h10M18 7h2M14 5v4M4 17h2M10 17h10M6 15v4"/>', ["tune-variant", "tune-vertical", "equalizer"]),
    "home": ('<path d="M5 10l7-6 7 6v10H5z"/>', '<path d="M10 20v-6h4v6"/>', ["home", "home-outline"]),
    "download": ("", '<path d="M12 4v12M7 11l5 5 5-5M5 20h14"/>', ["download", "tray-arrow-down"]),
    "upload": ("", '<path d="M12 16V4M7 9l5-5 5 5M5 20h14"/>', ["upload", "tray-arrow-up"]),
    "link": ("", '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
             ["link", "link-variant"]),
    "lock": ('<rect x="5" y="11" width="14" height="10" rx="2"/>', '<path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
             ["lock", "lock-outline", "shield-lock-outline"]),
    "key": ('<circle cx="8" cy="15" r="4"/>', '<path d="M11 12l9-9M16 7l3 3"/>', ["key", "key-variant", "key-outline"]),
    "eye": ('<circle cx="12" cy="12" r="3"/>', '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/>', ["eye", "eye-outline"]),
    "bell": ('<path d="M6 17v-6a6 6 0 0 1 12 0v6l2 2H4z"/>', '<path d="M10 21h4"/>', ["bell", "bell-outline"]),
    "heart": ('<path d="M12 20s-8-5-8-11a4.5 4.5 0 0 1 8-2.5A4.5 4.5 0 0 1 20 9c0 6-8 11-8 11z"/>', "", ["heart", "heart-outline"]),
    "bookmark": ('<path d="M6 3h12v18l-6-4-6 4z"/>', "", ["bookmark", "bookmark-outline"]),
    "clock": ('<circle cx="12" cy="12" r="9"/>', '<path d="M12 7v5l3 2"/>', ["clock-outline", "clock", "timer-outline"]),
    "calendar": ('<rect x="4" y="5" width="16" height="16" rx="2"/>', '<path d="M4 10h16M8 3v4M16 3v4"/>', ["calendar", "calendar-outline"]),
    "account": ('<circle cx="12" cy="8" r="4"/>', '<path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>', ["account", "account-outline"]),
    "package": ('<path d="M12 3l8 4v10l-8 4-8-4V7z"/>', '<path d="M4 7l8 4 8-4M12 11v10"/>',
                ["package-variant-closed", "package-variant", "package"]),
    "database": ('<ellipse cx="12" cy="6" rx="7" ry="3"/>', '<path d="M5 6v12c0 1.7 3 3 7 3s7-1.3 7-3V6M5 12c0 1.7 3 3 7 3s7-1.3 7-3"/>',
                 ["database"]),
    "cloud": ('<path d="M7 18a4 4 0 0 1-.5-8A6 6 0 0 1 18 9a4.5 4.5 0 0 1 0 9z"/>', "", ["cloud", "cloud-outline"]),
    "web": ('<circle cx="12" cy="12" r="9"/>', '<path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>', ["web", "earth"]),
    "filter": ('<path d="M3 5h18l-7 8v6l-4 2v-8z"/>', "", ["filter", "filter-outline"]),
    "menu": ("", '<path d="M4 7h16M4 12h16M4 17h16"/>', ["menu"]),
    "dots": ('<circle cx="12" cy="5" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="12" cy="19" r="1.2"/>', "",
             ["dots-vertical"]),
    "copy": ('<rect x="9" y="9" width="11" height="11" rx="2"/>', '<path d="M5 15H4V5a2 2 0 0 1 2-2h10v1"/>',
             ["content-copy", "file-multiple-outline"]),
    "send": ('<path d="M3 11l18-8-8 18-2-8z"/>', "", ["send", "send-outline"]),
    "image": ('<rect x="3" y="4" width="18" height="16" rx="2"/>', '<circle cx="9" cy="10" r="1.6"/><path d="M4 18l5-5 4 4 3-3 4 4"/>',
              ["image", "image-outline"]),
    "monitor": ('<rect x="3" y="4" width="18" height="12" rx="2"/>', '<path d="M8 20h8M12 16v4"/>', ["monitor", "desktop-classic"]),
    "gamepad": ('<rect x="3" y="8" width="18" height="10" rx="4"/>', '<path d="M8 11v4M6 13h4M16 12h.01M18 14h.01"/>', ["controller", "gamepad-variant"]),
    "music": ("", '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>', ["music-note", "music"]),
    "wrench": ('<path d="M14.5 6a4 4 0 0 0 5 5L10 20.5a2.1 2.1 0 0 1-3-3z"/>', "", ["wrench", "tools", "hammer-wrench"]),
    "target": ('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/>', '<path d="M12 12h.01"/>', ["target", "bullseye-arrow"]),
}

PALETTE = {"fold": "#f9b44c", "act": "#4c9ffe", "ok": "#3ecf8e", "bad": "#f4617f", "warn": "#f5c542", "misc": "#a78bfa"}
CATEGORY = {
    "folder": "fold", "folder-open": "fold", "folder-plus": "fold", "delete": "bad", "close": "bad", "minus-circle": "bad",
    "alert": "warn", "alert-circle": "warn", "star": "warn", "flash": "warn", "bell": "warn", "bookmark": "warn",
    "check": "ok", "check-circle": "ok", "plus": "ok", "plus-circle": "ok", "play": "ok", "shield-check": "ok", "git": "ok",
    "puzzle": "misc", "palette": "misc", "storefront": "misc", "rocket": "misc", "heart": "bad",
}

# id, nom, description, style
PACKS = [
    ("trait-fin", "Trait fin", "Contours fins de 1,25 px, extrémités arrondies ; suit la couleur du thème.", dict(w=1.25, cap="round", join="round")),
    ("trait-epais", "Trait épais", "Contours de 2,5 px, très lisibles, extrémités arrondies.", dict(w=2.5, cap="round", join="round")),
    ("carre", "Carré", "Angles vifs et extrémités plates, esprit technique.", dict(w=2, cap="butt", join="miter")),
    ("duo-ton", "Duo-ton", "Contour plus remplissage translucide de la couleur du thème.", dict(w=1.75, cap="round", join="round", fill=0.22)),
    ("plein", "Plein", "Formes pleines pour un style compact et marqué.", dict(w=1.5, cap="round", join="round", fill=1.0)),
    ("accent", "Accent coloré", "Couleurs par catégorie (dossiers ambre, succès vert, danger rouge…) sur fond clair ou sombre.",
     dict(w=1.75, cap="round", join="round", accent=True, fill=0.15)),
    ("neon", "Néon", "Traits cyan lumineux, pensé pour les thèmes sombres.", dict(w=1.75, cap="round", join="round", color="#22e0ff")),
    ("pointille", "Pointillé", "Contours en pointillés légers — décoratif.", dict(w=1.5, cap="round", join="round", dash="0.1 3")),
]


def svg(gid: str, style: dict) -> str:
    area, lines, _ = G[gid]
    color = style.get("color") or (PALETTE[CATEGORY.get(gid, "act")] if style.get("accent") else "currentColor")
    fill = style.get("fill")
    attrs = (f'fill="none" stroke="{color}" stroke-width="{style["w"]}" stroke-linecap="{style["cap"]}" '
             f'stroke-linejoin="{style["join"]}"')
    if style.get("dash"):
        attrs += f' stroke-dasharray="{style["dash"]}"'
    parts = []
    if area:
        parts.append(f'<g fill="{color}" fill-opacity="{fill}">{area}</g>' if fill else area)
    if lines:
        parts.append(lines)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {attrs}>{"".join(parts)}</svg>\n'


def main() -> None:
    for pid, name, desc, style in PACKS:
        folder = ROOT / pid
        folder.mkdir(parents=True, exist_ok=True)
        count = 0
        for gid, (_a, _l, names) in G.items():
            for mdi in names:
                (folder / f"{mdi}.svg").write_text(svg(gid, style), encoding="utf-8")
                count += 1
        item = {"id": pid, "name": name, "version": "1.0.0", "author": "yolezz", "tags": ["icônes"],
                "description": f"{desc} {count} icônes ; les autres gardent l'icône d'origine."}
        (folder / "item.json").write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(len(PACKS), "packs,", sum(len(v[2]) for v in G.values()), "icônes chacun")


if __name__ == "__main__":
    main()
