# Mode développeur

Menu Préférences → **Console développeur (plugins)…**

* **Tracebacks** : les exceptions des plugins *et de Voktora* sont journalisées. Les lignes `▶` sont votre code,
  `· Voktora` celui de l'application — vous voyez où ça casse sans fouiller.
* **Rechargement automatique** : cochez « Recharger automatiquement » pour un plugin ; à chaque fichier modifié il est rechargé.
* **Auto-installation** : au rechargement, les imports Python manquants sont ajoutés à `requires` (installés ensuite) et les
  permissions détectées ajoutées au manifeste explicite.
* **Valider** : exécute **réellement** le plugin dans un sous-processus jetable (données vierges, faux hôte graphique) :
  chargement, gestionnaires d'événements, déchargement. Python, JavaScript, Rust (compilation comprise).
  En ligne de commande : `python tools/plugin_tool.py validate mon-plugin --run`.
* Activation permanente : réglage `plugins.developer_mode = true` dans la configuration.

Limite : le faux hôte n'a pas de vraie fenêtre ; les événements qui en dépendent (`on_start`, `on_quit`, `on_close`,
`on_theme_changed`) ne sont pas simulés et les panneaux ne sont pas affichés.
