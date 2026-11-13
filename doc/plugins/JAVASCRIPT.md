# Plugins JavaScript

`"lang": "js"`, `"entry": "main.js"` (ou `.mjs`). Chaque plugin JavaScript tourne dans **son propre processus** (moteur QJSEngine),
avec un environnement minimal : une boucle infinie est arrêtée (5 s sans réponse) sans geler Voktora, et le code n'a
aucun accès direct au système — uniquement l'API.

* `voktora.xxx(...)` : toute méthode de l'API en camelCase (`add_menu_action` → `addMenuAction`). Les rappels sont de
  simples fonctions ; les valeurs transitent en JSON.
* `require("./autre.js")` : modules CommonJS **dans le dossier du plugin** (échapper du dossier est refusé).
* `voktora.on("on_open", ctx => …)`, `voktora.options.addInt(...)` ; une fonction globale `onUnload()` est appelée au déchargement.
* Pas de DOM, pas de `fetch` : utilisez l'API (`voktora.systemInfo()`, `voktora.httpGet(...)` avec la permission `network`, qui rend des octets).

```js
const fmt = require("./fmt.js");
voktora.options.addInt("n", "Nombre", 5, 1, 10);
voktora.addMenuAction("Outils", "Compter", ctx => {
  voktora.notify(fmt.plural(voktora.options.get("n"), "projet"));
});
```
Limites : pas d'interface Qt personnalisée (panneaux/docks) — utilisez les dialogues de l'API (`showMarkdown`, `askChoice`, …)
ou écrivez ce plugin en Python.
