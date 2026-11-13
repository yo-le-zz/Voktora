# Marketplace de plugins Voktora

Ce dossier est le **catalogue officiel** : Voktora (Paramètres → Plugins → Marketplace) lit
`index.json` et installe les plugins de `plugins/`. Tout y arrive par **Pull Request**.

## Deux types de plugins

| | **Officiel** | **Communauté** |
|---|---|---|
| Où est le code ? | `marketplace/plugins/<id>/` dans CE dépôt | dans **votre dépôt (fork)**, relié ici par un **sous-module Git** |
| Qui l'écrit ? | le mainteneur (plugins par défaut) | n'importe qui |
| Chargement | tout le dépôt Voktora | seulement les quelques fichiers du plugin, au commit exact épinglé |
| Badge dans l'application | Officiel | Communauté (+ dépôt et commit affichés) |

## Proposer un plugin communautaire (fork → sous-module → Pull Request)

1. Créez **votre propre dépôt public** (ou un fork de Voktora réduit à votre plugin) contenant à la racine
   `plugin.json` + `main.py` (squelette : `python tools/plugin_tool.py new mon-plugin`, puis déplacez le dossier
   créé dans votre dépôt).
2. **Fork** de ce dépôt (bouton *Fork*) et clonez-le. Ajoutez votre plugin en sous-module :
   ```bash
   python tools/plugin_tool.py submit https://github.com/votre-pseudo/mon-plugin
   ```
   (équivalent de `git submodule add <url> marketplace/community/mon-plugin`). L'URL doit être
   `https://github.com/<auteur>/<dépôt>` : ni ssh, ni `file://`, ni identifiants.
3. Vérifiez : `python tools/plugin_tool.py validate mon-plugin`, committez **uniquement** le sous-module et
   `.gitmodules`, poussez sur votre fork et ouvrez une **Pull Request** vers `main`
   (ajoutez `?template=community-plugin.md` à l'URL pour la liste de contrôle).
4. La CI vérifie les règles de PR, récupère uniquement votre sous-module, relance l'analyse de sécurité et publie
   un résumé (fichiers et diff) pour le mainteneur, qui relit le code puis fusionne. L'`index.json` est
   régénéré tout seul : il contient l'adresse de votre dépôt, le **commit épinglé** et l'empreinte SHA-256 de
   chaque fichier.

### Mettre à jour un plugin communautaire — une NOUVELLE PR est toujours nécessaire

L'application télécharge votre code **au commit épinglé**, jamais « la dernière version de votre dépôt ».
Donc, si vous poussez du nouveau code dans votre dépôt, **rien ne change chez les utilisateurs** tant que
vous n'avez pas ouvert une nouvelle Pull Request qui avance le pointeur du sous-module — **même si votre plugin
a déjà été accepté**. Cette PR repasse par la validation automatique et par la relecture du mainteneur :

```bash
git submodule update --remote marketplace/community/mon-plugin   # avance sur votre dernier commit
# augmentez "version" dans plugin.json (dans VOTRE dépôt, avant d'épingler) : la CI le exige
git add marketplace/community/mon-plugin && git commit -m "mon-plugin 1.1.0" && git push
```

Une PR qui change le commit épinglé sans augmenter `version` est refusée. Une PR communautaire ne doit rien
modifier d'autre que son sous-module (et l'entrée correspondante de `.gitmodules`).

## Proposer un plugin officiel (par défaut)

Réservé au mainteneur (CODEOWNERS) : même flux, mais le code est dans `marketplace/plugins/<id>/`
(`python tools/plugin_tool.py new mon-plugin`).

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
> l'utilisateur. La sécurité repose sur plusieurs couches cumulées :
> 1. **commit épinglé** : le code d'un plugin communautaire ne change jamais sans nouvelle PR relue ;
> 2. **empreintes SHA-256** vérifiées au téléchargement, puis **à chaque démarrage** (fichier modifié, ajouté
>    ou supprimé sur le disque → le plugin ne se charge pas) ;
> 3. **analyse statique identique** dans la CI et dans l'application (imports dangereux, `eval`/`exec`,
>    contournements par introspection…), rejouée à l'installation et au chargement ;
> 4. **garde d'imports à l'exécution** : un plugin du marketplace s'exécute sans `eval`/`exec`/`compile` et ne peut
>    importer réseau/`subprocess` que s'il en a déclaré la permission ;
> 5. **liste de retraits** (`marketplace/revoked.json`) : un plugin retiré est déchargé et bloqué chez tous les
>    utilisateurs en ligne dans les 24 h ;
> 6. relecture du mainteneur + confirmation explicite de l'utilisateur (permissions, dépôt, commit).

## Pour le mainteneur

- Relire le diff **en entier** (CODEOWNERS vous désigne automatiquement) ; vérifier que chaque permission est justifiée.
- Fusionner (squash conseillé). Le job `index` de `.github/workflows/plugins.yml` régénère `index.json` et le pousse.
- Pour une PR communautaire, lisez le **résumé de la CI** (`pr-summary`) : lien « compare » entre l'ancien et le
  nouveau commit, liste des fichiers modifiés. Lisez le code au commit épinglé, pas la branche de l'auteur.
- Chaque semaine, `plugins-drift.yml` signale les dépôts d'auteurs qui ont avancé (information : les utilisateurs
  restent sur le commit épinglé) ou disparu.
- Retirer un plugin : supprimer son dossier / sous-module. Pour le bloquer **tout de suite** chez ceux qui
  l'ont déjà installé, ajoutez-le à `marketplace/revoked.json` :
  `[{"id": "mon-plugin", "reason": "…", "commit": "<sha optionnel : seulement ce commit>"}]`.
- Les contrôles de PR s'exécutent avec l'outil de la branche `main` (pas celui de la PR) : une PR ne peut pas
  affaiblir ses propres vérifications.
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
| `project-counter` | barre d'état, menu clic droit, événements |


## Boutiques d'apparence (1.1.1)

Les thèmes, packs d'icônes et styles ne sont plus des plugins : chaque type a **sa propre boutique** dans
`marketplace/shops/<type>/` (`index.json` + `items/<id>/`). Les trois thèmes de l'ancien plugin `neon-themes`
(Neon Night, Coffee, Mint) y sont désormais des objets à part entière. Voir `doc/SHOPS.md`.

```
python tools/shop_tool.py new themes mon-theme   # modèle
python tools/shop_tool.py validate               # règles de sécurité (SVG, QSS, extensions)
python tools/shop_tool.py build-index            # régénère les index (SHA-256)
```
