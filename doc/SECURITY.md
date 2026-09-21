# Sécurité — modèle et audit (v1.0.3)

## Ce qui est protégé, et comment

| Donnée | Protection |
|--------|-----------|
| Token OAuth / GitHub App | Chiffrement AES-256 (Fernet + PBKDF2) optionnel, voir [VAULT.md](VAULT.md) |
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

## Audit 1.0.3

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

## Signaler une vulnérabilité

Ouvrez une *security advisory* privée sur le dépôt GitHub plutôt qu'une issue publique.
