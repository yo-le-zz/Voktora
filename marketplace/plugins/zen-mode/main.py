"""Zen Mode — masque les barres pour se concentrer.

Montre : add_toolbar_button, add_menu_action avec raccourci, api.main_window() (accès à la fenêtre).
"""


def on_load(api):
    window = api.main_window()
    state = {"zen": False}

    def parts():
        return [window.menuBar(), window.statusBar(), window._main_splitter.widget(0)]

    def toggle():
        state["zen"] = not state["zen"]
        for widget in parts():
            widget.setVisible(not state["zen"])
        api.notify("Mode zen activé — Ctrl+Shift+Z pour revenir" if state["zen"] else "Mode zen désactivé", 3000)

    api.add_toolbar_button("Zen", toggle, icon="mdi:meditation", tooltip="Masquer les barres (Ctrl+Shift+Z)")
    api.add_menu_action("Plugins/Zen Mode", "Activer / désactiver", toggle, shortcut="Ctrl+Shift+Z",
                        icon="mdi:meditation")

    def restore():
        for widget in parts():
            widget.setVisible(True)

    api.on("on_quit", lambda ctx: restore())
