"""Project Counter 1.1 — compteur de projets dans la barre d'état, résumé, et actions du menu clic droit.

Montre : add_status_widget, add_context_action, options, api.projects(), hooks on_refresh/on_create/on_delete.
"""

from PySide6.QtWidgets import QApplication, QLabel

from . import summary


def on_load(api):
    o = api.options
    o.group("Barre d'état")
    o.add_choice("format", "Affichage", ["count", "short", "category"], default="count",
                 help="count : « 12 projets » · short : « 12 » · category : « 12 projets · 3 catégories »")
    o.group("Menu clic droit")
    o.add_bool("extra_actions", "Ajouter « Copier le nom » et « Copier la commande cd »", default=True)
    holder = {}

    def update(_ctx=None):
        label = holder.get("label")
        if label is not None:
            projects = api.projects()
            label.setText(summary.label(projects, o.get("format")))
            label.setToolTip(summary.tooltip(projects))

    def factory(_ctx):
        holder["label"] = QLabel()
        update()
        return holder["label"]

    def copy(text, message):
        QApplication.clipboard().setText(text)
        api.notify(message)

    def copy_path(ctx):
        if ctx.project_path:
            copy(str(ctx.project_path), "Chemin copié dans le presse-papiers")

    def copy_name(ctx):
        if ctx.project_path:
            copy(ctx.project_path.name, "Nom copié")

    def copy_cd(ctx):
        if ctx.project_path:
            copy(summary.cd_command(str(ctx.project_path)), "Commande copiée")

    api.add_status_widget(factory)
    api.add_context_action("project", "Copier le chemin", copy_path, icon="mdi:content-copy")
    if o.get("extra_actions"):
        api.add_context_action("project", "Copier le nom", copy_name, icon="mdi:tag-outline")
        api.add_context_action("project", "Copier la commande cd", copy_cd, icon="mdi:console")
    api.add_menu_action("Plugins/Project Counter", "Résumé des projets",
                        lambda *_: api.show_markdown("Projets", summary.to_markdown(api.projects())), icon="mdi:chart-bar")
    o.on_change(lambda _k, _v: update())
    api.on("on_refresh", update)
    api.on("on_create", update)
    api.on("on_delete", update)
