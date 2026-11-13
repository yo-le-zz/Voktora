# Exemples

## Compteur de fichiers dans la barre d'état (Python)
```python
from PySide6.QtWidgets import QLabel
def on_load(api):
    label = {}
    def factory(ctx):
        label["w"] = QLabel("…")
        return label["w"]
    api.add_status_widget(factory)
    api.on("on_open", lambda ctx: label["w"].setText(f"{len(api.project_files(ctx.project_path))} fichiers"))
```
## Lire l'état du système (JavaScript)
```js
voktora.addMenuAction("Outils", "Mémoire", ctx => {
  const s = voktora.systemInfo();
  voktora.showMarkdown("Système", "**RAM** : " + s.memory.percent + " %");
});
```
## Outil pour l'IA (Python)
```python
def on_load(api):
    api.register_ai_tool("compte", "Compte les mots d'un texte", lambda args: str(len(args["text"].split())),
                         params={"text": "string"})
```
## Tâche périodique avec options
```python
def on_load(api):
    api.options.add_float("every", "Période (s)", default=60, min=5, max=3600)
    api.every(api.options.get("every"), lambda: api.log("tic"))
```
## Rust avec serde_json
Ajoutez `serde_json = "1"` à `Cargo.toml` puis `use serde_json::json;` dans `lib.rs`.
