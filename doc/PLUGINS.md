# Plugins Voktora (API 3 — Voktora 1.0.8)

Les plugins ajoutent des fonctions à Voktora **sans toucher à son code** : onglets de projet, menus,
boutons, panneaux latéraux, widgets de barre d'état, styles, thèmes, réactions aux événements.
Ils s'installent depuis le **Marketplace** (Paramètres → Plugins) ou à la main.

> ⚠ **Sécurité.** Un plugin est du code Python exécuté avec vos droits. Les *permissions* sont une
> déclaration vérifiée par l'API et relue par le mainteneur — **pas un bac à sable**. N'installez que
> des plugins dont vous faites confiance à l'auteur. Désactiver un plugin n'exécute plus son code.

## Utiliser les plugins

*Paramètres → Plugins et marketplace…* (`Ctrl+Maj+P`)

- **Installés** : activer/désactiver (immédiat, sans redémarrage), désinstaller, voir les erreurs et les
  gestionnaires lents, installer depuis un dossier ou une archive `.zip`.
- **Marketplace** : recherche, détails et permissions, installation et mise à jour en un clic.
  Chaque fichier est téléchargé en HTTPS et **comparé à son empreinte SHA-256** de l'index : un fichier
  modifié est refusé. Vous confirmez toujours les permissions avant l'installation.
- Hors ligne, la dernière liste connue du marketplace reste consultable.

Dossier des plugins : `<dossier de données Voktora>/plugins/` ; leurs réglages : `plugins_data/<id>/`.

## Écrire un plugin

```bash
python tools/plugin_tool.py new mon-plugin --author votre-pseudo
```

Structure :

```
marketplace/plugins/mon-plugin/
├── plugin.json     # identité + permissions
└── main.py         # point d'entrée : def on_load(api)
```

### `plugin.json`

```json
{
  "id": "mon-plugin",
  "name": "Mon plugin",
  "version": "1.0.0",
  "author": "votre-pseudo",
  "description": "Ce qu'il fait, en une phrase.",
  "api": 2,
  "entry": "main.py",
  "permissions": ["ui", "projects.read"],
  "tags": ["productivité"],
  "homepage": "https://github.com/..."
}
```

`id` : minuscules, chiffres, tirets. `version` : `MAJEUR.MINEUR.CORRECTIF`. `api` : version d'API visée
(2 actuellement). `min_voktora` (facultatif) : version minimale de l'application.

### Permissions

| Permission | Autorise |
|---|---|
| `ui` | `add_menu_action`, `add_toolbar_button`, `add_project_tab`, `add_sidebar_panel`, `add_status_widget`, `add_context_action`, `set_stylesheet`, `register_theme`, `notify`, `message`, `confirm`, `ask_text`, `main_window`… |
| `projects.read` | `projects()`, `project_info()`, `current_project()` |
| `files` | déclaration : le plugin lit des fichiers de vos projets (affichée à l'installation) |
| `network` | `http_get()` (HTTPS uniquement, 2 Mo max) |
| `shell` | `run([...])` (liste d'arguments, jamais d'interpréteur de commandes) |

Appeler une méthode sans la permission lève `PluginError` (le plugin est signalé, l'application continue).

### Exemple minimal

```python
def on_load(api):
    api.add_menu_action("Plugins/Mon plugin", "Dire bonjour",
                        lambda ctx: api.notify("Bonjour !"), icon="mdi:hand-wave-outline")
```

## Référence de l'API (`api`)

### Informations
| | |
|---|---|
| `api.plugin_id`, `api.app_version`, `api.api_version` | identité et versions |
| `api.data_dir` | dossier privé du plugin |
| `api.plugin_dir` | dossier du plugin (fichiers annexes) |
| `api.settings` | stockage persistant : `get(clé, défaut)`, `set`, `delete`, `all()` (JSON) |

### Interface (permission `ui`)
| Méthode | Effet |
|---|---|
| `add_menu_action(menu, label, handler, icon="", shortcut="", checkable=False, checked=False, tooltip="")` | Action de menu. `menu` : `"Outils"` ou un chemin `"Mon plugin/Sous-menu"` (créé si besoin, inséré avant « Aide »). Si `checkable`, le handler reçoit l'état coché. |
| `add_toolbar_button(label, handler, icon="", tooltip="")` | Bouton dans la barre d'outils des plugins (apparaît seulement s'il y en a). |
| `add_project_tab(title, factory, icon="")` | Onglet dans la page d'un projet. `factory(ctx)` renvoie un `QWidget` ; s'il a une méthode `set_project(path)` (ou `None`), elle est appelée à chaque changement de projet. |
| `add_sidebar_panel(title, factory, icon="")` | Panneau repliable en bas de la barre latérale. Même convention que les onglets. |
| `add_status_widget(factory)` | Widget permanent à droite de la barre d'état. |
| `add_context_action("project", label, handler, icon="")` | Entrée du menu clic droit d'un projet ; `ctx.project_path` = projet cliqué. |
| `set_stylesheet(qss)` | Feuille de style Qt ajoutée **après** le thème (remplace celle du plugin). Retirée à la désactivation. |
| `register_theme(id, name, colors, description="")` | Nouveau thème (Paramètres → Thème). Quelques couleurs suffisent (`base`, `text`, `blue`, `green`, `red`, `mauve`, `primary`…) : les autres sont dérivées. |
| `notify(msg)`, `message(titre, texte)`, `confirm(titre, texte) -> bool`, `ask_text(titre, label, défaut) -> str\|None` | Messages et questions. |
| `open_project(path)`, `refresh()` | Ouvrir un projet, rafraîchir la liste. |
| `icon("mdi:nom", color=None)` | `QIcon` vectoriel (même catalogue que le sélecteur d'icônes). |
| `theme_colors()` | Couleurs du thème courant. |
| `main_window()` | La `QMainWindow` (accès avancé, à utiliser avec parcimonie). |

Tout ce qu'ajoute un plugin est **retiré proprement** quand on le désactive ou le désinstalle.

### Données, réseau, système
| Méthode | Permission |
|---|---|
| `projects()` → `[{name, path, category, …}]`, `project_info(path)`, `current_project()` | `projects.read` |
| `http_get(url, timeout=10, max_bytes=2 Mo)` → `bytes` | `network` |
| `run(["git", "status"], cwd=None, timeout=30)` → `(code, sortie)` | `shell` |
| `run_async(travail, on_done=None, on_error=None)` | — (le résultat revient sur le thread d'interface) |

Les tâches longues (analyse de fichiers, réseau, git) vont dans `run_async` : **ne bloquez jamais l'interface**.
Un gestionnaire d'événement qui dépasse 0,25 s est signalé comme « lent » dans le gestionnaire de plugins.

## API 3 (Voktora 1.0.8) — réglages, snapshots, forges, synchro, plugins, sécurité

Chaque famille exige sa permission dans `plugin.json` (affichée à l'installation). Les plugins `api: 2` marchent toujours.

| Permission | Méthodes |
|---|---|
| `config.read` | `config_get(clé)`, `config_all()` — les clés sensibles (token, secret, password, key…) sont refusées |
| `config.write` | `config_set(clé, valeur)` — **confirmé par l'utilisateur à chaque changement** |
| `quick_actions` | `quick_actions()`, `quick_action_add(nom, cmd, icon, terminal)` (confirmé), `quick_action_remove(nom)` |
| `snapshots` | `snapshots(projet)`, `snapshot_create(projet, label, note)` (long : `run_async`) |
| `diskusage` | `disk_usage(projet)` — taille par catégorie (cache, compilation, dépendances) |
| `forges` | `forge_info(projet)` (forge, dépôt, fork, parent), `forge_accounts()` (sans jeton) |
| `sync` | `sync_status()`, `sync_now()` |
| `plugins.manage` | `plugins()`, `set_plugin_enabled(id, bool)` (confirmé ; jamais sur soi-même) |
| `security` | `security_report()` (coffre, plugins, révocations, synchro, TLS), `audit_plugin_source(code)` |
| `vault` | `lock_vault()`, `vault_secret_get/set/delete(nom)` — secrets **propres au plugin** (`plugin:<id>:<nom>`) |

Sans interface (Voktora sans fenêtre), toute demande de confirmation est refusée. Les jetons, mots de passe et
secrets de Voktora ne sont jamais accessibles à un plugin, quelles que soient ses permissions.

### Événements (`api.on(nom, handler)`)

| Événement | Quand |
|---|---|
| `on_start` / `on_quit` | application prête / fermeture |
| `on_open` / `on_close` | un projet est ouvert / on le quitte |
| `on_create` / `on_delete` / `on_rename` | projet créé / supprimé / renommé (`ctx.data["old_path"]`) |
| `on_refresh` | liste de projets rafraîchie |
| `on_theme_changed` | thème changé (`ctx.data["theme"]`) |
| `plugin:<nom>` | événements entre plugins : `api.emit("nom", clé=valeur)` → `ctx.data` |

Le handler reçoit `ctx` : `ctx.project_path`, `ctx.data`, `ctx.log(msg)`.

### Commandes et boutons (hérités)
`register_command(nom, handler, desc)` et `register_button(label, handler, tooltip, icon)` restent disponibles
(groupe « Plugins » de l'onglet Outils).

### Cycle de vie
`on_load(api)` à l'activation, `on_unload(api)` (facultatif) à la désactivation. Une exception dans votre
code est capturée et affichée dans le gestionnaire de plugins ; elle n'arrête ni l'application ni les autres plugins.

## Compatibilité : anciens plugins (fichier `.py`)

Un fichier `plugins/mon_plugin.py` (avec `PLUGIN_NAME`, `PLUGIN_VERSION`, `PLUGIN_AUTHOR` et `on_load(api)`)
fonctionne toujours, avec toutes les permissions. Il est signalé « ancien format » : passez à un dossier avec
`plugin.json` pour déclarer vos permissions.

## Publier sur le marketplace

Plugins **officiels** (par défaut, écrits par le mainteneur) : dossier `marketplace/plugins/<id>/`.
Plugins **communautaires** : vous gardez votre dépôt/fork ; la PR ajoute un **sous-module Git épinglé sur un
commit** (`marketplace/community/<id>`). L'application ne télécharge que les fichiers du plugin à ce commit
exact. Modifier votre code ne change rien chez les utilisateurs tant qu'une **nouvelle PR** (nouveau commit
épinglé, `version` augmentée) n'est pas relue et fusionnée — même pour un plugin déjà accepté.
Détails et sécurité : [`marketplace/README.md`](../marketplace/README.md). Outils :

```bash
python tools/plugin_tool.py submit https://github.com/vous/mon-plugin   # ajoute VOTRE dépôt en sous-module
python tools/plugin_tool.py check-pr --base origin/main                 # règles d'une PR communautaire
python tools/plugin_tool.py pr-summary --base origin/main               # diff ancien → nouveau commit
python tools/plugin_tool.py drift                                       # dépôts ayant avancé depuis l'épinglage
python tools/plugin_tool.py validate [id]      # manifeste, fichiers, analyse statique
python tools/plugin_tool.py zip mon-plugin     # archive installable (Installer depuis un fichier…)
python tools/plugin_tool.py build-index        # régénère l'index (fait par la CI après fusion)
```

L'analyse statique (module `voktora/plugins/audit.py`, **la même** dans la CI et dans l'application) refuse
`eval`/`exec`/`compile`/`__import__`, `os.system`, `shell=True`, `ctypes`/`importlib`/`pickle`/`builtins`, l'accès à
`__subclasses__`/`__globals__`/`__builtins__`, et les imports réseau ou `subprocess` sans la permission
correspondante. Au chargement, un plugin du marketplace tourne en plus avec des `builtins` filtrés (sans
`eval`/`exec`, `__import__` contrôlé par permissions). Cela ne remplace pas la relecture humaine : ce n'est pas
un bac à sable.

## Plugins fournis (exemples à lire)

`ui-tweaks` (styles), `quick-notes` (onglet + réglages), `focus-timer` (barre d'état), `todo-scanner`
(analyse asynchrone), `git-insights` (`api.run`), `zen-mode` (barre d'outils, `main_window`),
`neon-themes` (thèmes), `project-counter` (menu clic droit, événements) — dans `marketplace/plugins/`.
