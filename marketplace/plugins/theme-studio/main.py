"""Theme Studio — créez un thème avec aperçu en direct, exportez/importez du JSON, appliquez-le."""

from .studio import StudioDialog
from .themes import load_saved


def on_load(api):
    o = api.options
    o.group("Éditeur")
    o.add_bool("live_preview", "Aperçu en direct", default=True)
    o.add_choice("start_from", "Point de départ", ["sombre", "clair", "dernier thème"], default="dernier thème")
    o.add_text("author", "Auteur par défaut", default="")
    o.group("Application")
    o.add_bool("auto_register", "Enregistrer le thème dans Paramètres → Thèmes à chaque sauvegarde", default=True)

    saved = load_saved(api)
    for theme_id, data in saved.items():
        api.register_theme(theme_id, data["name"], data["colors"], data.get("description", ""))

    def open_studio(*_):
        StudioDialog(api, saved).exec()

    api.add_menu_action("Outils", "Theme Studio…", open_studio, icon="mdi:palette-outline")
    api.add_palette_command("Theme Studio", open_studio)

