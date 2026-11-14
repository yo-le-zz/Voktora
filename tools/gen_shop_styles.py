#!/usr/bin/env python3
"""Génère les styles QSS de la boutique (marketplace/shops/styles/items/<id>/). Aucun `url(` ni `@import` (refusés)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "marketplace" / "shops" / "styles" / "items"

S = {
    "spacieux": ("Spacieux", "Marges généreuses : interface plus aérée.", """\
QPushButton { padding: 8px 16px; min-height: 30px; }
QTreeView::item, QListView::item, QTableView::item { padding: 6px; }
QTabBar::tab { padding: 9px 18px; }
QMenu::item { padding: 7px 28px; }
QLineEdit, QComboBox, QSpinBox { padding: 6px 8px; min-height: 26px; }
"""),
    "tres-arrondi": ("Très arrondi", "Grands rayons sur boutons, champs et listes.", """\
QPushButton, QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit { border-radius: 10px; }
QListView, QTreeView, QTableView, QTabWidget::pane, QGroupBox { border-radius: 10px; }
QMenu { border-radius: 10px; padding: 4px; }
QMenu::item { border-radius: 6px; }
QToolTip { border-radius: 8px; padding: 4px 8px; }
"""),
    "onglets-soulignes": ("Onglets soulignés", "Onglets sans cadre, l'actif est souligné.", """\
QTabBar::tab { background: transparent; border: none; border-bottom: 2px solid transparent; padding: 6px 12px; }
QTabBar::tab:selected { border-bottom: 2px solid palette(highlight); }
QTabBar::tab:hover:!selected { border-bottom: 2px solid palette(mid); }
QTabWidget::pane { border: none; border-top: 1px solid palette(mid); }
"""),
    "boutons-plats": ("Boutons plats", "Boutons sans relief, fond au survol seulement.", """\
QPushButton { background: transparent; border: 1px solid transparent; padding: 4px 10px; }
QPushButton:hover { background: palette(midlight); border: 1px solid palette(mid); }
QPushButton:pressed { background: palette(mid); }
QPushButton:disabled { color: palette(mid); }
QToolButton { background: transparent; border: none; padding: 3px; }
QToolButton:hover { background: palette(midlight); }
"""),
    "barres-fines": ("Barres fines", "Barres de défilement minces et discrètes.", """\
QScrollBar:vertical { width: 8px; background: transparent; margin: 0; }
QScrollBar:horizontal { height: 8px; background: transparent; margin: 0; }
QScrollBar::handle:vertical { background: palette(mid); border-radius: 4px; min-height: 28px; }
QScrollBar::handle:horizontal { background: palette(mid); border-radius: 4px; min-width: 28px; }
QScrollBar::handle:hover { background: palette(dark); }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""),
    "sans-bordures": ("Sans bordures", "Supprime la plupart des cadres : rendu épuré.", """\
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit, QListView, QTreeView, QTableView { border: none; }
QGroupBox { border: none; margin-top: 14px; }
QFrame[frameShape="4"], QFrame[frameShape="5"] { color: palette(midlight); }
QStatusBar { border: none; }
"""),
    "lisible": ("Lisible", "Police plus grande et interlignes confortables.", """\
* { font-size: 11pt; }
QTreeView::item, QListView::item, QTableView::item { padding: 4px; }
QToolTip { font-size: 10pt; }
"""),
    "focus-visible": ("Focus visible", "Contour net sur l'élément qui a le focus (accessibilité clavier).", """\
QPushButton:focus, QToolButton:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid palette(highlight); }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border: 2px solid palette(highlight); }
QTreeView:focus, QListView:focus, QTableView:focus { border: 2px solid palette(highlight); }
QTabBar::tab:focus { border: 2px solid palette(highlight); }
"""),
    "tableau-zebre": ("Tableaux zébrés", "Lignes alternées dans les listes et tableaux.", """\
QTreeView, QListView, QTableView { alternate-background-color: palette(alternate-base); }
QHeaderView::section { padding: 4px 8px; border: none; border-bottom: 1px solid palette(mid); }
"""),
    "menus-aeres": ("Menus aérés", "Menus et listes déroulantes plus confortables.", """\
QMenu { padding: 6px; }
QMenu::item { padding: 6px 26px 6px 12px; border-radius: 5px; }
QMenu::separator { height: 1px; margin: 5px 8px; background: palette(mid); }
QComboBox QAbstractItemView { padding: 4px; }
"""),
    "dense": ("Dense", "Très compact : un maximum d'informations à l'écran.", """\
* { font-size: 9pt; }
QPushButton { padding: 2px 6px; min-height: 18px; }
QTreeView::item, QListView::item, QTableView::item { padding: 1px; }
QTabBar::tab { padding: 3px 8px; }
QMenu::item { padding: 2px 14px; }
"""),
}


def main() -> None:
    for sid, (name, desc, qss) in S.items():
        folder = ROOT / sid
        folder.mkdir(parents=True, exist_ok=True)
        assert "url(" not in qss and "@import" not in qss
        (folder / f"{sid}.qss").write_text(qss, encoding="utf-8")
        (folder / "item.json").write_text(json.dumps({"id": sid, "name": name, "version": "1.0.0", "author": "yolezz",
                                                      "description": desc, "tags": ["style"]}, indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
    print(len(S), "styles écrits")


if __name__ == "__main__":
    main()
