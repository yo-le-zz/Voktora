# Voktora — Snapshots

Un snapshot capture l'état complet d'un projet (fichiers + structure Git) dans un fichier `.snap` (ZIP structuré).

---

## Onglet Snapshots dans le panneau projet

### Créer un snapshot
1. Cliquer **Créer**
2. Donner un label (optionnel)
3. Le snapshot est créé dans `~/.voktora/snapshots/<nom_projet>/`

### Snapshot rapide
Bouton **Créer snapshot rapide** — label automatique = horodatage, aucune saisie.

### Restaurer
1. Sélectionner un snapshot dans la liste
2. Cliquer **Restaurer**
3. Choisir un dossier de destination
4. Si le dossier existe déjà, confirmer l'écrasement

### Comparer deux snapshots
1. Cliquer **Comparer**
2. Sélectionner Snapshot A et Snapshot B
3. Voktora affiche les différences : `ADDED`, `MODIFIED`, `REMOVED`

---

## Format .snap

Un `.snap` est un ZIP avec :
- `manifest.json` : métadonnées (nom projet, timestamp, label, version)
- `files/` : arborescence complète du projet

Les dossiers lourds `.git/objects` et `.git/lfs` sont exclus pour réduire la taille.

---

## Stockage

```
~/.voktora/snapshots/
└── mon_projet/
    ├── mon_projet_20240115_143022.snap   (12.4 MB)
    └── mon_projet_20240116_091500.snap   (13.1 MB)
```

---

## API Python (pour plugins)

```python
import snapshots
from pathlib import Path

project = Path("/chemin/vers/mon_projet")

# Créer
snap_path = snapshots.create(project, label="avant refacto")

# Lister
for s in snapshots.list_snaps(project):
    print(s.label, s.timestamp, f"{s.size_mb} MB")

# Restaurer
snapshots.restore(snap_path, Path("/tmp/restore_test"), overwrite=True)

# Comparer
snaps = snapshots.list_snaps(project)
diff  = snapshots.diff_snaps(snaps[0].path, snaps[1].path)
for fichier, statut in diff.items():
    print(f"{statut:10}  {fichier}")

# Supprimer
snapshots.delete_snap(snap_path)
```
