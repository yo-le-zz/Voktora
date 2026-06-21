# Changelog — Voktora

Toutes les modifications notables de ce projet sont documentées ici.  
Format : [Semantic Versioning](https://semver.org/) — `MAJEUR.MINEUR.CORRECTIF`

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
