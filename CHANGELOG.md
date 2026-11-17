# Changelog — Voktora

Toutes les modifications notables de ce projet sont documentées ici.  
Format : [Semantic Versioning](https://semver.org/) — `MAJEUR.MINEUR.CORRECTIF`

---

## [1.1.6] — 2026-11-16

### 🛠️ Corrections
- **Build macOS** : l'icône PNG est convertie en `.icns` avec `sips`/`iconutil` (plus d'erreur « Need to install 'imageio' »).
- **Compilation plus rapide** : pas de LTO sur macOS par défaut (`VOKTORA_LTO=yes` pour l'activer), ccache, cache de Nuitka entre les runs CI.
- **`build.sh`** (Linux/macOS) : compilation locale rapide — `./build.sh` (rapide), `run`, `release` (LTO), `dev` (sans compiler), `clean`.
- **Installation en une commande** : `Installers/install.sh` (Linux — distribution détectée — et macOS Intel) et `install.ps1` (Windows, non testé) téléchargent le bon paquet, vérifient son SHA-256 puis l'installent ; mode live équivalent pour chaque système. Site mis à jour (macOS, commandes uniques).
- Tests : le test du plugin retiré `project-counter` est supprimé (il échouait à l'import).

## [1.1.5] — 2026-11-16

### 🧪 Mode live
- **Une commande, aucune installation** : `curl -fsSL https://raw.githubusercontent.com/yo-le-zz/Voktora/main/Installers/live/install-live.sh | sh` (Windows : `install-live.ps1`, non testé). Le script télécharge la version demandée, prépare Python 3.13 et les dépendances **dans un dossier temporaire** `voktora-live-XXXXXXXX` (uv y est installé si absent), lance Voktora, puis **supprime tout** à la fermeture — y compris après Ctrl+C, fermeture du terminal ou plantage. Les sessions abandonnées (kill -9) sont nettoyées au lancement suivant.
- Dans l'application (`voktora/live.py`) : configuration, plugins, boutiques, coffre et projets créés vivent dans le dossier live ; fenêtre « Tout supprimer et fermer / Exporter mes projets / Rester » à la fermeture ; synchronisation, mise à jour automatique et moniteur développeur désactivés ; titre « MODE LIVE ». Nouveau réglage d'environnement `VOKTORA_DATA_DIR` (dossier de données au choix).
- Garde-fous de suppression : jamais un dossier arbitraire (nom `voktora-live-<alphanum>`, marqueur `.voktora-live`, dossier réel hors lien symbolique, situé dans le dossier temporaire).

### 🧰 Ajouts de dernière minute
- **Workflow Forge 1.3.0** : bouton ⤵ pour transmettre les données d'un bloc à l'autre (contenu de fichier, réponse HTTP, variables), « Supprimer le bloc » séparé de « Supprimer le workflow », bouton « Arrêter » réparé (il ne marchait qu'à la première exécution), très grande zone de travail déplaçable, modèle « Test » et 3 modèles complexes (CI complet, comptage de lignes, surveillance d'API).
- **Marketplace des plugins** : « Tout mettre à jour (N) » et « Mode non vérifié » (download unsafe : ni SHA-256, ni signature, ni analyse — avec confirmation ; les plugins installés ainsi sont marqués `unsafe`).
- **Journal global** : le moniteur développeur voit enfin l'activité (commandes lancées, réseau, fichiers supprimés/déplacés, console, avertissements, journaux des panneaux et de la synchro).
- **Icônes** manquantes (se déconnecter, accessibilité, suggestion de commit, archives, actualiser…) et 15 autres emojis convertis.
- **Clés de confiance** : `voktora/trusted_keys.json` (clé publique de yolezz) au lieu d'une constante dans le code, copié par les builds.
- **Build macOS Intel (x86_64)** : `.dmg` dans la release (non testé sur un vrai Mac).
- Domaine du site : https://voktora.pages.dev/

### 🔐 Sécurité
- Boutiques : identifiant et noms de fichiers revalidés avant les aperçus (pas de sortie du cache).
- Archivage : une archive n'est lue/supprimée que dans le dossier des archives (une config modifiée ne peut plus viser un autre fichier).
- Suggestions IA de commit : `git` est lancé sans fsmonitor, sans hooks, sans diff externe ni textconv (un dépôt non fiable ne peut rien exécuter).
- Notifications : `--` avant le titre (pas d'injection d'option dans `notify-send`).
- Import de thèmes en lot : taille réellement lue plafonnée (ZIP piégé).
- Sync : le réglage `marketplace` (clés de confiance, `allow_unsigned`) n'est jamais poussé par un pair.
- Site : `_headers` (CSP stricte, nosniff, no-referrer, frame-ancestors none).

## [1.1.4] — 2026-11-16

### 🔎 Marketplaces : recherche intelligente, « Tout installer », aperçus
- **Barre de recherche commune** (plugins, thèmes, icônes, styles) conçue pour des milliers d'éléments : `mot`, `"expression exacte"`, `-exclure`, `tag:sombre`/`#sombre`, `lang:rust`, `auteur:…`, `perm:network`, `is:installed|new|update|active|community`, `sort:name|recent`, tolérance aux fautes de frappe, complétion et puces de filtres. 5 000 éléments en < 1 s (testé). Voir `voktora/catalog_search.py`.
- **Tout installer** (sur le filtre en cours) dans le marketplace de plugins (confirmation avec permissions cumulées, plugins communautaires et natifs signalés) et dans chaque boutique (échecs isolés, vérification SHA-256 de chaque fichier).
- **Aperçu des icônes et des styles même NON installés** (fichiers téléchargés, vérifiés par empreinte, mis en cache, jamais exécutés) ; les styles s'affichent sur une maquette de widgets.

### 🔄 Synchronisation
- **Push config** : toute la configuration non sensible (réglages, thèmes/icônes/styles installés, liste de plugins + options, profils, hooks…) est poussée chiffrée ; aperçu des différences, sauvegarde et application atomique avec retour arrière côté pair.
- **Obligatoire pour synchroniser** : la sync des projets est bloquée tant que les configurations divergent (message + boutons de résolution) → aucun conflit silencieux.
- **Mode dirigé** : un PC « chef » est la source de vérité (époque croissante contre le split-brain, abdication, proposition/accord) ; mode égalitaire conservé.
- **Pause / Reprendre / Stop** dans la fenêtre de sync (nouvel onglet « Groupe & config ») et dans l'API du service ; Stop ne laisse aucun fichier partiel.
- La synchronisation fonctionne avec **plus de deux PC** (envoi de config à tous, rôles par PC).

### 🛰️ Moniteur développeur
- **Canal sécurisé** : secret partagé aléatoire (32 octets) transmis au moniteur par un tube anonyme ; journal **chiffré AES-256-GCM et chaîné** (ligne modifiée, supprimée, déplacée ou forgée = rejetée et signalée), commandes de contrôle authentifiées et anti-rejeu, fichiers 0600 / dossier 0700.
- Il voit maintenant les **changements d'onglet, ouvertures de menus, actions de menu, choix dans les listes, fenêtre active**.

### 🧩 Plugins
- **Workflow Forge 1.2.0** : panneau de propriétés par bloc (texte, nombre, MENU, chemin, variable, durée, expression, paires clé/valeur), résumé lisible dans le bloc, double-clic, annuler/rétablir, dupliquer, copier/coller, réordonner, recherche dans la palette, 6 modèles.
- **Retirés** (doublons) : quick-note, ui-tweaks, project-counter, json-clipboard-js, generators-js.

### 🧰 Anciens reports, maintenant faits
- **Archivage de projets** (ZIP vérifié SHA-256, suppression optionnelle du dossier après relecture, restauration).
- **Notifications de bureau** (sync, mises à jour, plugins, tâches, plantages ; heures « ne pas déranger », historique).
- **Raccourcis clavier personnalisables** avec import/export JSON validés ; **import de thèmes en lot** (dossier ou ZIP).
- **Accessibilité** : taille du texte, contraste renforcé, focus épais, réduction des animations, noms accessibles des boutons-icônes, audit.
- **Suggestions IA** : message de commit (Conventional Commits) et explication du diff — Voktora ne commit ni ne pousse jamais ; diff borné, secrets masqués, fichiers sensibles ignorés, avertissement si le fournisseur n'est pas local.
- **Index du marketplace signé (Ed25519)** : `tools/sign_index.py keygen|sign|verify` ; exigé dès qu'une clé est dans `TRUSTED_KEYS` (`voktora/signing.py`).

### 🌐 Site et correctifs
- Site multi-pages (accueil, téléchargement, fonctions, plugins avec recherche, docs, changelog), animations sobres, thème clair/sombre.
- **CI** : `.gitignore` ignorait `lib/` et donc les bibliothèques JS des plugins → fichiers absents du dépôt → échecs. Règle de ré-inclusion ajoutée.

### ⚠️ Limites connues
- Les aperçus de styles sont approximatifs (le thème actif n'est pas appliqué à la maquette).
- Signature : aucune clé n'est livrée ; la protection s'active quand vous ajoutez votre clé publique et signez l'index en CI.
- Canal du moniteur : un processus du MÊME utilisateur capable de lire la mémoire de Voktora peut obtenir le secret.
- Non testé de bout en bout : push de config entre deux vrais PC, mode dirigé en réseau réel, notifications sous Windows/macOS, script de mise à jour Windows.
- Le glisser pour réordonner de Workflow Forge ne gère que les suites simples ; les déclencheurs restent en JSON.

---

## [1.1.3] — 2026-11-14

### 🛰️ Moniteur développeur global (nouveau)
- **Seconde fenêtre dans un processus DÉTACHÉ** : elle ne bloque pas Voktora et reste ouverte si Voktora plante. Elle suit en direct
  un journal JSON Lines (`<données>/devmon/session-*.jsonl`) : exceptions non gérées (fil principal, threads, « unraisable »),
  plantages natifs (`faulthandler`), journaux Python et messages Qt, clics, menus, raccourcis, fenêtres, hooks de plugins,
  écritures de configuration, blocages de l'interface (avec la pile du fil principal), battement de cœur → état *en marche / figé / arrêté / plantage probable*.
- **4 modes**, modifiables en direct depuis la fenêtre : `crash`, `normal`, `verbose`, `trace`.
- Activation : `voktora --dev[=mode]`, variable `VOKTORA_DEV`, ou Préférences › « Moniteur développeur global… » (option de démarrage automatique).
- Confidentialité : jamais le texte saisi ni le contenu des champs, secrets masqués, fenêtres de coffre/mot de passe ignorées, 10 sessions conservées, 25 Mo max par session.
- Voir `doc/DEVMONITOR.md`.

### 🎨 Boutiques : 45 thèmes, 8 packs d'icônes, 10 styles
- Packs d'icônes SVG (~185 icônes aux noms MDI, `currentColor` pris en charge) ; styles QSS sans `url()` ni `@import`.
- **Correctif** : la fenêtre des boutiques ne s'ouvrait pas (« je clique, rien ne se passe ») — une valeur par défaut évaluée trop tôt levait une `KeyError`
  quand un objet installé n'était pas encore dans le catalogue. Test de non-régression ajouté.

### 🧩 Plugins
- **Améliorés (1.1.0, avec tests et interface plus lisible)** : todo-scanner, git-insights, focus-timer, project-counter, zen-mode, quick-notes.
- **Nouveaux** : gitignore-gen, license-picker, changelog-builder, snippet-vault, color-lab (Python) ; text-case-js, json-clipboard-js, generators-js (JavaScript) ;
  loc-counter-rs (Rust, nécessite cargo).

### 🔄 Mise à jour automatique
- Nouveau script d'installation (`update_install.py`) : détecte l'architecture et la famille de distribution, choisit le bon fichier (deb/rpm/pacman/AppImage/tar/msi/exe),
  arrête Voktora (TERM puis KILL), installe en arrière-plan avec 2 tentatives, journal `update.log`, notification, relance de l'ancienne version en cas d'échec.

### 🌐 Site
- Page d'accueil beaucoup plus sobre : commandes d'installation (à copier) et un court paragraphe, polices système, clair/sombre automatique.

### 🔧 Divers
- Tests rendus indépendants des dossiers résiduels du dépôt (le catalogue `index.json` fait foi) ; verrou sur l'écriture de `config.json`.

### ⚠️ Limites connues
- Le script de mise à jour Windows (PowerShell) n'a pas été testé sous Windows. Les plugins Rust sont natifs (pas de bac à sable) et exigent cargo.
- Les packs d'icônes ne couvrent que ~185 noms MDI. Les générateurs aléatoires JS ne sont pas cryptographiques.
- Moniteur : le masquage des secrets est « au mieux » ; un plantage natif très précoce (avant l'activation) n'est pas capté.

---

## [1.1.2] — 2026-11-13

### 🧩 Cinq plugins avancés (marketplace officiel, API 5)
- **code-inspector** : analyse statique Python/Rust/JS/C++/config, graphe d'architecture (appels classés *certain / probable / inconnu*),
  ponts Python × Rust, audit de dépendances hors-ligne, exports JSON / Markdown+Mermaid / SVG / HTML interactif / PDF.
- **devops-center** : Git (sans push), Docker, SSH, GitHub, pipelines, déploiements avec sauvegarde et restauration automatique,
  confirmation obligatoire en production.
- **api-studio** : client HTTP (auth, OAuth2 + PKCE), variables, extraction, scripts Python/JS, WebSocket, serveur mock,
  import/export OpenAPI et Postman.
- **project-knowledge** : recherche plein texte BM25 + similarité TF-IDF (ce ne sont PAS des embeddings), wiki, diagrammes, doc d'API.
- **workflow-forge** : éditeur visuel d'automatisations (blocs, expressions, cron, déclencheurs, moteur d'exécution).
- Chacun a ses tests (`tests/test_plugin_*.py`) et passe `plugin_tool validate --run`.

### 🌐 Site et documentation
- Site : version affichée 1.1.2, présentation des cinq plugins et de la documentation développeurs.
- Documentation : fiches des plugins fournis (`doc/plugins/SHIPPED.md`), index du marketplace régénéré.

### 🔧 Divers
- Nettoyages ruff ; version synchronisée partout (1.1.2).

### ⚠️ Limites connues
- L'isolation des scripts n'est pas un bac à sable de sécurité ; le déploiement SSH n'a pas été testé sur un vrai serveur ;
  le jeton `http_in` de Workflow Forge est stocké en clair dans les données du plugin ; les blocs Rust/JS exigent rustc/node.
- Reporté : synchronisation >2 PC, notifications, archivage de projets, paquets signés, import de raccourcis/thèmes,
  accessibilité, suggestions IA de diff/commit.

---

## [1.1.1] — 2026-11-11

### 🔌 Plugins (API 5)
- **Plugins JavaScript** (processus isolé par plugin, `require`, `voktora.*`) et **plugins Rust** (compilés par Voktora, crates externes
  permises, SDK `native/sdk/voktora-plugin`). Presque aucun code de liaison.
- **Permissions détectées automatiquement** dans le code (Python, JS, Rust) ; `"permissions": "auto"` pour les plugins locaux ;
  le marketplace exige la liste explicite.
- **Options** (`api.options`) : onglet « Options » généré par Voktora pour chaque plugin.
- Des dizaines de méthodes d'API en plus : fichiers privés, journal, minuteries, raccourcis, docks, palette, dialogues, presse-papiers,
  système, fichiers de projet, outils IA fournis par les plugins, boutiques…
- **Dépendances entre plugins** (`dependencies`, `provide`/`plugin`), **bibliothèques Python par plugin** (`requires`, versions
  différentes d'un plugin à l'autre), **mises à jour automatiques** des plugins (jamais si nouvelle permission).
- Limites réseau et de taille par plugin supprimées.
- **Mode développeur** : console (tracebacks Voktora/plugin), rechargement automatique, auto-installation des imports,
  validation qui EXÉCUTE réellement le plugin (`plugin_tool validate --run`, `detect`, `fix-permissions`, `new --lang`).
- Documentation complète : `doc/plugins/` (référence d'API et icônes générées depuis le code : `tools/gen_api_doc.py`).
- Plugins fournis : api-plus, quick-note, system-monitor, dev-toolbox, theme-studio.

### 🎨 Boutiques d'apparence
- Boutiques de **thèmes**, d'**icônes** et de **styles** (SHA-256, https, filtrage SVG/QSS), compatibles avec les plugins ;
  les thèmes néon quittent le marketplace de plugins pour la boutique de thèmes.

### 🤖 Chat IA
- Vrai streaming, sans délai d'attente fixe, annulable, Markdown, interface refaite.

### 🆙 Mise à jour de Voktora
- Vérification des versions `vX.Y.Z` de `yo-le-zz/Voktora` (24 h), téléchargement vérifié par SHA-256, jamais d'auto-remplacement.

### 🐛 Corrections
- Icône de l'espace disque des projets.

---

## [1.1.0] — 2026-11-09

### ⚡ Synchronisation
- **Vérification rapide « déjà à jour »** : à la fin de chaque synchro réussie, Voktora garde une empreinte (noms + tailles +
  dates, **aucun contenu lu**) de chaque espace sur les deux PC. À la synchro suivante, si rien n'a bougé, c'est terminé en
  une fraction de seconde au lieu d'une analyse complète. Analyse complète quand même si un réglage de contenu change, si
  quelque chose a bougé, ou toutes les 12 h (réglable) ; bouton **Vérification complète** pour la forcer.
- **Simuler** (dry-run) : montre ce qui serait reçu / envoyé / supprimé sans rien modifier.
- **Historique** : onglet dédié (date, PC, résumé, détails des fichiers, erreurs) ; les suppressions restent 30 jours en corbeille.
- **`.voktoraignore`** : fichier à la racine d'un projet, un motif par ligne (`big/`, `*.tmp`), exclut des fichiers/dossiers de la synchro.
- **Beaucoup plus de configuration synchronisée** : fournisseurs IA et permissions de l'assistant (**sans les clés d'API**,
  qui restent propres à chaque PC), identité du compte GitHub et nom affiché, comptes GitLab/Forgejo (libellés ; **jamais les
  jetons**), thèmes personnalisés, profils de projets. Les nouvelles catégories se règlent dans l'onglet *Contenu*.

### 💬 Assistant IA avec outils
- Nouvelle fenêtre **Assistant IA** (Ctrl+Maj+A) : discussion avec le fournisseur actif (Ollama, OmniRoute, compatible OpenAI) qui
  peut **utiliser les outils de Voktora** : lister projets, lire/modifier les infos d'un projet, rechercher, état Git global,
  dépôts du compte, cloner, compte GitHub/forges, synchronisation (état/lancement), plugins (lister, installer, désinstaller,
  activer/désactiver), réglages (lire/modifier), commandes dans un projet.
- **Permissions** par outil : *désactivé* (l'outil n'est même pas présenté au modèle), *demander*, *automatique* (lecture
  seule uniquement). Toute action qui modifie demande **toujours** confirmation. Jetons/clés/coffre jamais renvoyés au modèle ;
  commandes sans shell, avec délai ; boucle limitée à 6 outils par message.

### 📊 Gérer 100+ projets
- **Vue d'ensemble** : état Git de tous les projets en un tableau (modifications, retard, à pousser, sans distant, sans Git,
  dossier manquant) avec filtres, **actions groupées** `fetch` et `pull --ff-only` (jamais de push ni de commit).
- **Recherche globale** dans les noms de projets, de fichiers et leur contenu (ripgrep si présent).
- **Projets orphelins** (dossiers non enregistrés) et **Tickets / demandes de fusion / CI** d'un projet (GitHub, GitLab, Forgejo,
  lecture seule).
- **Palette de commandes** (Ctrl+K) : toutes les actions des menus et l'ouverture d'un projet.

### 🔌 Plugins — API 4
- Nouveaux événements `on_sync_start`, `on_sync_done` ; nouvelles méthodes `fleet_states()`, `search_projects()`,
  `project_update()` (confirmé), `ai_ask()` (confirmé) ; permissions `fleet`, `projects.write`, `ai`.

### 🛠️ Fiabilité
- Sauvegarde automatique de `config.json` à chaque changement de version (`config.backup-<ancienne>.json`, 5 conservées).
- CI : workflow `packages-smoke` (syntaxe des scripts d'installation, version identique, `makepkg --printsrcinfo`).

## [1.0.9] — 2026-11-08

### 🔄 Synchronisation : journal maîtrisé, PC modestes, entrées au fil de l'eau, vraie reprise

- **Journal** : peut être **vidé** (bouton) ou **désactivé**, et a trois niveaux — *Essentiel*, *Par projet* (défaut),
  *Détaillé* (chaque fichier). Plus de gel de l'interface : le journal n'est plus réécrit en entier à chaque mise à
  jour (seules les nouvelles lignes sont ajoutées), les rafraîchissements sont regroupés (250-800 ms selon le PC) et les
  widgets des appareils sont mis à jour sur place au lieu d'être recréés.
- **PC peu puissants** : réglage **Charge sur ce PC** (Automatique / Économe / Normal / Rapide). En économe : une seule
  analyse à la fois, pauses proportionnelles pendant le calcul des empreintes, threads de synchro en priorité basse
  (`nice`), peu de rafraîchissements d'interface. « Automatique » choisit selon le nombre de cœurs.
- **Les entrées apparaissent pendant la synchro** : réglages et liste des projets d'abord, puis chaque projet est
  validé dès qu'il est terminé ; la liste des projets se rafraîchit toutes les 5 s au plus pendant la synchro (avant :
  seulement à la fin).
- **Reprise exacte après interruption** : un fichier de reprise (`resume-<pc>.json`) est mis à jour toutes les 10
  actions / 3 s. Au retour de l'autre PC, seul ce qui reste est refait, le pourcentage repart d'où il était, le choix de
  source déjà fait au premier échange n'est pas redemandé, et les fichiers partiels (`.part`) périmés sont nettoyés.
  La fenêtre indique « Interrompue à N % : elle reprendra exactement à cet endroit ».

### 🐙 GitHub

- **Renommer le compte** : le nom affiché peut être corrigé (carte GitHub ✏️, menu Forges, fenêtre Forges) ; il survit
  aux reconnexions ; vide = retour au nom de GitHub. Les comptes GitLab / Forgejo ont aussi un bouton **Renommer**.
- **Organisations manquantes** : la liste est maintenant paginée en entier et complétée par les adhésions actives
  (`/user/memberships/orgs`) ; la connexion demande le droit `read:org` (sans lui GitHub cache les organisations
  privées — reconnectez-vous une fois). Nouveau bouton **🏢 Recharger les organisations** (sélecteur de dépôts et
  fenêtre « Compte & organisations »), avec message d'aide si le droit manque.

### 🎨 Interface

- L'icône du mode **lignes** (liste) des projets était vide sur certaines polices : les icônes liste/grille sont
  désormais dessinées (indépendantes de la police).

## [1.0.8] — 2026-11-08

### 🔄 Synchronisation : fiabilité, transparence, rapidité

- **La synchro parle** : fini le « préparation » muet. Chaque étape est annoncée (connexion, réservation de l'autre PC,
  analyse de chaque projet **sur les deux PC avec le nombre de fichiers lus**, comparaison, transferts « Réception /
  Envoi / Fusion », terminé en N s) dans la barre d'état, la fenêtre et un nouvel onglet **Journal**
  (`sync/sync.log`, tourné à 1 Mo). Le pourcentage couvre toute la synchro (analyse 0-20 %, transferts 20-100 %).
- **Connexions instables** : analyses envoyées en flux (plus de délai d'attente pendant une longue analyse),
  nouvelles tentatives automatiques (0,5 / 1,5 / 4 s), verrou de l'autre PC renouvelé s'il expire, TCP keep-alive.
- **Ports automatiques** : port occupé → un port libre est pris tout seul (47821-47840) et l'autre PC le retrouve
  seul ; le port mémorisé est mis à jour.
- **Tester la connexion** : diagnostic pas à pas (réseau, port, authentification, **écart d'horloge**, occupation)
  avec la cause probable et la commande de pare-feu adaptée. Messages d'erreur explicites (plus de « 'clé' » brut) ;
  toute erreur interne est écrite avec sa trace dans le journal au lieu de bloquer en silence.
- **Certificats TLS (GitHub refusé sans `SSL_CERT_FILE`)** : le lot de certificats du système est désormais TOUJOURS
  chargé (avant, seulement si le magasin d'OpenSSL paraissait vide — faux sur Fedora avec le Python/OpenSSL embarqué),
  et exporté (`SSL_CERT_FILE`, `GIT_SSL_CAINFO`, `CURL_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`) pour git et les sous-processus ;
  une variable de l'utilisateur valide est respectée, une variable cassée est remplacée.
- **105 projets et plus** : analyses locales/distantes en parallèle, cache d'empreintes écrit au plus toutes les 15 s
  et élagué (avant : réécrit après chaque projet), 2ᵉ passe quasi instantanée (105 projets : 3,6 s puis 0,7 s).
- **Garde-fous** : une suppression massive n'est jamais propagée automatiquement ; un projet absent d'un PC n'est plus
  pris pour « supprimé » ; un projet reçu apparaît dans la liste même sans aucune métadonnée.
- Correction : course sur le cache d'empreintes (« dictionary changed size during iteration »).

### 🌐 Forges (GitHub, GitLab, Fedora…)

- Nouveau menu **🌐 Forges** : tout ce qui touche GitHub est regroupé (clonage, dépôts du compte, connexion,
  organisations) avec **GitLab**, la **forge de Fedora** (Forgejo, `forge.fedoraproject.org`), **Codeberg** et toute
  instance GitLab / Forgejo / Gitea ou GitHub Enterprise.
- **Distinction des forks** : badge « 🍴 fork de propriétaire/dépôt » dans l'onglet Git du projet (remote `upstream`
  instantané, confirmé par l'API en arrière-plan) et dans la liste des dépôts (filtre « Forks seulement »).
- Jetons dans le coffre quand il est déverrouillé ; jamais dans un remote, ni synchronisés, ni affichés.

### 🧩 API de plugins v3

Nouvelles permissions : `config.read`, `config.write`, `quick_actions`, `snapshots`, `diskusage`, `forges`, `sync`,
`plugins.manage`, `security`, `vault` — voir `doc/PLUGINS.md`. Tout changement de sécurité est confirmé par
l'utilisateur ; jetons et secrets ne sont jamais exposés ; les plugins de l'API 2 continuent de fonctionner.

---

## [1.0.7] — 2026-11-07

### 🔄 Synchronisation entre PC (priorité de cette version)

Intégrée à Voktora (menu **Outils → Synchronisation entre PC**) — voir `doc/SYNC.md`.

- **PC principal / secondaire** : le PC désigné « principal » a la priorité en cas de conflit.
- **Uniquement sur le même réseau** (LAN privé ou Tailscale, adresses stables) ; rien ne sort vers Internet.
- Synchronise les **réglages, actions rapides, catégories/statuts, métadonnées et fichiers des projets** (+ `.git`
  en bloc), les réglages des plugins ; jamais les jetons, le coffre, le compte GitHub ni les chemins locaux.
- **Fusion intelligente à la GitHub** : fichier A modifié d'un côté et B de l'autre → les deux changements sont
  appliqués ; même fichier modifié aux deux endroits sans chevauchement → fusion 3 voies des lignes ; sinon le
  principal gagne et la version perdante est gardée (`….sync-conflict-…`).
- **Premier échange différent → Voktora demande la source** (ce PC, l'autre, ou « le principal gagne »).
- **Pourcentage de progression des deux PC** dans la barre d'état et dans la fenêtre de synchronisation.
- **Coupure tolérée** : si un PC s'éteint ou quitte le réseau, tout s'arrête proprement et reprend tout seul.
- **Sécurité** : appairage par code à usage unique (10 min), requêtes signées HMAC anti-rejeu, contenu chiffré
  AES-256-GCM, chemins validés (pas de traversée ni de lien symbolique), suppressions mises en corbeille 30 jours.
- Beaucoup de réglages : catégories, projets concernés, motifs ignorés, taille max, git, suppressions, intervalle,
  politique du premier échange, port.
- **Nouveau format de paquet Arch / Omarchy** (`.pkg.tar.zst`, `pacman -U`) en plus du `.deb` et du `.rpm`
  → le portable peut tourner sous n'importe quelle distribution. `PKGBUILD` de référence fourni.

### Plugins communautaires (forks + sous-modules)

- Un auteur fork Voktora, ajoute son plugin en **sous-module git épinglé sur un commit** ; si le code du
  sous-module change, **une nouvelle PR est obligatoire**, même après acceptation.
- Verrou SHA-256 vérifié à chaque chargement, audit statique partagé (CI + application), imports/builtins gardés,
  liste de révocation, CI exécutant l'outil de la branche de base sur le code de la PR.

### Correctifs et nouveautés

- **Erreur SSL `CERTIFICATE_VERIFY_FAILED`** dans le marketplace de la version compilée corrigée (certificats
  système/certifi chargés au démarrage).
- **Vault** : fenêtre de déverrouillage (au démarrage si besoin, depuis le vault, ou à la demande).
- **Actions rapides** : celles ajoutées s'affichent, sont modifiables, avec sélecteur d'icônes.
- **Snapshots v2** : vraies sauvegardes complètes (avec `.git`), versions, vérification d'intégrité, restauration,
  comparaison intelligente, barre de progression.
- **Espace disque par projet** : détection des caches/compilations/dépendances, nettoyage par projet et
  « tout réinitialiser » avec double confirmation au-delà d'un seuil réglable.

---

## [1.0.6] — 2026-11-06

### Performances et fluidité

- **Démarrage 10× plus rapide avec 400 projets** (7,5 s → 0,6 s) : la vue grille n'est construite que si elle
  est affichée, et par tranches de 40 cartes au-delà de 80 projets (l'interface ne gèle plus).
- **Fin des « Voktora ne répond plus »** après une action : la santé des projets (barre latérale) est calculée
  en arrière-plan et sans lancer de processus git ; les hooks `on_open` ne bloquent plus l'ouverture d'un projet.
- IA : le contexte envoyé est **résumé** (≈ 700 caractères, sans badges ni code), seules 12 icônes présélectionnées
  sont proposées au modèle, et la longueur de réponse est bornée (descriptions ≈ 3× plus rapides).
- Compilation : Rust en LTO « fat » + `panic=abort` ; Nuitka avec `--lto=yes`, sans docstrings ni asserts,
  sans modules de test, en parallèle ; l'extension Rust est incluse dans les paquets quand elle est installée.

### Interface

- Dialogue « Personnaliser le projet » plus grand, aéré et redimensionnable (contenu défilant, boutons fixes).
- Menus : icônes détachées du texte (marges homogènes), cases à cocher alignées.
- **25 thèmes intégrés** : Dracula, Nord, Gruvbox (sombre/clair), Solarized (sombre/clair), Tokyo Night, One Dark,
  Monokai, Rosé Pine (+ Dawn), Catppuccin Macchiato/Frappé, Ayu Mirage, Everforest, Kanagawa, Synthwave,
  Midnight OLED, Sunset, Forest, Sakura, Paper, Arctic, High Contrast.

### Plugins (API 2) et marketplace

- Nouveau système : plugins en dossier (`plugin.json` + `main.py`), permissions déclarées et vérifiées
  (`ui`, `projects.read`, `files`, `network`, `shell`), activation/désactivation à chaud, réglages par plugin.
- **API étendue** : onglets de projet, menus et sous-menus, barre d'outils, panneaux latéraux, widgets de barre d'état,
  menu contextuel, feuilles de style (QSS), thèmes, `run_async`, `http_get`, `run`, 9 événements
  (`on_start/quit/open/close/create/delete/rename/refresh/theme_changed`) et événements entre plugins.
- **Onglet Marketplace** (Paramètres → Plugins) : recherche, permissions affichées, installation/mise à jour
  vérifiées par SHA-256, copie hors ligne de l'index.
- **Contributions par fork + Pull Request** : `marketplace/`, `tools/plugin_tool.py` (création, validation et analyse
  statique), CI `plugins.yml` (validation, régénération de l'index après fusion), modèle de PR, CODEOWNERS.
- 8 plugins fournis : UI Tweaks, Quick Notes, Focus Timer, TODO Scanner, Git Insights, Zen Mode, Neon Themes (déplacé en 1.1.1 vers la boutique de thèmes),
  Project Counter.
- Correction : les plugins n'étaient jamais chargés au démarrage ni accessibles depuis un menu.
- **Plugins communautaires par sous-module Git** : chaque auteur garde son dépôt/fork ; la PR l'ajoute en
  sous-module épinglé sur un commit (`marketplace/community/<id>`). Les plugins par défaut restent « officiels ».
  Modifier le dépôt de l'auteur ne change rien chez les utilisateurs : **nouvelle PR obligatoire**, même après
  acceptation. Commandes `submit`, `check-pr`, `pr-summary`, `drift`, workflow de dérive hebdomadaire.
- **Sécurité des plugins** : empreintes SHA-256 revérifiées à chaque démarrage (`.source.json`), analyse statique
  partagée CI/application (`audit.py`), builtins filtrés + garde d'imports par permission, liste de retraits
  (`revoked.json`), contrôles de PR exécutés avec l'outil de la branche principale, mise en évidence des nouvelles
  permissions lors d'une mise à jour, badges Officiel/Communauté avec dépôt et commit affichés.
- Correction : `CERTIFICATE_VERIFY_FAILED` dans la version compilée (installation depuis le marketplace, IA, GitHub) :
  les certificats système sont désormais chargés (`core/tls.py`), la vérification n'est jamais désactivée.

---

## [1.0.5] — 2026-11-05

### Ajouté

- **Extension Rust optionnelle (`voktora_native`)** : parcours, copie et CRC32 parallèles (copie de
  224 Mo / 12 000 fichiers : 0,18 s contre 4,9 s). Repli automatique en Python pur
  (`VOKTORA_NO_NATIVE=1` pour le forcer).
- **Multi-processus** (`core.parallel`) pour le chiffrement/déchiffrement de nombreux fichiers.
- **Icônes vectorielles (Material Design Icons)** à la place des emojis, avec sélecteur d'icônes.
- **Fournisseurs d'IA multiples** : Ollama, OmniRoute et API compatibles OpenAI (clés masquées dans les exports).
- **Ajout des dépôts de mon compte GitHub** : clonage automatique en parallèle.
- **Migration automatique** des anciens dossiers « Instances » / « Intents » vers le dossier des projets.
- **Barres de progression** supplémentaires (clonage git, opérations longues, activité en arrière-plan).
- **Compatibilité Linux élargie** : détection distribution / bureau / session, terminaux et gestionnaires de fichiers.

### Modifié

- Mentions légales : copyright « yolezz », `THIRD_PARTY_NOTICES.md`, boîte « À propos ».

---

## [1.0.4] — 2026-10-30

### Sécurité

- **Coffre (vault) : la clé maître était déductible du fichier de configuration.** Le « verifier »
  stocké dans `config.json` était dérivé du mot de passe avec la même fonction que la clé maître, et
  ses 32 premiers octets *étaient* cette clé : quiconque lisait `config.json` pouvait déchiffrer tout
  le coffre sans connaître le mot de passe. Le verifier est désormais un HMAC à sens unique. Les
  coffres existants sont migrés automatiquement au premier déverrouillage, avec **renouvellement de la
  clé** et rechiffrement des secrets. Pensez à supprimer d'anciennes copies de `config.json` (dossier
  de sauvegardes) et, par précaution, à régénérer les tokens qu'elles contenaient.
- **Chiffrement de projet : remplacement du XOR par AES-256-GCM.** L'ancien format `.menc` n'était
  qu'un XOR avec SHA-512(mot de passe) : sans sel, sans authentification, cassable, et un mauvais mot
  de passe produisait des fichiers corrompus tout en supprimant les originaux chiffrés. Le nouveau
  format `.vkenc` (clé scrypt, blocs authentifiés) détecte un mauvais mot de passe ou une altération
  avant toute écriture définitive. Les anciens fichiers `.menc` restent déchiffrables ; rechiffrez
  ensuite le projet pour passer au nouveau format.
- **Restauration de snapshot : écriture hors du dossier cible (« zip-slip »).** Les noms de membres
  ne sont plus acceptés tels quels (pas de `..`, chemin absolu ou lecteur Windows ; liens ignorés) et
  l'extraction se fait dans un dossier temporaire : l'ancien dossier n'est remplacé qu'une fois le
  snapshot entièrement extrait (avant, il était supprimé d'abord).
- **Désinstallation** : le script n'est plus écrit sous un nom fixe dans `/tmp` (pré-création par un
  autre utilisateur local possible) mais dans un fichier privé à nom aléatoire ; les chemins sont
  échappés ; la suppression est refusée pour une racine de disque, le dossier personnel, et — hors
  version compilée — le dossier des sources.
- `config.json` est créé directement en `0600` (plus de fenêtre où il était lisible avant le `chmod`).
- L'ouverture d'URL dans le navigateur n'accepte plus que `http` et `https`.
- Workflow CI : le titre de la PR n'est plus interpolé dans un script shell (injection de commande
  possible avec un titre piégé) ; il est validé (`v1.2.3`) avant usage. Droits du jeton réduits au
  nécessaire par job, dépendances installées depuis `uv.lock`, empreintes `SHA256SUMS` publiées.

### Ajouté

- **Paquet `.rpm`** (Fedora, RHEL/Rocky/Alma, openSUSE) construit et publié avec chaque release, à
  côté du `.deb` et du `.msi`. Le `.deb` et le `.rpm` empaquettent la **même compilation Nuitka**
  (compilée une seule fois en CI). Dépendances déclarées par bibliothèque (soname), donc valables
  d'une distribution RPM à l'autre.
- Export complet en trois phases séparées (`core/full_export.py`) : planification (lecture seule),
  configuration publique sans secrets, puis copie. Un projet illisible n'empêche plus l'export des
  autres ; les projets introuvables et les fichiers ignorés sont listés dans `export_info.txt`.
- Chiffrement de fichiers en flux (`core/file_crypto.py`) : mémoire constante, quelle que soit la
  taille des fichiers.

### Changé

- **Interface qui ne fige plus** : création, restauration et comparaison de snapshots, sauvegarde
  avant désinstallation et analyse d'une grosse archive ZIP à l'import s'exécutent en arrière-plan
  (progression, annulation). Le chiffrement et la sauvegarde avant chiffrement sont annulables
  proprement (plus de `terminate()` du thread).
- **Performances** : copie, extraction et export par blocs de 4 Mo avec un tampon réutilisé ; les
  formats déjà compressés (images, vidéos, archives, PDF…) sont stockés tels quels dans les ZIP au
  lieu d'être recompressés ; calcul de taille des dossiers plus rapide (`scandir`) ; comparaison de
  snapshots par CRC au lieu de charger les fichiers en mémoire ; déverrouillage du coffre deux fois
  plus rapide (une seule dérivation PBKDF2 au lieu de deux).
- Dépendances `.deb` complétées (`libxcb-cursor0`, `libegl1`, `libopengl0`, `libfontconfig1`),
  nécessaires au démarrage de Qt sur une installation minimale.
- La documentation et l'interface ne parlent plus d'« AES-256 » pour le coffre : Fernet utilise
  AES-128-CBC + HMAC-SHA256.

### Corrigé

- Le dialogue de chiffrement plantait (`NameError`) au premier clic sur « Chiffrer » / « Déchiffrer ».
- Métadonnées AppStream du paquet (balise `<n>` invalide → `<name>`).

---

## [1.0.3] — 2026-09-21

### Changé

- **Instances et intents fusionnés en « projets ».** Une seule liste, une seule racine de
  stockage (`Voktora/Projects` par défaut). La config passe en schéma 9 : la migration est
  automatique et une copie de l'ancien fichier est conservée dans `config.pre-v9.json`.
  Les projets existants gardent leur emplacement. Les anciens bundles `.mpack` et les
  `config.json` Meridian / Voktora restent importables.
- **Catégories gérées par l'utilisateur** (nom, emoji, couleur, ordre). Les catégories
  imposées (Web, Desktop…) disparaissent ; celles déjà attribuées à un projet sont conservées.
  Renommer une catégorie met à jour ses projets ; la supprimer les laisse « sans catégorie ».
- **Regroupement de la liste et de la grille** par catégorie, organisation GitHub, langage ou
  statut (choix mémorisé). Glisser des projets sur une catégorie les y classe ; clic droit →
  « Catégorie » fonctionne aussi en vue grille. La recherche couvre désormais catégorie et
  organisation GitHub.
- **Export global** : n'exclut plus `.git/objects` (un dépôt restauré depuis l'archive avait
  perdu son historique) ; ne contient plus le compte GitHub ni les tokens de projet.
- Le tri « Type » est remplacé par « Catégorie » et « Ordre manuel ».

### Ajouté

- **Import sans blocage.** Le dézippage, la copie, le déplacement, l'export et la suppression
  s'exécutent dans un thread avec une fenêtre de progression (octets, fichier courant) et un
  bouton Annuler. L'annulation ne laisse aucun demi-projet et n'altère jamais la source.
- **Import de dossiers non compressés** : *déplacer* (défaut), *copier* ou *ajouter sur place*.
  Le glisser-déposer d'un dossier ou d'un `.zip` sur la fenêtre ouvre l'import (Ctrl+I aussi).
  Le dépôt GitHub d'un projet importé est repris depuis son `.git`.
- **Clone GitHub** : choix parmi vos dépôts et ceux de vos organisations (filtre par
  propriétaire, recherche), ou par URL ; branche et catégorie au choix, journal en direct.
- **Compte & organisations** (menu GitHub) : propriétaires de vos dépôts et de vos projets,
  ouverture sur GitHub, classement automatique des projets par organisation.
- Création de projet : catégorie, `git init` et dépôt GitHub en une étape.
- Suppression : choix entre « Retirer de Voktora » (fichiers conservés) et « Supprimer le dossier ».
- Menu contextuel, glisser-déposer multi-sélection, badges de catégorie sur les cartes.
- `doc/PROJECTS.md` et `doc/SECURITY.md`.

### Corrigé

- Fige de l'interface pendant l'import d'un ZIP (extraction dans le thread graphique).
- Un ZIP sans dossier racine unique était extrait « en vrac » à la racine des projets.
- Une suppression partielle « oubliait » le projet alors que des fichiers restaient sur disque.
- La migration de fichiers de config hérités pouvait boucler, et absorbait puis supprimait
  un `settings.json` sans rapport avec Voktora.
- L'auto-sauvegarde des notes visait un widget caché : elle n'enregistrait rien.
- Mises à jour de widgets depuis un thread non graphique (ping des projets).
- `git status`, `git log`, `git pull`, push automatique et clone ne bloquent plus l'interface.
- Détection du langage beaucoup plus rapide (dossiers de dépendances ignorés, plafond de fichiers).
- README : structure et liens de documentation alignés sur le dépôt.

### Sécurité

- **Le token GitHub n'est plus jamais écrit dans l'URL d'un remote** (donc plus dans
  `.git/config`, ni dans les exports et snapshots), ni passé en argument de ligne de commande :
  il est transmis à git par variables d'environnement, limité à `https://github.com/`. Les
  anciens remotes contenant un token sont nettoyés au prochain push.
- Exports, bundles de migration et snapshots retirent les identifiants de `.git/config`.
- Extraction ZIP : chemins `..`/absolus/lecteurs refusés, liens symboliques ignorés, espace
  disque vérifié, tailles annoncées contrôlées.
- **Injection de commande corrigée** : un nom de projet venant d'une archive (`'; cmd; '`,
  `$(cmd)`…) pouvait s'exécuter via « Ouvrir un terminal » / « Ouvrir avec ». Plus aucun chemin
  n'est interpolé dans un shell.
- URL de clone et noms de branche validés (`ext::`, `--option`, `..` refusés) ; `--` protège
  les opérandes git.
- `config.json` est créé en `0600` sous Linux.
- Déplacement refusé pour une racine de disque ou le dossier personnel.

### Tests

- 330+ tests (contre 117) : archive, import, catégories, regroupement, migration, API GitHub
  simulée, authentification git, sécurité, dialogues et fenêtre principale (Qt hors écran).
  Un test vérifie que la version est identique dans `pyproject.toml`, `version.txt`,
  `constants.py` et ce fichier.

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
