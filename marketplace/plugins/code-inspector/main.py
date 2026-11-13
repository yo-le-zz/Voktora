"""Code Inspector — comprendre un projet : architecture, dépendances, appels, ponts Python × Rust, qualité, exports."""

from PySide6.QtWidgets import QDialog, QVBoxLayout

from .storage.store import Store
from .ui.widget import InspectorWidget


def on_load(api):
    o = api.options
    o.group("Analyse")
    o.add_text("ignore", "Dossiers/fichiers à ignorer (séparés par des virgules)", default="")
    o.add_bool("auto_analyze", "Analyser automatiquement à l'ouverture d'un projet", default=False)
    store = Store(api.data_path("cache"))

    def make_widget(ctx=None):
        return InspectorWidget(api, store, api.run_async, {"ignore": o.get("ignore"), "auto_analyze": o.get("auto_analyze")})

    api.add_project_tab("Inspecteur", lambda ctx: make_widget(ctx), icon="mdi:graph-outline")

    def open_dialog(*_):
        root = api.current_project()
        dlg = QDialog(api.main_window())
        dlg.setWindowTitle("Code Inspector")
        dlg.resize(1100, 760)
        w = make_widget()
        QVBoxLayout(dlg).addWidget(w)
        w.set_project(root)
        dlg.exec()

    api.add_menu_action("Outils", "Code Inspector…", open_dialog, icon="mdi:graph-outline", shortcut="Ctrl+Alt+I")
    api.add_palette_command("Code Inspector : analyser le projet", open_dialog)
