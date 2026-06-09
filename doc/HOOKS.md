# Voktora — Hooks

Les hooks déclenchent automatiquement des scripts shell ou Python lors d'événements Voktora.

---

## Événements disponibles

| Hook | Quand |
|------|-------|
| `on_create` | Nouvelle instance ou intent créée |
| `on_open` | Projet ouvert dans le panneau détail |
| `on_delete` | Projet supprimé |
| `on_clone` | Dépôt Git cloné |
| `on_git_push` | Push Git effectué |
| `on_git_commit` | Commit effectué |
| `on_git_pull` | Pull effectué |

---

## Gestion : Onglet Actions → Hooks

1. Choisir l'événement dans le menu déroulant
2. Sélectionner le type : **shell** ou **python**
3. Entrer la commande ou le chemin vers un script `.py`
4. Ajouter un label descriptif
5. Cliquer **Ajouter**

---

## Variables d'environnement disponibles

| Variable | Description |
|----------|-------------|
| `MERIDIAN_PROJECT_PATH` | Chemin absolu du projet |
| `VOKTORA_PROJECT_PATH` | Identique (alias) |

```bash
# Exemple : hook on_open — ouvrir un fichier de notes
on_open : shell : code "$VOKTORA_PROJECT_PATH/NOTES.md"
```

---

## Exemples

### Shell — git pull automatique à l'ouverture
```bash
# Hook : on_open, type : shell
cd "$VOKTORA_PROJECT_PATH" && git pull --ff-only
```

### Shell — notification bureau après push
```bash
# Hook : on_git_push, type : shell
notify-send "Voktora" "Push effectué : $VOKTORA_PROJECT_PATH"
```

### Python — init README si absent
```python
# Hook : on_create, type : python (chemin : ~/.voktora/scripts/init_readme.py)
import os
from pathlib import Path

path = Path(os.environ.get("VOKTORA_PROJECT_PATH", "."))
readme = path / "README.md"
if not readme.exists():
    readme.write_text(f"# {path.name}\n\nCréé avec Voktora.\n")
    print(f"README.md créé dans {path}")
```

### Python — envoyer une notif Discord
```python
# Hook : on_git_push
import urllib.request, json, os

webhook = "https://discord.com/api/webhooks/VOTRE_WEBHOOK"
path    = os.environ.get("VOKTORA_PROJECT_PATH", "?")
data    = json.dumps({"content": f"✅ Push Voktora : `{path}`"}).encode()
req     = urllib.request.Request(webhook, data=data,
          headers={"Content-Type": "application/json"}, method="POST")
urllib.request.urlopen(req, timeout=5)
```

---

## Stockage

Les hooks sont enregistrés dans `~/.voktora/hooks.json` :

```json
{
  "on_create": [
    {"type": "shell", "cmd": "echo $VOKTORA_PROJECT_PATH", "label": "Log", "enabled": true}
  ],
  "on_open": [],
  "on_git_push": []
}
```
