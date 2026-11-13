# Plugins Rust

`"lang": "rust"`, `"entry": "Cargo.toml"`, permission `native`. Voktora **compile** le plugin (cargo requis, `https://rustup.rs`)
dans un dossier privé, puis charge la bibliothèque. Première compilation : quelques minutes ; ensuite seulement si le
code change (empreinte). Le plugin apparaît « en cours de compilation » pendant ce temps.

```toml
[package]
name = "mon-plugin"
version = "0.1.0"
edition = "2021"
[lib]
crate-type = ["cdylib"]
[dependencies]
voktora-plugin = { path = "../voktora-sdk" }   # le SDK est copié à côté pendant la compilation
serde_json = "1"                               # n'importe quelle crate de crates.io
```
```rust
use voktora_plugin::{plugin, Api};
plugin!(on_load, on_unload);
fn on_load(api: &Api) {
    let o = api.options();
    o.add_int("n", "Nombre", 5, 1, 10);
    api.add_menu_action("Outils", "Hello", |a, _ctx| a.notify("Salut"));
    api.on("on_open", |a, ctx| a.log(&format!("{ctx:?}")));
    api.every(30.0, |a, _| a.log("tick"));
}
fn on_unload(_api: &Api) {}
```
`api.call("nom_methode", json!([...]))` atteint **toute** l'API (même pont que JavaScript).

## Sécurité — important
Un plugin Rust est du **code natif dans le processus de Voktora** : aucun bac à sable, accès complet à vos fichiers et au
réseau, indépendamment des permissions (qui ne contrôlent que les appels d'API). C'est pourquoi : permission `native`
affichée avant installation ; **niveau officiel uniquement** dans le marketplace ; confirmation pour les plugins locaux.

## ABI (si vous écrivez sans le SDK)
Quatre symboles C : `voktora_plugin_abi() -> u32` (=1), `voktora_plugin_init(host_call, host_free)`,
`voktora_plugin_dispatch(json) -> *char`, `voktora_plugin_free(*char)`. Tout est JSON UTF-8 : appel hôte `{"name","args"}`,
rappels `{"__fn": id}`.
