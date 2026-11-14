# Moniteur développeur global (Voktora 1.1.3)

Une **seconde fenêtre**, dans un **processus détaché**, qui affiche en direct tout ce que fait Voktora : plantages, erreurs, journaux, clics, blocages.
Elle ne bloque pas la fenêtre principale et **reste ouverte si Voktora plante** (c'est son intérêt : elle affiche alors « plantage probable »
et la trace native).

## Activer

| Façon | Effet |
|---|---|
| `voktora --dev` / `--dev=verbose` | observation dès le démarrage + ouverture de la fenêtre |
| `VOKTORA_DEV=trace voktora` | idem (`1` = `normal`) |
| Préférences › *Moniteur développeur global…* | choix du mode, ouverture, option « ouvrir automatiquement au démarrage » |

## Modes (modifiables en direct dans la fenêtre)

| Mode | Contenu |
|---|---|
| `crash` | exceptions non gérées (fil principal, threads), plantage natif (`faulthandler`), arrêt anormal |
| `normal` | + erreurs et avertissements, démarrage/arrêt, fenêtres et dialogues ouverts, erreurs de plugins, erreurs Qt |
| `verbose` | + clics, menus, onglets, raccourcis, hooks de plugins, écritures de configuration, blocages de l'interface (pile du fil principal) |
| `trace` | + messages Qt, journaux DEBUG, changements de focus, durée de chaque hook |

## Fonctionnement

1. Voktora (`devmon/emitter.py`) écrit une ligne JSON par événement dans `<données>/devmon/session-AAAAMMJJ-HHMMSS-<pid>.jsonl`, vidée à chaque ligne : un plantage ne perd rien.
2. Le viewer (`devmon/viewer.py`) est lancé par `devmon/launcher.py` avec `start_new_session=True` (Windows : `DETACHED_PROCESS`). Ce n'est volontairement
   **pas** `multiprocessing` : un processus enfant meurt avec son parent. En version compilée, c'est le même exécutable relancé avec `VOKTORA_DEVMON_VIEWER=<fichier>`.
3. Le viewer relit le fichier (`Tail`), filtre (gravité, catégorie, recherche), affiche le détail (traceback), exporte, et écrit le mode voulu dans
   `session-….control.json` que l'application relit chaque seconde.
4. L'état vient d'un battement de cœur (2 s) + de l'existence du processus : *en marche*, *ne répond plus*, *arrêté*, *plantage probable*.

## Confidentialité

- Jamais le texte tapé (seulement les raccourcis `Ctrl/Alt/Méta+…`), jamais le contenu des champs ni des listes.
- Jetons GitHub/OpenAI/Slack/AWS, `password=…`, `token=…`, identifiants dans les URL : masqués (au mieux — ne mettez pas de secrets dans vos messages).
- Les fenêtres dont le titre évoque coffre/mot de passe/jeton/secret ne sont pas observées.
- Tout reste local ; 10 sessions conservées, 25 Mo maximum par session (`devmon/core.py`).

## Limites

- Un plantage avant l'activation (très tôt au démarrage) n'est pas capté.
- Un blocage (`freeze`) est détecté par une minuterie du fil principal : seuil de 2 s.
- Sous Windows, le lancement détaché et le test de présence du processus n'ont pas été testés.
