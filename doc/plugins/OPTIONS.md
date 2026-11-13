# Options (`api.options`)

Déclarez des réglages : Voktora construit l'onglet « Options » du plugin (Plugins → votre plugin → Options), valide,
sauvegarde et remet à zéro. Rien à coder côté interface.

```python
o = api.options
o.group("Affichage")
o.add_bool("compact", "Mode compact", default=False)
o.add_int("size", "Taille", default=12, min=8, max=40)
o.add_float("delay", "Délai (s)", default=1.0, min=0.1, max=10)
o.add_text("title", "Titre", default="")
o.add_multiline("template", "Modèle", default="")
o.add_choice("mode", "Mode", ["a", "b"], default="a")
o.add_color("accent", "Couleur", default="#89b4fa")
o.add_path("folder", "Dossier", default="", directory=True)
o.add_shortcut("key", "Raccourci", default="Ctrl+Alt+N")
o.add_button("reset", "Réinitialiser", lambda: o.reset())
o.on_change(lambda key, value: ...)
o.get("size")   o.set("size", 14)   o.values()
```
`visible_if` masque une option selon une autre. Les valeurs sont validées et bornées (`min`/`max`) ; elles sont stockées
dans les réglages du plugin. JavaScript : `voktora.options.addBool(...)` ; Rust : `api.options().add_int(...)`.
