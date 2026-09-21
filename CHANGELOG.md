# Changelog — Voktora

Toutes les modifications notables de ce projet sont documentées ici.  
Format : [Semantic Versioning](https://semver.org/) — `MAJEUR.MINEUR.CORRECTIF`

---

## [1.0.2] — 2026-08-24

### Architecture

- **Compilation via Docker.** Les paquets `.deb` (Linux) et `.msi` (Windows) se compilent
  désormais dans des images Docker dédiées (`docker/linux.Dockerfile`,
  `docker/windows.Dockerfile`), pour un build identique en local, entre contributeurs et en
  CI. Voir `docker/README.md`, y compris une note sur la signature de code (le `.msi` reste
  non signé — Docker ne résout pas ce point, seul un certificat de signature le peut).
- **Découpage des trois plus gros fichiers en packages par domaine** (~75 % du code) :
  - `core.py` (2533 lignes) → package `core/` : `constants`, `paths`, `config_store`,
    `drives`, `crypto`, `github_auth`, `projects`, `git_ops`, `system`, `diagnostics`.
  - `ui_dialogs.py` (3226 lignes) → package `ui_dialogs/`, un fichier par boîte de dialogue.
  - `ui_main.py` (4491 lignes) → package `ui_main/` (workers, dialogues annexes,
    `main_window.py`).
  - Compatibilité totale préservée (`import core`, `core.get_data_dir()`, etc. inchangés).
- **Tests.** Suite pytest ajoutée (auparavant inexistante) : 112 tests couvrant la config,
  le chiffrement, le vault, Git, les migrations, le nouveau package `core/`, et l'UI Qt
  (import réel avec PySide6, `QT_QPA_PLATFORM=offscreen`). Nouveau job CI `test` (lint ruff +
  pytest) sur chaque push/PR.

### Ajouté

- **Système de tags** : champ `tags` sur les instances/intents, éditable dans le dialogue de
  personnalisation, utilisable dans la recherche.
- **Recherche par tags**, en plus du nom et du chemin.
- **Bascule Instance ↔ Intent** directement depuis le panneau de projet (la logique backend
  existait déjà mais n'était appelée nulle part).
- **Import de dossier non compressé** (en plus du `.zip`), sans jamais modifier ni supprimer
  le dossier source.
- **Sélecteur d'emoji** dédié (menu par catégories avec recherche), en plus du champ existant.
- **Markdown dans les descriptions de projet**, avec bascule aperçu/édition ; et **repli
  automatique sur le premier `README.md`** du dossier quand aucune note n'existe encore.
- **Éditeur JSON avancé de `config.json`**, réservé au dépannage : avertissement explicite,
  validation de syntaxe séparée, sauvegarde automatique horodatée avant tout écrasement.
- **Génération via Ollama (local)** : description de projet et suggestion d'emoji, via un
  serveur Ollama local configurable (réglages → section "🤖 Ollama"). Aucune donnée envoyée
  en dehors de la machine de l'utilisateur.

### Corrigé

- **Notification "GitHub non connecté" à chaque lancement, même connecté** — le diagnostic de
  démarrage confondait "Client ID OAuth non configuré" avec "compte non connecté".
- **Recherche invisible en mode grille/bloc** — la barre de recherche vivait dans la vue
  liste, entièrement masquée en mode grille. Déplacée au niveau partagé, active dans les deux
  modes désormais. Le nombre de cartes par ligne en mode grille a aussi été augmenté.
- **`Échap` provoquait un plantage** (`AttributeError` sur des attributs jamais définis).
- **Déverrouillage du vault totalement cassé** (`NameError: name 'hmac' is not defined` —
  import manquant) : toute tentative de déverrouillage avec mot de passe maître échouait.
- **Deux `NameError` dans `ui_dialogs.py`** (`hashlib`, `shutil` non importés) affectant le
  chiffrement de projet et la copie de snapshots.
- **Fonctionnalité de migration multi-ordinateur entièrement cassée** (`mc.py`, module
  référencé partout mais absent du dépôt) : reconstruite, en excluant délibérément tout secret
  (token GitHub, vault) du bundle exporté.
- **`core._whirlpool_available()` inexistante** appelée à 3 endroits (plantage juste après un
  chiffrement réussi) ; au passage, 4 libellés d'interface annonçant à tort un chiffrement
  "Whirlpool + XOR" ont été corrigés pour refléter l'algorithme réellement utilisé (AES-256 /
  Fernet, PBKDF2-HMAC-SHA256).
- **Méthodes dupliquées** dans `MainWindow` (`act_open_terminal`, `act_open_explorer`,
  `act_open_vscode`) — la définition dupliquée, qui l'emportait silencieusement, avait perdu
  la gestion d'erreur de la version originale.
- **Écrasement possible du `.git` d'un projet existant** lors d'un clone dans un dossier déjà
  suivi par Git — le filtrage prévu n'était pas appliqué.
- **Header HTTP `X-GitHub-Api-Version` corrompu** en `X-GitHub-Api-constants.Version` sur les
  requêtes GitHub App (régression introduite puis détectée et corrigée pendant le découpage
  en package).
- Constante de schéma de configuration obsolète (`CONFIG_SCHEMA_VERSION`), messages de commit
  Conventional Commits mal classés pour les fichiers de test, plusieurs imports inutilisés ou
  mal ordonnés, variables et code mort divers.

---

## [1.0.1] — 2025-01-01

### Corrigé

- **Critique — `TypeError: vault_store() got an unexpected keyword argument 'domain'`**  
  Deux fonctions `vault_store` coexistaient dans `core.py`. Python écrase silencieusement
  la première définition par la seconde : la version légacy `vault_store(path, token)` (cache
  de session) shadait la version cryptographique `vault_store(key, value, domain)`.  
  Résultat : toute tentative d'associer un compte GitHub (chiffré ou non) levait une
  `TypeError`. Correctif : renommage en `vault_session_store()` et `vault_session_clear()` ;
  une seule `vault_store()` cryptographique existe désormais dans le code.

- Avertissements au démarrage `Could not parse stylesheet of object QLineEdit`  
  Stylesheets invalides sur certains champs du dialog GitHub.

### Ajouté

#### Vérification automatique des mises à jour
- `core.check_for_update()` interroge l'API GitHub Releases
  (`repos/yo-le-zz/Voktora/releases/latest`) et compare sémantiquement les versions via
  `core._version_gt()`.
- `UpdateCheckWorker` (QThread) lance la vérification 3 secondes après le démarrage,
  sans bloquer l'interface.
- Si une nouvelle version est détectée : bannière bleue non bloquante en haut de la
  fenêtre principale, avec bouton **Télécharger** (ouvre la page GitHub Releases) et
  bouton **✕** pour fermer. Aucune bannière si la version est à jour.

#### Mode grille — colonnes dynamiques
- Le nombre de colonnes (2 à 7) est recalculé automatiquement à chaque `resizeEvent`
  selon la largeur disponible du viewport.
- Re-rendu instantané sans perte de la sélection en cours.
- Objectif : 6–7 cartes par ligne sur un écran large, 2 sur un écran étroit.

#### Tri multi-critères
- Nouveau `QComboBox` dans la barre de contrôle du `ProjectBrowser` :
  **Nom A→Z**, **Nom Z→A**, **Date (récent)**, **Date (ancien)**, **Langage**,
  **Statut**, **Type** (instances d'abord).
- Tri appliqué simultanément aux modes liste et grille.
- Persistance par session (réinitialisé à "Nom A→Z" au prochain lancement).

#### Ping — vérification d'accessibilité
- Bouton **⬤ Ping** dans la barre de contrôle : vérifie tous les projets visibles
  en thread daemon (non bloquant).
- En mode liste : les entrées se colorent en vert (dossier OK + Git), jaune
  (dossier OK sans Git) ou rouge (dossier introuvable), avec tooltip explicatif.
- En mode grille : chaque carte affiche un point coloré en coin supérieur droit ;
  clic individuel pour pinger un seul projet.

#### Drag-and-drop dans la vue liste
- Réordonnancement par glisser-déposer activé sur les listes Instances et Intents
  (`QAbstractItemView.InternalMove`).
- L'ordre est persisté automatiquement dans la configuration (`core.reorder_entries()`)
  150 ms après le drop, pour éviter les écritures en rafale.

### Technique interne

- `core.reorder_entries(kind, ordered_paths)` : persiste l'ordre drag-and-drop dans
  `config.json` ; les entrées absentes de la liste sont ajoutées à la fin (sécurité).
- `core._version_gt(v1, v2)` : comparaison sémantique `X.Y.Z`, robuste aux préfixes `v`.
- `_build_update_banner()` : construction déclarative de la bannière de mise à jour
  (layout VBox inséré au-dessus du splitter principal dans `_build_ui`).

---

## [1.0.0] — Release initiale

### Ajouté

- Gestion d'instances et d'intents (projets locaux organisés par type)
- Vault chiffré AES-256 (Fernet + dérivation PBKDF2-HMAC-SHA256)
- Authentification GitHub — OAuth Device Flow et GitHub App (PEM)
- Templates de projets : Python, C++, Web App, Discord Bot, Minecraft Mod, Vide
- Dashboard de santé : repos cassés, branches en retard, `.gitignore` manquant, inactivité
- Système de hooks (`on_create`, `on_open`, `on_delete`, `on_clone`, `on_git_push`, ...)
- Système de plugins Python (API `register_command`, `register_button`, `register_hook`)
- Snapshots de projets (`.snap` = zip structuré avec manifeste)
- Profils d'exécution par projet (env vars, commande de lancement, pre/post scripts)
- Vues liste et grille avec switch dynamique
- Thèmes : Dark (défaut), Light, CRT Cyberpunk + thèmes personnalisés JSON
- Export / import de configuration JSON
- Auto-commit et auto-push Git avec messages Conventional Commits générés localement
- Raccourcis clavier : F5 (actualiser), Ctrl+N (nouvelle instance), Ctrl+F (recherche)
