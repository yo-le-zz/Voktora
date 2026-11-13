# Démarrer

## Créer un plugin
```
python tools/plugin_tool.py new mon-plugin                 # Python
python tools/plugin_tool.py new mon-plugin --lang js       # JavaScript
python tools/plugin_tool.py new mon-plugin --lang rust     # Rust
python tools/plugin_tool.py validate mon-plugin --run      # l'EXÉCUTE vraiment dans un bac jetable
```
Pour un usage local, placez le dossier dans le dossier des plugins de Voktora (Plugins → Ouvrir le dossier).

## plugin.json
```json
{
  "id": "mon-plugin", "name": "Mon plugin", "version": "1.0.0", "author": "vous",
  "description": "…", "api": 5,
  "lang": "python", "entry": "main.py",
  "permissions": ["ui"],
  "requires": ["rich>=13"],
  "dependencies": {"api-plus": ">=1.0.0"},
  "tags": ["outils"], "homepage": "https://…"
}
```
* `lang` : `python` (défaut), `js`, `rust` ; `entry` : `.py`, `.js`/`.mjs`, ou `Cargo.toml`.
* `permissions` : liste, ou `"auto"` (plugins **locaux** : détectées dans le code). Le marketplace exige la liste explicite
  (`python tools/plugin_tool.py fix-permissions`).
* `requires` : bibliothèques Python propres au plugin (voir LIBS.md). `dependencies` : autres plugins (voir DEPENDENCIES.md).

## Python
```python
def on_load(api):
    api.add_menu_action("Outils", "Bonjour", lambda ctx: api.notify("Bonjour !"), icon="mdi:hand-wave-outline")

def on_unload(api):      # facultatif
    pass
```
Plusieurs fichiers : imports relatifs (`from .helpers import x`, `from .ui.panel import Panel`).

## JavaScript
```js
voktora.addMenuAction("Outils", "Bonjour", ctx => voktora.notify("Bonjour !"));
```
Aucun code de liaison : `voktora` est global. Voir JAVASCRIPT.md.

## Rust
```rust
use voktora_plugin::{plugin, Api};
plugin!(on_load, on_unload);
fn on_load(api: &Api) { api.notify("Bonjour !"); }
fn on_unload(_api: &Api) {}
```
Voir RUST.md.
