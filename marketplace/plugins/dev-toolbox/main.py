"""Dev Toolbox — fenêtre à onglets d'outils de développeur."""

from .tools import registry
from .window import ToolboxDialog


def on_load(api):
    o = api.options
    o.group("Général")
    o.add_choice("default_tool", "Outil au démarrage", sorted(registry.TOOLS), default="Base64")
    o.add_int("font_size", "Taille du texte", default=11, min=8, max=24)
    o.add_bool("copy_result", "Copier automatiquement le résultat", default=False)
    o.group("Mots de passe")
    o.add_int("pw_length", "Longueur par défaut", default=20, min=8, max=128)
    o.add_bool("pw_symbols", "Inclure des symboles", default=True)
    o.group("Raccourci")
    o.add_shortcut("shortcut", "Ouvrir la boîte à outils", default="Ctrl+Alt+T")

    def open_toolbox(*_):
        ToolboxDialog(api, registry.TOOLS).exec()

    api.add_menu_action("Outils", "Dev Toolbox…", open_toolbox, icon="mdi:toolbox-outline", shortcut=o.get("shortcut"))
    api.add_palette_command("Dev Toolbox", open_toolbox)
    for name in ("UUID", "Horodatage"):
        api.add_palette_command(f"Dev Toolbox : {name}", lambda *_, n=name: ToolboxDialog(api, registry.TOOLS, n).exec())
