# Assistant IA avec outils (1.1.0)

Menu *Outils → Assistant IA* (Ctrl+Maj+A). Le fournisseur actif (Ollama, OmniRoute, API compatible OpenAI) répond ; pour agir,
il demande un outil avec un bloc ```` ```tool {"name": "...", "args": {...}} ``` ```` que Voktora exécute puis renvoie.

| Permission | Outils | Réglage maximum |
|---|---|---|
| Lister les projets | `list_projects` | automatique |
| Lire les infos d'un projet | `get_project`, `search_projects`, `fleet_status` | automatique |
| Modifier un projet | `update_project` | demander |
| Accéder aux dépôts | `list_repos`, `project_activity` | automatique |
| Cloner un dépôt | `clone_repo` | demander |
| Accéder au compte | `get_account` | automatique |
| Voir / lancer la synchro | `sync_status` / `sync_now` | automatique / demander |
| Plugins | `list_plugins` · `install_plugin` · `uninstall_plugin` · `set_plugin_enabled` | auto · demander |
| Réglages | `get_setting` / `set_setting` | automatique / demander |
| Commandes | `run_command` (sans shell, 60 s) | demander |

Sécurité : permission « désactivé » = outil invisible pour le modèle ; modifier = confirmation obligatoire ; jetons, clés, coffre et
réglages sensibles jamais renvoyés ni modifiables ; résultats d'outils traités comme des données ; 6 outils maximum par message ;
historique envoyé borné (contexte réduit).
