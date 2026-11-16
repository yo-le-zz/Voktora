"""
Voktora — accessibility (1.1.4) : réglages d'accessibilité (config « accessibility ») et audit des noms accessibles.
  • font_scale   : taille du texte de toute l'application (0.8 à 2.0) ;
  • high_contrast: contours renforcés, sélection très contrastée, bordures visibles ;
  • strong_focus : cadre de focus épais autour du widget actif (navigation au clavier) ;
  • reduce_motion: coupe les animations (transmis aux plugins/ui via la config) ;
  • label_icon_only(window) : donne un nom accessible (lecteurs d'écran) aux boutons sans texte, depuis leur info-bulle.
"""

from __future__ import annotations

import core

DEFAULTS = {"font_scale": 1.0, "high_contrast": False, "strong_focus": True, "reduce_motion": False}
SCALE_MIN, SCALE_MAX = 0.8, 2.0


def settings() -> dict:
    cfg = core.get_app_config().get("accessibility")
    merged = {**DEFAULTS, **(cfg if isinstance(cfg, dict) else {})}
    try:
        merged["font_scale"] = min(SCALE_MAX, max(SCALE_MIN, float(merged["font_scale"])))
    except (TypeError, ValueError):
        merged["font_scale"] = 1.0
    return merged


def save_settings(values: dict) -> None:
    cfg = core.get_app_config()
    cfg["accessibility"] = {**DEFAULTS, **values}
    core.set_app_config(cfg)


def stylesheet(s: dict | None = None) -> str:
    s = s or settings()
    parts: list[str] = []
    if s.get("strong_focus"):
        parts.append("QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus, QTabBar::tab:focus, QCheckBox:focus,"
                     " QListView:focus, QTreeView:focus, QTableView:focus { border: 2px solid #f9e2af; }")
    if s.get("high_contrast"):
        parts.append("QWidget { selection-background-color: #ffffff; selection-color: #000000; }"
                     " QPushButton, QLineEdit, QComboBox, QListView, QTreeView, QTableView, QTextEdit, QPlainTextEdit"
                     " { border: 1px solid #ffffff; }"
                     " QToolTip { border: 2px solid #ffffff; }")
    return "\n".join(parts)


def apply_font(app, s: dict | None = None) -> None:
    s = s or settings()
    font = app.font()
    base = app.property("_voktora_base_pt")
    if base is None:
        base = font.pointSizeF() if font.pointSizeF() > 0 else 10.0
        app.setProperty("_voktora_base_pt", base)
    font.setPointSizeF(float(base) * s["font_scale"])
    app.setFont(font)


def label_icon_only(root) -> int:
    """Nomme les boutons sans texte (icônes seules) d'après leur info-bulle. Renvoie le nombre de widgets nommés."""
    from PySide6.QtWidgets import QAbstractButton
    named = 0
    for button in root.findChildren(QAbstractButton):
        if not button.text().strip() and not button.accessibleName().strip():
            tip = button.toolTip().strip()
            if tip:
                button.setAccessibleName(tip)
                named += 1
    return named


def audit(root) -> list[str]:
    """Boutons encore sans aucun nom (ni texte, ni info-bulle, ni nom accessible) : à corriger."""
    from PySide6.QtWidgets import QAbstractButton
    return [f"{type(b).__name__}#{b.objectName()}" for b in root.findChildren(QAbstractButton)
            if not b.text().strip() and not b.accessibleName().strip() and not b.toolTip().strip()]
