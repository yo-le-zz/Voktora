# Voktora — Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/)

---

## [1.0.0] — Release initiale

Première version publique de **Voktora** (anciennement Meridian), entièrement rebranded et restructuré.

Créé par **yolezz**.

### ✦ Interface

- **Double vue projets** : liste ☰ et grille ⊞ switchables
  - Grille : cartes visuelles avec icône personnalisable (image ou emoji), badge langage coloré, badge instance/intent
  - Liste : sidebar compacte avec recherche unifiée, filtrage live, couleurs
- **Panneau projet dédié** : plein écran avec 5 onglets (Actions / Git / Outils / Snapshots / Détails)
  - Header : icône cliquable, nom, badges, bouton ⇄ Autre projet
  - Journal intégré par projet
- Barre de statut : compteur projets + version
- Raccourcis : `F5`, `Ctrl+N`, `Ctrl+F`, `Escape`
- Thème Catppuccin Mocha (PySide6), polices cross-platform

### 🔐 Sécurité & Vault

- **Master password** au premier lancement (PBKDF2-HMAC-SHA256, 480 000 itérations)
- **Vault AES-256** (Fernet) avec clé dérivée par domaine : `github_token`, `ssh_key`, `api_key`, `env_secret`, `general`
- Tokens GitHub automatiquement stockés dans le vault si déverrouillé
- `token_encrypt()` / `token_decrypt()` → AES-256 Fernet (remplace l'ancien XOR)

### 🐙 GitHub

- **GitHub App** (JWT RS256) : token d'installation renouvelé automatiquement (cache 55 min)
- **OAuth App** (Device Flow) : rétrocompat totale
- Dialog de connexion refait : 6 pages (choix / OAuth / GitHub App / device code / attente / guide migration)
- `verify_github_token()` : vérification token en temps réel

### ⚡ Fonctionnalités

- **Profils d'exécution** (`profiles.py`) : commande, env vars, dossier, pre/post scripts
- **Hooks** (`hooks.py`) : 7 événements, handlers shell ou Python
- **Templates** (`templates.py`) : Python, C++, Web App, Discord Bot, Minecraft Mod, Vide
- **Snapshots** (`snapshots.py`) : capture, restauration, diff entre snapshots
- **Dashboard** (`dashboard.py`) : santé et usage avec scores 0–100
- **Plugins** (`plugins.py`) : système extensible, rechargement à chaud
- **Git automation** (`git.py`) : smart commit (Conventional Commits), auto-push, push avec token

### 📦 Packaging

- **Linux** : paquet `.deb` (dpkg) — installe dans `/opt/voktora/`, symlink `/usr/bin/voktora`, `.desktop` XDG, AppStream XML
- **Windows** : paquet `.msi` (WiX Toolset 4.x) — installe dans `C:\Program Files\Voktora\`, raccourcis Bureau + Menu Démarrer
- Remplacement de l'installateur PySide6 custom

### 🔧 Architecture

| Fichier | Rôle |
|---------|------|
| `main.py` | Point d'entrée, master password setup |
| `core.py` | Config, crypto, auth GitHub, session |
| `vault.py` | Vault sécurisé AES-256 |
| `git.py` | Git automation |
| `hooks.py` | Système de hooks |
| `profiles.py` | Profils d'exécution |
| `templates.py` | Templates de projets |
| `snapshots.py` | Snapshot / restore / diff |
| `dashboard.py` | Health & usage analytics |
| `plugins.py` | Plugins extensibles |
| `migration.py` | Migration de config |
| `theme_manager.py` | Thèmes CSS |
| `ui_main.py` | MainWindow |
| `ui_project_view.py` | Vue liste / grille (ProjectBrowser) |
| `ui_project_panel.py` | Panneau projet 5 onglets |
| `ui_dialogs.py` | Tous les dialogs fusionnés |

### 🚀 CI/CD

- Push `dev` → PR automatique vers `main` (titre = version)
- Squash & Merge → build `.deb` + `.msi` → release GitHub
- `src/version.txt` écrit par le CI à chaque release
