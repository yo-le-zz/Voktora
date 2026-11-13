# voktora-plugin — SDK Rust pour les plugins Voktora

Voir `doc/plugins/RUST.md`. Un plugin Rust = `plugin.json` (`"lang": "rust"`, `"entry": "Cargo.toml"`) + `Cargo.toml`
(`crate-type = ["cdylib"]`, dépendance `voktora-plugin = { path = "../voktora-sdk" }`) + `src/lib.rs`.
Voktora compile le plugin lui-même (cargo requis) ; toutes les crates externes de crates.io sont utilisables.
