"""Project Counter — widget de barre d'état + action de menu contextuel.

Montre : add_status_widget, add_context_action, api.projects(), hook on_refresh.
"""

from PySide6.QtWidgets import QApplication, QLabel


def on_load(api):
    holder = {}

    def update(_ctx=None):
        label = holder.get("label")
        if label is not None:
            total = len(api.projects())
            label.setText(f"{total} projet{'s' if total != 1 else ''}")

    def factory(_ctx):
        holder["label"] = QLabel()
        update()
        return holder["label"]

    def copy_path(ctx):
        if ctx.project_path:
            QApplication.clipboard().setText(str(ctx.project_path))
            api.notify("Chemin copié dans le presse-papiers")

    api.add_status_widget(factory)
    api.add_context_action("project", "Copier le chemin", copy_path, icon="mdi:content-copy")
    api.on("on_refresh", update)
    api.on("on_create", update)
    api.on("on_delete", update)
