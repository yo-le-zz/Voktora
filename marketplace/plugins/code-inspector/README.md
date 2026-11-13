# Code Inspector

Comprendre un projet en quelques secondes : architecture, dépendances, appels, ponts Python × Rust, qualité.
Plugin Voktora (API 5, Python). Menu **Outils → Code Inspector…** (Ctrl+Alt+I) ou onglet **Inspecteur** d'un projet.

## Ce que le plugin fait
- **Langages** : Python, Rust (y compris PyO3), JavaScript / TypeScript, C / C++ ; fichiers de configuration
  (`pyproject.toml`, `package.json`, `Cargo.toml`, `requirements*.txt`, CMake, `go.mod`, Dockerfile).
- **Vues** : architecture globale, arborescence détaillée, dépendances entre fichiers, relations entre classes,
  graphe des appels (double-clic sur un nœud pour le centrer), chaînes d'exécution depuis les points d'entrée, ponts Python × Rust.
- **Fiche d'une fonction** : fichier, signature, paramètres, retour, complexité, appelants, appelés, dépendances du fichier ;
  les liens sont cliquables.
- **Qualité** : erreurs probables, mauvaises pratiques, complexité, doublons (≥ 12 lignes), imports inutilisés,
  fonctions jamais appelées (candidates), dépendances inutilisées / obsolètes / avec avis de sécurité connu (liste locale `resources/advisories.json`).
- **Exports** : JSON (graphe complet), Markdown (avec diagrammes Mermaid), SVG, HTML autonome interactif (sans CDN),
  PDF, et exports spécifiques Python, Rust, Python × Rust.
- **Incrémental** : l'analyse par fichier est mise en cache (taille/date puis empreinte SHA-1) ; seul ce qui a changé est réanalysé.

## Fiabilité : certain / probable / inconnu
Chaque relation porte un niveau, affiché en trait plein / tirets / pointillés et filtrable :

| Niveau | Signification |
|---|---|
| **certain** | lue directement dans le code : import résolu, appel d'un nom importé, `self.méthode()` trouvée dans la classe ou ses bases |
| **probable** | déduite : type d'une variable (`x = Classe()`), méthode au nom unique (≤ 3 candidats), fonction passée en rappel |
| **inconnu** | indécidable statiquement : `getattr`, imports dynamiques, paramètres appelés, nom introuvable, trop de candidats |

Le plugin **n'invente jamais** une relation : ce qu'il ne peut pas établir est marqué « inconnu ».
Limites connues : pas d'inférence de types complète (ni Python ni Rust), macros Rust non développées, génériques simplifiés,
code généré ou chargé à l'exécution invisible.

## Python × Rust
Détecte les modules natifs (`#[pymodule]`, `[lib] name`, `module-name` maturin), les appels Python → `#[pyfunction]` / `#[pyclass]` /
méthodes, `ctypes`/`cffi` → `extern "C"` + `#[no_mangle]`, `subprocess` → binaires Cargo, et les retours Rust → Python
(`py.import("m")`, `.getattr("f")`, `.call_method`) ; les rappels dont la cible n'est pas littérale sont « inconnus ».

## Options
Dossiers à ignorer (en plus de `.gitignore` et `.voktoraignore`), analyse automatique à l'ouverture d'un projet.

## Permissions et confidentialité
`projects.read` (projet courant), `ui`. Le plugin lit les fichiers du projet avec ses propres accès Python (aucune donnée n'est envoyée :
**aucun accès réseau**) et ne conserve son cache que dans son dossier de données.

## Structure
`core/` (modèle, graphe, liaison, moteur) · `analyzers/` (un par langage) · `services/` (vues, qualité, détection, ponts) ·
`storage/` (cache) · `exporters/` · `ui/` · `resources/` · `tests/` (voir aussi `tests/test_plugin_code_inspector.py` à la racine du dépôt).

## Ajouter un langage
Créer `analyzers/xxx_an.py` avec une classe `Analyzer` (`register`), retourner un `FileResult`, ajouter un résolveur dans
`core/resolvers/` et incrémenter `ANALYZER_VERSION` dans `analyzers/base.py` pour invalider les caches.
