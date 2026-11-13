# Plugins fournis (marketplace officiel)

| Plugin | Rôle | Options principales |
|---|---|---|
| **api-plus** | aides pour auteurs de plugins : `fmt_bytes`, `fmt_duration`, `slug`, `debounce`, `Store`, `Cache`, bus d'événements | — |
| **quick-note** | notes rapides (par projet) dans un panneau ancrable, enregistrement différé | police, retour à la ligne, délai, position, raccourci |
| **system-monitor** | CPU/RAM/disques/charge, barre d'état + panneau, alertes | éléments affichés, intervalle, seuils |
| **dev-toolbox** | Base64, UUID, horodatage, JSON, hachages, URL, mots de passe | outil au démarrage, copie auto, longueur de mot de passe |
| **theme-studio** | éditeur de thèmes avec aperçu en direct, import/export JSON | point de départ, aperçu, auteur |
| **code-inspector** | analyse d'architecture (Python/Rust/JS/C++), graphe, ponts Python×Rust, audit, exports | profondeur, exclusions |
| **devops-center** | Git, Docker, SSH, GitHub, pipelines, déploiements avec restauration | environnements, confirmation prod |
| **api-studio** | client HTTP/WebSocket, mock, scripts, OpenAPI/Postman | variables, environnements |
| **project-knowledge** | recherche BM25, wiki, diagrammes, doc d'API | fichiers indexés |
| **workflow-forge** | éditeur visuel d'automatisations, cron, déclencheurs | déclencheurs, port http_in |
| + ceux d'avant : project-counter, todo-scanner, ui-tweaks, zen-mode, … | | |

Les thèmes, packs d'icônes et styles sont dans les **boutiques** (`doc/SHOPS.md`), plus dans les plugins.
Quick Note, System Monitor et Dev Toolbox **dépendent** d'api-plus (installée automatiquement).

## Plugins avancés (1.1.2) — notes pour développeurs

Chaque plugin suit la même structure : `plugin.json`, `main.py` (point d'entrée mince), `core/` (logique pure, sans Qt),
`services/`, `storage/`, `ui/`, `resources/`, `tests/`. Les tests vivent dans `tests/test_plugin_<nom>.py` à la racine et chargent
le plugin comme paquet factice pour que les imports relatifs fonctionnent.

Contraintes du validateur (voir `PERMISSIONS.md`) : pas de littéraux `eval`/`exec`/`__import__` ni `importlib` dans les `.py` d'un plugin ;
les données sensibles à ce sujet vont dans `resources/*.json|txt`. Vérification : `python tools/plugin_tool.py validate <id> --run`.

| Plugin | Permissions | Points d'extension utiles |
|---|---|---|
| code-inspector | projects.read, ui | `core/model.py` (modèle), `analyzers/` (un fichier par langage), `exporters/` |
| devops-center | network, projects.read, shell, ui | `core/proc.py` (exécuteur sans shell), `core/pipeline.py`, `core/deploy.py` |
| api-studio | network, projects.read, shell, ui | `core/client.py`, `core/scripts.py` + `resources/*_runner.txt`, `core/mock.py` |
| project-knowledge | projects.read, ui | `core/index.py`, `core/bm25.py`, `core/wiki.py` |
| workflow-forge | network, projects.read, shell, ui | `core/blocks.py` (catalogue), `core/engine.py`, `core/triggers.py` |

Pour ajouter un bloc à Workflow Forge ou un analyseur à Code Inspector : créez le module, enregistrez-le dans le catalogue
correspondant, ajoutez un test, puis relancez `validate --run`.
