# Sécurité — modèle et audit (v1.0.4)

## Ce qui est protégé, et comment

| Donnée | Protection |
|--------|-----------|
| Token OAuth / GitHub App | Chiffrement Fernet (AES-128-CBC + HMAC-SHA256, clé PBKDF2) optionnel, voir [VAULT.md](VAULT.md) |
| Token GitHub à l'exécution de git | Variables d'environnement `GIT_CONFIG_*`, en-tête limité à `https://github.com/` ; jamais dans l'URL d'un remote, jamais en argument (visible dans la liste des processus) |
| `config.json` | Créé en `0600` sous Linux |
| Exports, bundles `.mpack`, snapshots | Identifiants retirés de `.git/config` ; export global et bundles sans compte GitHub ni tokens de projet |

Un token de projet non protégé par mot de passe reste stocké en clair dans `config.json` : activez
la protection par mot de passe si l'ordinateur est partagé.

## Entrées non fiables

Une archive ZIP, un dossier importé, un dépôt cloné ou un nom de branche peuvent venir d'un tiers.

- **ZIP** : chaque nom de membre est validé (pas de chemin absolu, de `..`, de lecteur Windows) et
  vérifié à nouveau après résolution ; liens symboliques ignorés ; espace disque contrôlé avant
  extraction ; un membre plus grand que la taille annoncée fait échouer l'import ; extraction dans un
  dossier temporaire puis renommage atomique.
- **Noms de projet** : ils sont passés aux applications externes (terminal, explorateur, « ouvrir
  avec ») comme arguments ou répertoire de travail, jamais interpolés dans une chaîne de shell.
- **git** : les URL de clone sont limitées à `http(s)`, `ssh`, `git` et `utilisateur@hôte:chemin`
  (`ext::`, chemins locaux et `--option` refusés) ; noms de branche validés ; `--` précède les opérandes.
- **Déplacement de dossier** : refusé pour une racine de disque ou le dossier personnel.

## Ce qui reste à la charge de l'utilisateur

- Les **hooks** et **profils d'exécution** lancent des commandes shell que vous écrivez : c'est leur
  rôle. Ils sont stockés dans le dossier de données de Voktora, pas dans les projets — importer un
  projet ne peut donc pas en installer.
- Les **plugins** exécutent du code Python : n'installez que des plugins de confiance.
- Le **`.msi` n'est pas signé** (voir [BUILD.md](BUILD.md)).

## Audit 1.0.3 (historique)

Deux passes ont été faites (avant puis après correction) sur la configuration, l'authentification git,
l'import/export, l'ouverture d'applications externes et les dialogues.

| Gravité | Constat | État |
|---------|---------|------|
| Élevée | Token GitHub écrit dans l'URL de `origin` (donc dans `.git/config`, exports et snapshots) et passé en argument de ligne de commande | Corrigé |
| Élevée | Injection de commande via un nom de projet (`'; cmd; '`, `$(cmd)`) dans « Ouvrir un terminal » / « Ouvrir avec » | Corrigé |
| Moyenne | Un ZIP pouvait écrire hors du dossier cible ou saturer le disque | Corrigé (validation, contrôle d'espace) |
| Moyenne | `config.json` lisible par tous les utilisateurs de la machine | Corrigé (`0600`) |
| Moyenne | Tokens de projet inclus dans les bundles de migration | Corrigé |
| Moyenne | Un fichier `settings.json` étranger était absorbé puis supprimé au démarrage | Corrigé |
| Faible | URL de clone / noms de branche non validés (injection d'option git) | Corrigé |
| Faible | Suppression partielle silencieuse (`ignore_errors`) | Corrigé |
| Info | Tokens de projet non protégés stockés en clair | Documenté ci-dessus |

Les tests correspondants sont dans `tests/test_security.py`, `tests/test_git_auth.py` et
`tests/test_archive.py`.

## Audit 1.0.4

Deux passes (avant puis après correction), orientées application de bureau : fichiers locaux,
processus lancés, archives non fiables, secrets stockés, chaîne de build.

### Élevée

| Constat | Impact | Correctif | État |
|---------|--------|-----------|------|
| Coffre : le *verifier* stocké dans `config.json` contenait la clé maître (PBKDF2 `dklen=64` vs `dklen=32` : les 32 premiers octets sont identiques) | Toute personne ayant lu `config.json` (ou une de ses sauvegardes) pouvait déchiffrer tout le coffre **sans le mot de passe** | Verifier = HMAC-SHA256 de la clé maître (à sens unique). Migration automatique au déverrouillage avec nouveau sel, donc nouvelle clé, et rechiffrement des secrets (tout ou rien) | Corrigé |
| Chiffrement de projet = XOR avec SHA-512(mot de passe), sans sel ni authentification ; mauvais mot de passe au déchiffrement = fichiers corrompus **et** originaux supprimés ; fichier entier chargé en mémoire | Aucune confidentialité réelle ; perte de données ; crash mémoire sur gros fichiers | AES-256-GCM en flux (blocs de 1 Mo authentifiés, clé scrypt, sel par opération, en-tête lié aux blocs). Mauvais mot de passe / altération / troncature détectés avant toute écriture définitive. Ancien format toujours déchiffrable | Corrigé |
| Workflow CI : titre de PR interpolé dans un script shell (`${{ github.event.pull_request.title }}`) avec un jeton en écriture | Exécution de commande dans la CI avec un titre piégé | Titre lu via variable d'environnement, validé (`v1.2.3`) dans un job dédié ; droits du jeton réduits par job | Corrigé |

### Moyenne

| Constat | Correctif | État |
|---------|-----------|------|
| Restauration de snapshot : noms de membres non validés (écriture hors du dossier cible) et dossier cible supprimé avant extraction | Validation des noms, liens ignorés, extraction dans un dossier temporaire puis échange | Corrigé |
| Script de désinstallation à nom fixe dans `/tmp`, chemins interpolés dans le shell, suppression possible d'un dossier de sources ou personnel | Fichier privé à nom aléatoire, `shlex.quote`, refus des dossiers système/personnel et du dossier des sources | Corrigé |

### Faible

| Constat | Correctif | État |
|---------|-----------|------|
| `config.json.tmp` créé en `0644` puis `chmod 0600` (fenêtre de lecture) | Création directe en `0600` | Corrigé |
| `open_url_in_browser` acceptait n'importe quel schéma (`file:`, `ms-…:`) | `http` / `https` uniquement | Corrigé |
| Dépendances de build non figées (`pip install` sans version) | Installation depuis `uv.lock` | Corrigé |

### Information

- Fernet est AES-128-CBC + HMAC-SHA256 (clé de 32 octets). Les libellés « AES-256 » du coffre étaient
  inexacts et ont été corrigés ; le format n'a pas été changé.
- PBKDF2 reste à 480 000 itérations (compatibilité des coffres existants) ; OWASP recommande
  600 000 pour PBKDF2-HMAC-SHA256. À relever avec un champ de version dans une prochaine release.
- Les anciennes copies de `config.json` (dossier de sauvegardes) créées **avant** la 1.0.4 contiennent
  encore l'ancien verifier : supprimez-les, et régénérez par précaution les tokens du coffre.
- Les **plugins** s'exécutent avec les droits de l'utilisateur dès leur chargement : leur dossier
  (`data/plugins`) est une frontière de confiance.
- Le **`.rpm` n'est pas signé** (pas plus que le `.deb` et le `.msi`) ; publiez et vérifiez `SHA256SUMS`.

Tests : `tests/test_vault.py`, `tests/test_file_crypto.py`, `tests/test_snapshots.py`,
`tests/test_full_export.py`, `tests/test_security.py`, `tests/test_archive.py`.

## Signaler une vulnérabilité

Ouvrez une *security advisory* privée sur le dépôt GitHub plutôt qu'une issue publique.

## Plugins et marketplace (1.0.6)

- Un plugin est du code exécuté avec les droits de l'utilisateur : les permissions (`ui`, `projects.read`, `files`,
  `network`, `shell`) sont déclarées, affichées avant l'installation et vérifiées par l'API, mais **ce n'est pas un
  bac à sable**.
- Le marketplace n'est lu qu'en HTTPS ; chaque fichier téléchargé est comparé à son empreinte SHA-256 de l'index
  (un fichier modifié est refusé), les noms de fichiers sont filtrés (pas de `..`, de chemin absolu, de lien
  symbolique, extensions autorisées uniquement) et la taille est bornée. Une installation échouée laisse
  l'ancienne version intacte.
- Les contributions passent par Pull Request : validation automatique (`tools/plugin_tool.py validate` : manifeste,
  analyse statique refusant `eval`/`exec`/`os.system`/`shell=True` et les imports réseau/`subprocess` non déclarés)
  puis relecture du mainteneur (CODEOWNERS).
- **Plugins communautaires** (sous-modules Git) : le code est **épinglé sur un commit** ; l'index contient
  l'adresse du dépôt, le SHA du commit et le SHA-256 de chaque fichier ; l'application télécharge
  `raw.githubusercontent.com/<dépôt>/<commit>/…` (immuable). Si l'auteur modifie son dépôt, rien ne change chez
  les utilisateurs : une nouvelle PR (nouveau commit, `version` augmentée) et une nouvelle relecture sont
  nécessaires, même pour un plugin déjà accepté. Les PR communautaires ne peuvent modifier que leur
  sous-module ; `.gitmodules` n'accepte que `path` et `url` (`https://github.com/<auteur>/<dépôt>`).
- **Intégrité locale** : `.source.json` enregistre le SHA-256 de chaque fichier installé ; à chaque démarrage et
  juste avant l'exécution, tout écart (modifié, ajouté, supprimé) bloque le chargement.
- **Défense en profondeur** : analyse statique identique CI/application ; builtins filtrés et garde d'imports par
  permission à l'exécution ; liste de retraits (`revoked.json`) vérifiée au plus toutes les 24 h en arrière-plan ;
  les contrôles de PR utilisent l'outil de la branche `main`, jamais celui de la PR.
- Limite connue : du code Python déterminé peut contourner une analyse statique ou une garde d'imports ; ce n'est
  pas un bac à sable. La relecture humaine du commit épinglé reste la barrière principale.
- Un plugin en erreur est isolé : ses exceptions sont capturées et affichées, sans arrêter l'application.
