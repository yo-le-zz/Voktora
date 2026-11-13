# Noms et conventions

* **id** du plugin : minuscules, chiffres, tirets (`mon-plugin`). C'est aussi le nom du dossier et la clé de ses réglages.
* **Menus** : chemin séparé par `/` — `api.add_menu_action("Outils/Mon plugin", "Faire", fn)`.
* **Commandes de la palette** : `api.add_palette_command("Mon plugin : faire", fn)` (préfixez par le nom du plugin).
* **Outils IA** : `api.register_ai_tool(...)` ; vus par l'IA sous le nom `<id-plugin>_<outil>`, toujours confirmés.
* **Données privées** : `api.data_path()` → `plugins_data/<id>/` ; fichiers `read_text("x.json")`, `write_text(...)`.
* **Fournitures** : `api.provide(objet)` publie l'objet du plugin ; `api.plugin("autre-id")` le récupère.
* **Versions** : `MAJEUR.MINEUR.CORRECTIF` ; contraintes `>=1.0.0`, `==1.2.3`, `~=1.2`.
