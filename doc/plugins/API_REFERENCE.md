# Référence de l'API des plugins

**114 méthodes.**

> Fichier GÉNÉRÉ par `tools/gen_api_doc.py` depuis le code : ne le modifiez pas à la main.

En Python : `api.nom(...)`. En JavaScript : `voktora.nomEnCamelCase(...)`. En Rust : `api.call("nom_en_snake", ...)` ou les raccourcis du SDK. La colonne *Permission* est **détectée automatiquement** à partir de votre code.

## Base

| Méthode | Permission | Description |
|---|---|---|
| `add_context_action(target: str, label: str, handler: Callable, icon: str='')` | — | Entrée dans le menu contextuel (clic droit). `target` : « project ». |
| `add_menu_action(menu: str, label: str, handler: Callable, icon: str='', shortcut: str='', checkable: bool=False, checked: bool=False, tooltip: str='')` | — | Action dans un menu. `menu` : « Outils », ou un chemin « Mon plugin/Sous-menu » |
| `add_project_tab(title: str, factory: Callable[[PluginContext], Any], icon: str='')` | — | Onglet dans la page d'un projet. `factory(ctx)` retourne un QWidget ; s'il possède une méthode |
| `add_sidebar_panel(title: str, factory: Callable[[PluginContext], Any], icon: str='')` | — | Panneau repliable en bas de la barre latérale gauche. |
| `add_status_widget(factory: Callable[[PluginContext], Any])` | — | Widget permanent à droite de la barre d'état. |
| `add_toolbar_button(label: str, handler: Callable, icon: str='', tooltip: str='')` | — | Bouton dans la barre d'outils des plugins (en haut de la fenêtre). |
| `app_version()` | — |  |
| `ask_text(title: str, label: str, default: str='')` | — |  |
| `confirm(title: str, text: str)` | — |  |
| `current_project()` | projects.read |  |
| `data_dir()` | — | Dossier privé du plugin (créé à la demande) pour ses fichiers. |
| `emit(event: str, **data: Any)` | — | Événement entre plugins : `api.emit("mon-event", x=1)` -> hooks « plugin:mon-event ». |
| `has_plugin(plugin_id: str, spec: str='*')` | — | Dépendance FACULTATIVE : le plugin est-il chargé (et dans la version `spec`) ? |
| `http_download(url: str, dest: str | Path, timeout: float=60.0, progress: Callable[[int, int], None] | None=None)` | network | Télécharge `url` dans un fichier du dossier de données du plugin (`dest` relatif), en flux, sans limite |
| `http_get(url: str, timeout: float=30.0, max_bytes: int | None=None)` | — | GET (permission « network »). https:// partout ; http:// seulement vers la machine locale ou un réseau |
| `http_request(method: str, url: str, headers: dict[str, str] | None=None, body: bytes | str | dict | None=None, timeout: float=30.0, max_bytes: int | None=None)` | network | Requête HTTP complète (permission « network »). `body` dict → JSON. Retourne (code, corps, en-têtes). |
| `icon(icon_id: str, color: str | None=None)` | — | QIcon vectoriel (« mdi:nom » ; voir le sélecteur d'icônes). |
| `main_window()` | — | La QMainWindow de Voktora, pour les plugins qui ont vraiment besoin d'agir dessus (mode zen…). |
| `message(title: str, text: str)` | — |  |
| `notify(message: str, timeout_ms: int=4000)` | — |  |
| `open_project(path: str | Path)` | — |  |
| `plugin(plugin_id: str)` | — | Ce que le plugin `plugin_id` publie avec `api.provide`. Il doit figurer dans « dependencies ». |
| `plugin_dir()` | — |  |
| `plugin_id()` | — |  |
| `project_info(path: str | Path)` | projects.read |  |
| `projects()` | projects.read | Projets enregistrés : [{name, path, category, …}]. |
| `provide(exports: Any)` | — | Publie un objet (fonctions, classe, dict…) que les plugins qui dépendent de celui-ci récupèrent avec |
| `refresh()` | — |  |
| `register_button(label: str, handler: Callable, tooltip: str='', icon: str='')` | — | Bouton dans le groupe « Plugins » de l'onglet Outils du projet. |
| `register_command(name: str, handler: Callable, desc: str='')` | — |  |
| `register_hook(hook_name: str, handler: Callable)` | — |  |
| `register_theme(theme_id: str, name: str, colors: dict[str, str], description: str='')` | ui | Ajoute un thème (apparaît dans Paramètres → Thèmes). `colors` : mêmes clés que les thèmes JSON. |
| `run(args: list[str], cwd: str | Path | None=None, timeout: float=30.0)` | shell | Lance un programme (permission « shell »), sans passer par un interpréteur de commandes. |
| `run_async(work: Callable[[], Any], on_done: Callable[[Any], None] | None=None, on_error: Callable[[BaseException], None] | None=None)` | — | Exécute `work()` dans un thread ; `on_done(résultat)` / `on_error(exc)` reviennent sur le |
| `set_stylesheet(qss: str)` | — | Ajoute une feuille de style Qt (QSS) par-dessus le thème. Remplace celle du plugin. |
| `theme_colors()` | — | Couleurs du thème courant (base, text, blue, green, red…). |

## Extensions (API 2–4)

| Méthode | Permission | Description |
|---|---|---|
| `ai_ask(prompt: str, max_tokens: int=400)` | ai | Pose une question au fournisseur IA actif (permission « ai »). Le texte est envoyé à ce fournisseur : |
| `audit_plugin_source(source: str)` | security | Passe le code Python donné dans l'audit statique des plugins ; retourne les problèmes trouvés. |
| `config_all()` | config.read |  |
| `config_get(key: str, default: Any=None)` | config.read | Réglage de l'application (permission « config.read »). Les clés sensibles sont masquées. |
| `config_set(key: str, value: Any)` | config.write | Modifie un réglage de l'application (permission « config.write », confirmation à chaque changement). |
| `disk_usage(project: str | Path)` | diskusage | Taille d'un projet par catégorie (cache, compilation, dépendances…). Lecture seule. |
| `fleet_states()` | fleet | État Git de tous les projets (permission « fleet ») : branche, modifications, retard/avance, problèmes. |
| `forge_accounts()` | forges | Comptes de forge connectés — sans jeton. |
| `forge_info(project: str | Path)` | forges | Forge, dépôt et statut de fork d'un projet (analyse locale des remotes, sans réseau). |
| `lock_vault()` | vault | Verrouille le coffre tout de suite (action sûre : aucune confirmation). |
| `plugins()` | plugins.manage | Plugins installés : id, version, origine, permissions, état, commit épinglé. |
| `project_update(project: str | Path, **fields: Any)` | projects.write | Modifie description, catégorie, statut, tags, couleur ou emoji d'un projet (permission « projects.write », |
| `quick_action_add(name: str, cmd: str, icon: str='', terminal: bool=False)` | quick_actions |  |
| `quick_action_remove(name: str)` | quick_actions |  |
| `quick_actions()` | quick_actions |  |
| `search_projects(query: str, content: bool=True, limit: int=100)` | fleet | Recherche dans les noms de projets, de fichiers et le contenu (permission « fleet »). |
| `security_report()` | security | Vue d'ensemble de la sécurité (lecture seule) : coffre, plugins, révocations, synchronisation, TLS. |
| `set_plugin_enabled(plugin_id: str, enabled: bool)` | plugins.manage |  |
| `snapshot_create(project: str | Path, label: str='', note: str='')` | snapshots | Crée un snapshot complet ; retourne son chemin. Peut être long : à appeler depuis `run_async`. |
| `snapshots(project: str | Path)` | snapshots |  |
| `sync_now()` | sync |  |
| `sync_status()` | sync | État de la synchronisation entre PC (pourcentages, pairs, dernière synchro). |
| `vault_secret_delete(name: str)` | vault |  |
| `vault_secret_get(name: str)` | vault | Secret PROPRE à ce plugin (espace « plugin:<id>:<nom> » du coffre déverrouillé). |
| `vault_secret_set(name: str, value: str)` | vault |  |

## API 5 — fichiers, journal, tâches, dialogues, IA, boutiques

| Méthode | Permission | Description |
|---|---|---|
| `add_dock(title: str, factory: Callable[[Any], Any], area: str='right', icon: str='')` | — | Panneau flottant/ancrable (QDockWidget) à gauche, à droite, en haut ou en bas de la fenêtre. |
| `add_palette_command(label: str, handler: Callable)` | — | Commande dans la palette (Ctrl+K), préfixée du nom du plugin. |
| `add_shortcut(sequence: str, handler: Callable, description: str='')` | — | Raccourci clavier global (ex. « Ctrl+Alt+N »). Retiré au déchargement. |
| `after(seconds: float, handler: Callable[[], None])` | — | Appelle `handler()` une fois, dans `seconds` s, sur le thread de l'interface. Annulé au déchargement. |
| `ask_choice(title: str, label: str, choices: list[str], default: int=0)` | — |  |
| `ask_number(title: str, label: str, default: float=0, min: float=-1000000000.0, max: float=1000000000.0, decimals: int=0)` | — |  |
| `clipboard_text()` | clipboard |  |
| `data_path(relative: str | Path='')` | — | Chemin SÛR dans le dossier de données du plugin (`..`, chemins absolus et liens refusés). |
| `debug(message: Any)` | — |  |
| `delete_data(relative: str)` | — |  |
| `error(message: Any)` | — |  |
| `every(seconds: float, handler: Callable[[], None])` | — | Appelle `handler()` toutes les `seconds` s (au moins 0,2 s), sur le thread de l'interface. |
| `list_data(relative: str='')` | — |  |
| `log(message: Any, level: str='info')` | — |  |
| `open_url(url: str)` | — | Ouvre une adresse http(s):// dans le navigateur (confirmé). |
| `pick_file(title: str='Choisir un fichier', start: str='', filter: str='')` | — |  |
| `pick_folder(title: str='Choisir un dossier', start: str='')` | — |  |
| `pick_save_file(title: str='Enregistrer sous', start: str='', filter: str='')` | — |  |
| `project_files(project: str | Path, pattern: str='*', limit: int=2000)` | files | Fichiers d'un projet correspondant à `pattern` (glob, ex. « **/*.py »), chemins relatifs. |
| `project_read_text(project: str | Path, relative: str, max_bytes: int=5000000)` | files |  |
| `project_write_text(project: str | Path, relative: str, text: str)` | files.write | Écrit un fichier d'un projet (permission « files.write », confirmé à chaque écriture). |
| `read_bytes(relative: str)` | — |  |
| `read_text(relative: str, default: str | None=None, encoding: str='utf-8')` | — |  |
| `register_ai_tool(name: str, description: str, handler: Callable[[dict], Any], params: dict[str, str] | None=None, writes: bool=False)` | ai.tools | Ajoute un outil à l'assistant IA. `handler(args: dict)` retourne du texte ou du JSON. L'assistant demande |
| `register_shop_source(kind: str, name: str, url: str)` | — | Ajoute une source (boutique) de thèmes (« themes »), d'icônes (« icons ») ou de styles (« styles »). |
| `set_clipboard_text(text: str)` | clipboard |  |
| `set_icon_pack(pack_id: str)` | ui | Active un pack d'icônes installé (« » pour revenir aux icônes d'origine ; confirmé). |
| `set_style_enabled(style_id: str, enabled: bool)` | ui | Active/désactive un style installé (confirmé). |
| `set_theme(theme_id: str)` | ui | Change le thème de l'application (confirmé). |
| `shop_installed(kind: str)` | config.read | Objets installés d'une boutique : [{id, name, version, author, description…}]. |
| `show_markdown(title: str, markdown: str)` | — | Fenêtre de lecture : Markdown (titres, listes, code, tableaux, liens http/https) rendu par Voktora. |
| `system_info(processes: int=0)` | system | Processeur (%), mémoire, disques, charge ; `processes` > 0 : les plus gourmands (si psutil). |
| `warn(message: Any)` | — |  |
| `write_bytes(relative: str, data: bytes)` | — |  |
| `write_text(relative: str, text: str, encoding: str='utf-8')` | — |  |

## Options (api.options)

| Méthode | Permission | Description |
|---|---|---|
| `add_bool(key: str, label: str, default: bool=False, help: str='', visible_if=None)` | — |  |
| `add_button(label: str, handler: Callable[[], None], help: str='')` | — | Bouton d'action dans le panneau (ex. « Vider le cache »). |
| `add_choice(key: str, label: str, choices: list[str], default: str | None=None, help: str='', visible_if=None)` | — |  |
| `add_color(key: str, label: str, default: str='#89b4fa', help: str='', visible_if=None)` | — |  |
| `add_float(key: str, label: str, default: float=0.0, min: float | None=None, max: float | None=None, step: float=0.1, help: str='', visible_if=None)` | — |  |
| `add_int(key: str, label: str, default: int=0, min: int | None=None, max: int | None=None, step: int=1, help: str='', visible_if=None)` | — |  |
| `add_multiline(key: str, label: str, default: str='', help: str='', visible_if=None)` | — |  |
| `add_path(key: str, label: str, default: str='', kind: str='file', help: str='', visible_if=None)` | — |  |
| `add_shortcut(key: str, label: str, default: str='', help: str='', visible_if=None)` | — |  |
| `add_text(key: str, label: str, default: str='', help: str='', visible_if=None)` | — |  |
| `get(key: str, default: Any=None)` | — |  |
| `group(name: str)` | — | Les options déclarées ensuite sont rangées sous ce titre. |
| `is_visible(option: Option)` | — |  |
| `on_change(callback: Callable[[str, Any], None])` | — | `callback(clé, valeur)` est appelé à chaque changement (depuis le panneau de réglages ou `set`). |
| `reset(key: str | None=None)` | — | Remet une option (ou toutes) à sa valeur par défaut. |
| `schema()` | — |  |
| `set(key: str, value: Any)` | — |  |
| `values()` | — |  |

