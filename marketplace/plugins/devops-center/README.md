# DevOps Center

Git, GitHub, Docker, serveurs SSH, déploiements et pipelines dans un seul onglet (**DevOps** d'un projet, ou **Outils → DevOps Center…**, Ctrl+Alt+D).

| Onglet | Fonctions |
|---|---|
| Environnements | versions de Python, Node, cargo, Go, Git, Docker, SSH ; fichiers de projet, venv, noms des `.env` (valeurs jamais lues) |
| Git | statut, branches, derniers commits, diff, `fetch`, `pull --ff-only`, changement de branche, tickets et pull requests GitHub |
| Docker | conteneurs, images, démarrer/arrêter/redémarrer, journaux, `compose up/down` |
| Serveurs | profils SSH (clé ou agent), test, commande à distance, confirmation en production |
| Déploiements | cible locale ou SSH, sauvegarde avant, vérification, **restauration automatique** si échec, confirmation en production |
| Pipelines | étapes (tentatives, délai, condition, `continue_on_error`), annulation, journaux en direct, modèles Python/Node/Rust |
| Historique | pipelines, déploiements, commandes SSH (500 derniers, journaux complets) |

## Sécurité
- **Aucun `push`** : le plugin n'a ni méthode ni commande de push ; `pull` est en fast-forward seulement et refusé si des modifications locales existent.
- Jamais de shell : les commandes sont découpées (`shlex`) et lancées en liste ; hôtes/utilisateurs/noms Docker validés (pas d'injection d'option).
- Aucun mot de passe stocké. SSH utilise vos clés / agent (`BatchMode`). Le jeton GitHub optionnel vit dans le coffre Voktora (`github_token`, via `vault_secret_set`) ; sans lui, l'API publique ou la CLI `gh` est utilisée.
- Production : confirmation explicite pour déployer, exécuter un pipeline ou une commande SSH.

## Pipelines (JSON)
```json
{"name": "ci", "environment": "dev", "notify": true, "env": {}, "steps": [
  {"name": "tests", "command": "python -m pytest -q", "retries": 1, "retry_delay": 2, "timeout": 600},
  {"name": "notifier", "command": "echo fini", "condition": "always"}]}
```
Conditions : `success` (défaut), `failure`, `always`, `branch:<nom>`, `env:<NOM>=<valeur>`, `exists:<chemin>`.

## Cibles de déploiement (JSON)
`name`, `source` (dossier du projet), `dest`, `ssh` (nom du profil, vide = local), `environment`, `pre`, `post`, `health`, `exclude`.
Limites : le déploiement SSH utilise `scp` + `tar` distants (Linux/macOS) ; la restauration distante dépend du serveur ; l'éditeur de pipelines/cibles est en JSON validé (pas d'éditeur visuel d'étapes).

## Permissions
`shell` (git/docker/ssh/commandes), `network` (API GitHub), `vault` (jeton), `projects.read`, `ui`.
Structure : `core/` (git, docker, ssh, github, pipeline, deploy, environments, proc) · `storage/` · `ui/` · tests : `tests/test_plugin_devops_center.py` (racine).
