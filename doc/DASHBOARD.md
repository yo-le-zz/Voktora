# Voktora — Dashboard

Le dashboard analyse la santé de tous vos projets et suit vos statistiques d'usage.

---

## Accès

**Onglet Outils → Dashboard** dans le panneau projet.

---

## Analyse de santé

Chaque projet reçoit un **score de santé** (0–100) et une icône :

| Score | Icône | Signification |
|-------|-------|---------------|
| 80–100 | 🟢 | Projet en bonne santé |
| 50–79  | 🟡 | Avertissements mineurs |
| 0–49   | 🔴 | Problèmes critiques |

### Vérifications effectuées

| Problème détecté | Type | Impact score |
|-----------------|------|-------------|
| Dossier introuvable | ❌ critique | -20 pts |
| Pas de dépôt Git | ⚠️ avertissement | -5 pts |
| `.gitignore` manquant | ⚠️ avertissement | -5 pts |
| Commits en retard sur remote | ⚠️ avertissement | -5 pts |
| Push locaux non envoyés (> 5) | ⚠️ avertissement | -5 pts |
| Branches non mergées | ⚠️ avertissement | -5 pts |
| Inactif > 90 jours | ℹ️ info | 0 pts |

---

## Statistiques d'usage

- **Total des ouvertures** : toutes sessions confondues
- **Projets les plus utilisés** : top 5 par nombre d'ouvertures
- **Projets cassés** : score < 50
- **Projets sains** : score ≥ 80

Les données sont enregistrées localement dans `~/.voktora/usage.json`.

---

## Cliquer sur un projet dans le dashboard

Affiche le détail :
- Liste des problèmes et avertissements
- Nombre de commits
- Dernière ouverture
- Situation ahead/behind par rapport à la remote
