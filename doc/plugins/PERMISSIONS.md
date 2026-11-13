# Permissions

Chaque méthode sensible de l'API exige une permission. Voktora la **détecte dans votre code** (Python : appels
`api.xxx` et imports ; JavaScript : `voktora.xxx(` ; Rust : `api.xxx(`, `std::net`, `std::process`, dépendances Cargo) à
partir de la table lue dans les classes de l'API elle-même — elle ne peut donc pas se périmer.

| Permission | Donne accès à |
|---|---|
| `ui` | menus, boutons, panneaux, dialogues, notifications, thèmes/icônes/styles |
| `files`, `files.write` | lire / écrire dans les projets (`project_*`) |
| `projects.read`, `projects.write` | liste et modification des projets |
| `network` | `http_get`, `http_request`, `http_download` (https ; http seulement pour le réseau privé) — **sans limite de taille par défaut** |
| `shell` | lancer des programmes |
| `clipboard` | presse-papiers |
| `system` | `system_info` (CPU, mémoire, disques, charge) |
| `config.read`, `config.write` | réglages de Voktora |
| `ai`, `ai.tools` | interroger l'IA / lui fournir des outils (toujours confirmés) |
| `libs` | bibliothèques Python propres au plugin (`requires`) |
| `native` | code natif (Rust) : **aucun bac à sable** |
| `sync`, `snapshots`, `diskusage`, `forges`, `fleet`, `vault`, `security`, `quick_actions`, `plugins.manage` | fonctions correspondantes |

Les données privées du plugin (`read_text`, `write_text`, `data_path`, journal, options) n'exigent aucune permission.

## Détection
```
python tools/plugin_tool.py detect mon-plugin           # permissions + raisons (fichier:ligne)
python tools/plugin_tool.py fix-permissions mon-plugin  # les écrit dans plugin.json
```
En mode développeur (voir DEVMODE.md), les permissions manquantes sont ajoutées au rechargement d'un manifeste explicite.
Le marketplace refuse un plugin qui utilise une permission non déclarée, ou `"permissions": "auto"`.
