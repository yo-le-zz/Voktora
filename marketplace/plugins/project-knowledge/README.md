# Project Knowledge

La mémoire d'un projet : **Outils → Project Knowledge…** (Ctrl+Alt+K) ou onglet **Connaissance**.

- **Indexation incrémentale** : taille/date puis empreinte SHA-1 ; seuls les fichiers modifiés sont relus. Respecte `.gitignore` et `.voktoraignore`, ignore `node_modules`, `.venv`, `target`…
- **Rôles** détectés par fichier : entrée, test, documentation, build, configuration, interface, modèle, service, script, utilitaire, code.
- **Symboles** : classes, fonctions, méthodes (signatures et docstrings pour Python ; Rust, JavaScript/TypeScript, C/C++, Go, titres Markdown par expressions régulières).
- **Recherche plein texte BM25** écrite pour ce plugin (mots découpés en camelCase/snake_case, accents ignorés, préfixes), avec extrait et ligne ; double-clic = ouvrir.
- **Recherche par similarité** : cosinus TF-IDF. **Ce n'est pas de la recherche sémantique à base d'embeddings** (aucun modèle n'est embarqué ni téléchargé) : elle retrouve des textes de vocabulaire proche, pas des synonymes.
- **Wiki par projet** : pages Markdown, liens `[[Page]]` / `[[Page|texte]]`, rétroliens, détection des **liens cassés** et des pages orphelines. Pages automatiques (Vue d'ensemble, Architecture, API interne, Dépendances, Historique des changements) régénérées à chaque actualisation, **sans jamais écraser une page manuelle** du même nom.
- **Pages périmées** : une page qui cite des fichiers entre accents graves est signalée (⚠) quand ces fichiers changent ; « Enregistrer » la remet à jour.
- **Diagramme de dépendances** (SVG) : imports résolus vers un seul fichier du projet (un import ambigu n'est pas relié) ; regroupement par dossier au-delà de 60 nœuds.
- **Documentation d'API interne** générée depuis les symboles publics.
- **Historique** des changements (fichiers et symboles ajoutés/supprimés).
- **Exports** : Markdown, HTML (une page), PDF, **site statique** (pages + recherche côté client, sans CDN).

Données : dossier du plugin (index compact et wiki en JSON), jamais dans le projet. Permissions : `projects.read`, `ui` — le plugin lit les fichiers du projet avec ses propres accès et n'utilise pas le réseau.
Tests : `tests/test_plugin_project_knowledge.py` (racine du dépôt).
