# Voktora — Système de Plugins

> Les plugins permettent d'étendre Voktora avec des commandes, boutons et hooks personnalisés.

---

## Emplacement

```
~/.voktora/plugins/
├── _example_plugin.py   ← exemple (généré automatiquement, préfixé _ = inactif)
├── mon_plugin.py        ← plugin actif
└── docker_plugin.py     ← autre plugin actif
```

Un fichier préfixé par `_` est ignoré. Tout autre `.py` est chargé au démarrage.

---

## Structure minimale

```python
# mon_plugin.py

PLUGIN_NAME    = "MonPlugin"
PLUGIN_VERSION = "1.0.0"
PLUGIN_AUTHOR  = "votre_nom"

def on_load(api):
    """Appelé une fois au chargement. Enregistrez vos commandes, boutons et hooks ici."""
    api.register_command("ma_commande", cmd_run, desc="Description courte")
    api.register_button("🔧 Mon bouton", btn_click, tooltip="Tooltip affiché au survol")
    api.register_hook("on_open", hook_on_open)
    api.register_hook("on_create", hook_on_create)
```

---

## PluginContext

Tous les handlers reçoivent un objet `PluginContext` :

```python
def cmd_run(ctx):
    # ctx.project_path : Path | None — chemin du projet actif
    # ctx.log(msg)     : str        — écrire dans le journal Voktora
    # ctx.args         : dict       — arguments supplémentaires (si fournis)
    
    ctx.log(f"Projet actif : {ctx.project_path}")
    
    if ctx.project_path:
        import subprocess
        subprocess.Popen(["code", str(ctx.project_path)])
        ctx.log("VS Code lancé !")
```

---

## API complète

### `api.register_command(name, handler, desc="")`

Enregistre une commande accessible depuis la palette de commandes (`Ctrl+P`).

```python
api.register_command("docker_up", lambda ctx: run_docker(ctx), desc="docker compose up")
```

### `api.register_button(label, handler, tooltip="")`

Ajoute un bouton dans l'onglet **Outils → Plugins** du panneau projet (max 5 affichés).

```python
api.register_button("🐳 Docker up", btn_docker_up, tooltip="Lance docker compose up -d")
```

### `api.register_hook(hook_name, handler)`

Déclenché automatiquement par les événements Voktora.

| Hook | Déclencheur |
|------|-------------|
| `on_create` | Nouvelle instance créée |
| `on_open` | Projet ouvert dans le panneau |
| `on_delete` | Projet supprimé |
| `on_clone` | Dépôt Git cloné |
| `on_git_push` | Push Git effectué |
| `on_git_commit` | Commit effectué |
| `on_git_pull` | Pull effectué |

---

## Exemple complet : plugin Docker

```python
# docker_plugin.py
import subprocess
from pathlib import Path

PLUGIN_NAME    = "Docker"
PLUGIN_VERSION = "1.0.0"
PLUGIN_AUTHOR  = "yolezz"

def on_load(api):
    api.register_button("🐳 Up",    btn_up,    tooltip="docker compose up -d")
    api.register_button("🛑 Down",  btn_down,  tooltip="docker compose down")
    api.register_button("📋 Logs",  btn_logs,  tooltip="docker compose logs -f")
    api.register_hook("on_open",   hook_check_compose)

def _compose(ctx, *args):
    if not ctx.project_path:
        ctx.log("Aucun projet actif.")
        return
    compose_file = ctx.project_path / "docker-compose.yml"
    if not compose_file.exists():
        ctx.log("Pas de docker-compose.yml dans ce projet.")
        return
    try:
        r = subprocess.run(
            ["docker", "compose", *args],
            cwd=str(ctx.project_path),
            capture_output=True, text=True, timeout=30,
        )
        ctx.log((r.stdout + r.stderr).strip() or "OK")
    except FileNotFoundError:
        ctx.log("Docker non trouvé. Installez Docker Desktop.")
    except Exception as e:
        ctx.log(f"Erreur : {e}")

def btn_up(ctx):    _compose(ctx, "up", "-d")
def btn_down(ctx):  _compose(ctx, "down")
def btn_logs(ctx):  _compose(ctx, "logs", "--tail=50")

def hook_check_compose(ctx):
    if ctx.project_path and (ctx.project_path / "docker-compose.yml").exists():
        ctx.log("[Docker] docker-compose.yml détecté dans ce projet.")
```

---

## Rechargement à chaud

Dans Voktora : **Onglet Outils → Plugins → Recharger**  
(pas besoin de redémarrer l'application)

---

## Accès aux APIs Voktora depuis un plugin

```python
import core   # config, vault, sessions GitHub
import vault  # secrets chiffrés
import git    # git automation

def btn_auto_commit(ctx):
    if not ctx.project_path:
        return
    token = core.get_effective_token(ctx.project_path)
    ok = git.auto_commit(ctx.project_path, log_cb=ctx.log)
    if ok:
        git.push(ctx.project_path, log_cb=ctx.log, token=token)
```
