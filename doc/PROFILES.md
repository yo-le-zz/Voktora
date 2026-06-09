# Voktora — Profils d'exécution

Un profil d'exécution définit comment lancer un projet : commande, env vars, dossier de travail, scripts pre/post run.

---

## Gestion : Onglet Actions → Profils d'exécution

Chaque projet peut avoir **plusieurs profils**. Un seul est marqué comme **défaut** (★).

---

## Structure d'un profil

```json
{
  "name": "Dev server",
  "run_cmd": "python src/main.py",
  "work_dir": "",
  "env": {
    "DEBUG": "1",
    "PORT": "8080",
    "DATABASE_URL": "sqlite:///dev.db"
  },
  "pre_run": [
    "uv pip install -e .",
    "python scripts/seed_db.py"
  ],
  "post_run": [
    "python scripts/cleanup.py"
  ],
  "default": true
}
```

---

## Variables disponibles dans la commande

| Variable | Description |
|----------|-------------|
| `VOKTORA_PROJECT_PATH` | Chemin absolu du projet |
| `VOKTORA_PROFILE` | Nom du profil lancé |

---

## Exemples par langage

### Python (uv)
```
run_cmd  : uv run python src/main.py
work_dir : (vide = racine du projet)
env      : DEBUG=1
pre_run  : uv sync
```

### Node.js
```
run_cmd  : npm run dev
work_dir : frontend/
env      : NODE_ENV=development
pre_run  : npm install
```

### Gradle (Minecraft Mod)
```
run_cmd  : ./gradlew runClient
work_dir : (vide)
env      : JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
```

### Docker Compose
```
run_cmd  : docker compose up
work_dir : (vide)
env      : COMPOSE_PROJECT_NAME=monprojet
pre_run  : docker compose pull
post_run : docker compose down
```

---

## Lancement rapide

- **Onglet Actions → ▶ Lancer profil par défaut** : lance le profil marqué ★
- **Onglet Actions → Gérer les profils → Lancer** : choisir un profil spécifique

Le journal de sortie apparaît dans le panneau **Journal** (colonne droite).
