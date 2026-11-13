"""Project Knowledge — recherche plein texte, wiki par projet, symboles, diagrammes et exports."""

from PySide6.QtWidgets import QDialog, QVBoxLayout

from .storage.store import Store
from .ui.widget import KnowledgeWidget


def on_load(api):
    o = api.options
    o.group("Général")
    o.add_bool("auto_refresh", "Actualiser l'index à l'ouverture d'un projet", default=False)
    store = Store(api.data_path("knowledge"))

    class Tab(KnowledgeWidget):
        def set_project(self, path):
            super().set_project(path)
            if path and o.get("auto_refresh"):
                self.refresh()

    def make(ctx=None):
        return Tab(store, api.run_async, None, api.notify)

    api.add_project_tab("Connaissance", lambda ctx: make(ctx), icon="mdi:book-search-outline")

    def open_dialog(*_):
        dlg = QDialog(api.main_window())
        dlg.setWindowTitle("Project Knowledge")
        dlg.resize(1150, 780)
        w = make()
        QVBoxLayout(dlg).addWidget(w)
        w.set_project(api.current_project())
        dlg.exec()

    api.add_menu_action("Outils", "Project Knowledge…", open_dialog, icon="mdi:book-search-outline", shortcut="Ctrl+Alt+K")
    api.add_palette_command("Project Knowledge : rechercher dans le projet", open_dialog)
