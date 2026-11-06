# Marketplace de plugins Voktora

Ce dossier est le **catalogue officiel** : Voktora (Paramètres → Plugins → Marketplace) lit
`index.json` et installe les plugins de `plugins/`. Tout y arrive par **Pull Request**.

## Proposer un plugin (fork → Pull Request)

1. **Fork** du dépôt sur GitHub (bouton *Fork*), puis clonez votre fork.
2. Créez le squelette :
   ```bash
   python tools/plugin_tool.py new mon-plugin --author votre-pseudo
   ```
   Il crée `marketplace/plugins/mon-plugin/` avec `plugin.json` et `main.py`.
3. Écrivez votre plugin (API : [`doc/PLUGINS.md`](../doc/PLUGINS.md)). Pour l'essayer : dans Voktora,
   *Plugins → Installer depuis un fichier…* → dossier `marketplace/plugins/mon-plugin`.
4. Vérifiez :
   ```bash
   python tools/plugin_tool.py validate mon-plugin
   ```
5. Poussez sur une branche de votre fork et ouvrez une **Pull Request** vers `main`
   (ajoutez `?template=plugin.md` à l'URL de la PR pour obtenir la liste de contrôle).
6. La CI valide automatiquement ; le mainteneur relit le code, puis fusionne. L'`index.json`
   est régénéré tout seul (n'y touchez pas). Le plugin apparaît dans le marketplace.

**Mettre à jour un plugin :** même procédure, en **augmentant `version`** dans `plugin.json`.

## Règles

- Dossier `plugins/<id>/`, `id` identique à celui de `plugin.json` (minuscules, chiffres, tirets).
- Fichiers autorisés : `.py .json .md .txt .qss .svg .png .css` — 40 fichiers, 512 Ko par fichier, 2 Mo au total.
- Pas de dépendance à installer : bibliothèque standard + PySide6 (déjà fournie).
- Déclarez **toutes** les permissions utilisées et justifiez-les dans la PR (voir ci-dessous).
- Interdits : `eval`/`exec`/`compile`/`__import__`, `os.system`, `shell=True`, code obfusqué, liens symboliques.
  Utilisez `api.run([...])` (permission `shell`) plutôt que `subprocess`.
- Respectez la vie privée : aucune donnée envoyée sur Internet sans permission `network` expliquée.

| Permission | Donne accès à |
|---|---|
| `ui` | menus, onglets, boutons, panneaux, styles, thèmes |
| `projects.read` | liste et informations de vos projets |
| `files` | lecture de fichiers dans vos projets |
| `network` | requêtes HTTPS (`api.http_get`) |
| `shell` | lancer des programmes (`api.run`) |

> ⚠ Ce n'est **pas un bac à sable** : un plugin est du code Python exécuté avec les droits de
> l'utilisateur. La sécurité repose sur la relecture du mainteneur, les empreintes SHA-256 vérifiées
> à l'installation (un fichier modifié après fusion est refusé) et la confirmation de l'utilisateur.

## Pour le mainteneur

- Relire le diff **en entier** (CODEOWNERS vous désigne automatiquement) ; vérifier que chaque permission est justifiée.
- Fusionner (squash conseillé). Le job `index` de `.github/workflows/plugins.yml` régénère `index.json` et le pousse.
- Retirer un plugin : supprimer son dossier ; l'index est régénéré à la fusion.
- Marketplace alternatif : *Paramètres → Plugins* n'a pas besoin de réglage, mais `plugins.market_url`
  dans la configuration peut pointer vers un autre dépôt (HTTPS obligatoire, même format d'index).

## Plugins fournis

| Plugin | Ce qu'il montre |
|---|---|
| `ui-tweaks` | modifier l'interface par feuille de style (compact, arrondis, police) |
| `quick-notes` | onglet de projet avec réglages persistants |
| `focus-timer` | widget de barre d'état, raccourci clavier |
| `todo-scanner` | onglet + analyse en arrière-plan (`run_async`) |
| `git-insights` | `api.run` (commandes git) dans un onglet |
| `zen-mode` | bouton de barre d'outils, accès à la fenêtre (`main_window`) |
| `neon-themes` | `register_theme` : trois thèmes supplémentaires |
| `project-counter` | barre d'état, menu clic droit, événements |
