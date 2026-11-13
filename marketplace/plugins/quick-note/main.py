"""Quick Note — notes rapides par projet (panneau ancrable + raccourci)."""

from .ui.panel import NotePanel


_state = {}
state = _state


def on_unload(api):
    store = _state.get("store")
    if store is not None:
        store.save()


def on_load(api):
    o = api.options
    o.group("Éditeur")
    o.add_int("font_size", "Taille du texte", default=11, min=8, max=28)
    o.add_bool("monospace", "Police à chasse fixe", default=False)
    o.add_bool("wrap", "Retour à la ligne automatique", default=True)
    o.group("Enregistrement")
    o.add_float("autosave", "Enregistrer après (secondes d'inactivité)", default=1.0, min=0.2, max=30.0)
    o.add_bool("per_project", "Une note par projet", default=True)
    o.group("Raccourcis")
    o.add_shortcut("shortcut", "Ouvrir le panneau", default="Ctrl+Alt+N")
    o.add_choice("dock", "Position du panneau", ["left", "right", "bottom"], default="right")

    plus = api.plugin("api-plus")
    store = plus.Store(api, "notes.json")
    panels = []

    def factory(ctx):
        panel = NotePanel(api, plus, store)
        panels.append(panel)
        return panel

    api.add_dock("Quick Note", factory, area=o.get("dock"), icon="mdi:note-text-outline")
    api.add_palette_command("Quick Note : nouvelle note", lambda *_: [p.focus_new() for p in panels])
    api.on("on_open", lambda ctx: [p.show_project(ctx.project_path) for p in panels])
    state["store"] = store
    o.on_change(lambda key, value: [p.apply_options() for p in panels])
