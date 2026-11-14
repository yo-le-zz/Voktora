"""Zen Mode 1.1 — masque les barres pour se concentrer ; ce qui est masqué est réglable.

Montre : options, add_toolbar_button, add_menu_action avec raccourci, api.main_window(), on_quit, nettoyage au déchargement.
"""

from PySide6.QtWidgets import QWidget

PARTS = ("menu", "status", "sidebar")


def find_parts(window, wanted) -> list[QWidget]:
    """Widgets à masquer selon les choix (les éléments introuvables sont simplement ignorés)."""
    found: list[QWidget] = []
    if "menu" in wanted and window.menuBar() is not None:
        found.append(window.menuBar())
    if "status" in wanted and window.statusBar() is not None:
        found.append(window.statusBar())
    if "sidebar" in wanted:
        splitter = window.findChild(QWidget, "main_splitter") or window.__dict__.get("_main_splitter")
        if splitter is not None and splitter.count() > 0:
            found.append(splitter.widget(0))
    return found


class Zen:
    def __init__(self, window, options, notify):
        self.window, self.options, self.notify = window, options, notify
        self.active, self._hidden, self._was_fullscreen = False, [], False

    def wanted(self) -> list[str]:
        return [p for p in PARTS if self.options.get(f"hide_{p}")]

    def enter(self) -> None:
        self._hidden = [w for w in find_parts(self.window, self.wanted()) if w.isVisibleTo(self.window)]
        for w in self._hidden:
            w.setVisible(False)
        self._was_fullscreen = self.window.isFullScreen()
        if self.options.get("fullscreen") and not self._was_fullscreen:
            self.window.showFullScreen()
        self.active = True

    def leave(self) -> None:
        for w in self._hidden:
            w.setVisible(True)
        self._hidden = []
        if self.options.get("fullscreen") and not self._was_fullscreen and self.window.isFullScreen():
            self.window.showNormal()
        self.active = False

    def toggle(self) -> None:
        self.leave() if self.active else self.enter()
        if self.options.get("announce"):
            self.notify("Mode zen activé — Ctrl+Shift+Z pour revenir" if self.active else "Mode zen désactivé", 3000)


def on_load(api):
    o = api.options
    o.group("Éléments masqués")
    o.add_bool("hide_menu", "Barre de menus", default=True)
    o.add_bool("hide_status", "Barre d'état", default=True)
    o.add_bool("hide_sidebar", "Liste des projets (barre latérale)", default=True)
    o.group("Comportement")
    o.add_bool("fullscreen", "Passer aussi en plein écran", default=False)
    o.add_bool("announce", "Afficher une notification", default=True)
    zen = Zen(api.main_window(), o, api.notify)
    api.add_toolbar_button("Zen", zen.toggle, icon="mdi:meditation", tooltip="Masquer les barres (Ctrl+Shift+Z)")
    api.add_menu_action("Plugins/Zen Mode", "Activer / désactiver", zen.toggle, icon="mdi:meditation")
    api.add_shortcut("Ctrl+Shift+Z", zen.toggle, "Mode zen")        # reste actif même quand la barre de menus est masquée
    api.on("on_quit", lambda ctx: zen.leave())
