"""Workflow Forge — éditeur visuel d'automatisations : blocs, déclencheurs, exécution parallèle, test à blanc, journaux."""

from PySide6.QtWidgets import QDialog, QVBoxLayout

from .storage.store import Store
from .ui.widget import ForgeWidget


def on_load(api):
    o = api.options
    o.group("Général")
    o.add_bool("notify", "Notifier la fin des exécutions", default=True)
    o.add_bool("triggers", "Activer les déclencheurs automatiques (fichiers, cron, HTTP local…)", default=True)
    store = Store(api.data_path("forge"))
    live: list = []

    def make(ctx=None):
        w = ForgeWidget(store, api.run_async, api.notify, {"notify": o.get("notify"), "triggers": o.get("triggers")})
        live.append(w)
        return w

    def tab(ctx):
        return make(ctx)

    api.add_project_tab("Workflows", tab, icon="mdi:graph-outline")

    def open_dialog(*_):
        dlg = QDialog(api.main_window())
        dlg.setWindowTitle("Workflow Forge")
        dlg.resize(1250, 820)
        w = make()
        QVBoxLayout(dlg).addWidget(w)
        w.set_project(api.current_project())
        dlg.exec()

    api.add_menu_action("Outils", "Workflow Forge…", open_dialog, icon="mdi:graph-outline", shortcut="Ctrl+Alt+W")
    api.add_palette_command("Workflow Forge", open_dialog)
    api.on("on_open", lambda ctx: [w.open_event("on_open") for w in live if w.project])
    api.on("on_start", lambda ctx: [w.open_event("on_start") for w in live if w.project])
