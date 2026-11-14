//! LOC Counter (Rust) — « Outils › Compter les lignes de code » : tableau par langage du projet ouvert.

mod count;

use serde_json::json;
use std::path::PathBuf;
use voktora_plugin::{plugin, Api};

plugin!(on_load, on_unload);

fn on_load(api: &Api) {
    let o = api.options();
    o.group("Analyse");
    o.add_text("skip_dirs", "Dossiers ignorés", ".git, node_modules, target, .venv, venv, dist, build, __pycache__");
    o.add_int("max_files", "Nombre maximal de fichiers", 20000, 100, 500000);
    api.add_menu_action("Outils", "Compter les lignes de code", |a, _ctx| run(a));
    api.log("LOC Counter prêt");
}

fn on_unload(_api: &Api) {}

fn run(api: &Api) {
    let project = match api.call("current_project", json!([])) {
        Ok(v) => v.as_str().map(PathBuf::from),
        Err(e) => {
            api.notify(&format!("Projet inaccessible : {e}"));
            return;
        }
    };
    let Some(root) = project else {
        api.notify("Ouvrez d'abord un projet");
        return;
    };
    let options = api.options();
    let skip: Vec<String> = options
        .get_string("skip_dirs")
        .split(|c: char| c == ',' || c.is_whitespace())
        .filter(|s| !s.is_empty())
        .map(String::from)
        .collect();
    let limit = options.get_int("max_files").max(100) as usize;
    let report = count::count_dir(&root, &skip, limit);
    let name = root.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
    let markdown = count::render_markdown(&name, &report);
    if let Err(e) = api.call("show_markdown", json!(["Lignes de code", markdown])) {
        api.warn(&format!("show_markdown : {e}"));
    }
}
