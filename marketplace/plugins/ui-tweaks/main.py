"""UI Tweaks — exemple de plugin qui modifie l'interface avec une feuille de style Qt (QSS).

Montre : add_menu_action (cases à cocher), set_stylesheet, api.settings (réglages persistants).
"""

TWEAKS = {
    "compact": (
        "Mode compact",
        "QPushButton { padding: 3px 10px; } QLineEdit, QComboBox { min-height: 22px; } "
        "QMenu::item { padding-top: 4px; padding-bottom: 4px; } QTreeView::item { min-height: 22px; }",
    ),
    "round": (
        "Coins très arrondis",
        "QPushButton, QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QGroupBox { border-radius: 10px; }",
    ),
    "bigfont": (
        "Police plus grande",
        "* { font-size: 14px; }",
    ),
    "thin_scroll": (
        "Barres de défilement fines",
        "QScrollBar:vertical { width: 6px; } QScrollBar:horizontal { height: 6px; }",
    ),
}


def on_load(api):
    state = api.settings.get("enabled", [])

    def apply():
        api.set_stylesheet("\n".join(TWEAKS[k][1] for k in TWEAKS if k in state))

    def make_toggle(key):
        def toggle(checked):
            if checked and key not in state:
                state.append(key)
            elif not checked and key in state:
                state.remove(key)
            api.settings.set("enabled", list(state))
            apply()
        return toggle

    for key, (label, _qss) in TWEAKS.items():
        api.add_menu_action("Plugins/UI Tweaks", label, make_toggle(key),
                            checkable=True, checked=key in state, icon="mdi:palette-outline")
    apply()
