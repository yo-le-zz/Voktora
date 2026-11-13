"""API Studio — client HTTP, collections, variables, tests, scripts, WebSocket, mock et imports OpenAPI/Postman."""

from PySide6.QtWidgets import QDialog, QVBoxLayout

from .storage.store import Store
from .ui.widget import ApiStudioWidget


def on_load(api):
    store = Store(api.data_path("studio"))

    def make(ctx=None):
        return ApiStudioWidget(store, api.run_async, api.notify, lambda t, x: api.confirm(t, x))

    def factory(ctx):
        w = make(ctx)
        return w

    api.add_project_tab("API Studio", factory, icon="mdi:api")

    def open_dialog(*_):
        dlg = QDialog(api.main_window())
        dlg.setWindowTitle("API Studio")
        dlg.resize(1150, 780)
        w = make()
        QVBoxLayout(dlg).addWidget(w)
        w.set_project(api.current_project())
        dlg.exec()

    api.add_menu_action("Outils", "API Studio…", open_dialog, icon="mdi:api", shortcut="Ctrl+Alt+A")
    api.add_palette_command("API Studio", open_dialog)
