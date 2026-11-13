# Workflow Forge

Éditeur visuel d'automatisations pour vos projets : **Outils → Workflow Forge…** (Ctrl+Alt+W) ou onglet **Workflows**.

## Éditeur
Palette de blocs (recherche), double-clic pour ajouter, glisser du rond de sortie vers un bloc pour relier, Suppr pour effacer, molette pour zoomer. La scène reste fluide avec 250 blocs et 250 liens (test automatisé : chargement < 4 s, déplacement d'un bloc relié < 50 ms). Formulaire de paramètres généré par bloc ; options communes : tentatives, délai entre tentatives, délai maximal, « continuer si échec ».

## Blocs (30)
- **Flux** : démarrage, fin, échec volontaire, condition (true/false), pour chaque, tant que, parallèle, joindre, attendre.
- **Données** : variable, transformation, journal, notification, lecture JSON.
- **Système** : commande (sans shell), lire/écrire un fichier, fichier existe ?, lister, variable d'environnement.
- **Scripts** : Python (processus isolé `-I`), JavaScript (Node requis), Rust (`rustc` requis).
- **Réseau** : requête HTTP (toutes méthodes, port « error » sur code ≥ 400).
- **Projet** : Git statut / commit courant / pull fast-forward (**aucun push**), recherche dans le projet, commande du projet.

Les chemins de fichiers sont confinés au projet. Les ports « error » permettent de traiter un échec sans arrêter le workflow.

## Expressions et modèles
`{{ … }}` dans les paramètres, et expressions des conditions/boucles/variables. Évaluateur **sans `eval`/`exec`** : le texte est analysé syntaxiquement puis interprété nœud par nœud ; seuls opérateurs, accès `a.b` / `a[0]`, littéraux et une liste blanche de fonctions (`len`, `upper`, `join`, `get`, `regex_match`, …) sont permis ; pas de dunder, pas de lambda, pas de compréhension, puissances et répétitions bornées. Variables : `vars`, `out.<bloc>.<champ>`, `trigger`, `item`, `index`.

## Exécution
Fils d'exécution ; annulation ; **parallèle** : toutes les branches du bloc « Parallèle » démarrent ensemble et se rejoignent sur un seul bloc « Joindre » (une erreur annule les autres) ; boucles bornées (limite d'itérations) ; garde-fou de 20 000 étapes. Le délai maximal d'un bloc interrompt l'attente mais ne peut pas tuer un fil Python interne (les commandes, elles, sont tuées). **Test à blanc** : les blocs à effet de bord (commandes, écritures, HTTP, notifications, scripts, pull) ne sont pas exécutés ; conditions, variables et boucles le sont réellement. Journaux par exécution et historique (200).

## Déclencheurs
manuel, démarrage de Voktora, ouverture du projet, modification de fichiers (sondage), nouveau commit (HEAD Git), GitHub (sondage via fonction injectée — non branché dans l'interface), **HTTP entrant** (127.0.0.1 uniquement, POST, en-tête `X-Voktora-Token` d'au moins 16 caractères **obligatoire**, comparaison à temps constant, corps limité à 1 Mo), intervalle, cron à 5 champs. L'horloge est injectable (tests). Les jetons ne sont jamais exportés.

## Import / export
JSON versionné ; l'import valide le workflow (blocs, ports, expressions, cycles) avant de l'accepter.

## Limites honnêtes
Pas d'éditeur de déclencheurs graphique (JSON). Pas de reprise après plantage. Le sondage GitHub n'est pas câblé dans l'interface (la brique est testée). Un jeton HTTP est conservé en clair dans le dossier de données du plugin (il n'est pas dans les exports). Les scripts isolés ne sont pas un bac à sable de sécurité : n'exécutez que vos propres workflows.

Permissions : `shell`, `network`, `projects.read`, `ui`. Tests : `tests/test_plugin_workflow_forge.py` (racine du dépôt).
