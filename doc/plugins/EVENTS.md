# Événements

`api.on(nom, fonction)` (Python), `voktora.on(nom, fn)` (JS), `api.on(nom, |api, ctx| …)` (Rust).

| Événement | Quand |
|---|---|
| `on_start` / `on_quit` | démarrage / fermeture de la fenêtre |
| `on_open` / `on_close` | un projet est ouvert / fermé |
| `on_create` / `on_delete` / `on_rename` | projet créé / supprimé / renommé |
| `on_refresh` | la liste des projets est rafraîchie |
| `on_theme_changed` | thème modifié |
| `on_sync_start` / `on_sync_done` | synchronisation |
| `on_plugin_loaded` / `on_plugin_unloaded` | un autre plugin se (dé)charge — pratique avec les dépendances |

Le contexte (`ctx`) porte `project_path`, `project_name`, etc. ; en JS/Rust c'est un objet JSON. Une exception dans un
gestionnaire est journalisée (console développeur) sans arrêter les autres.
