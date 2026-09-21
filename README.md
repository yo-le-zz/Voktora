<div align="center">

<img src="assets/Voktora.png" alt="Voktora" width="80"/>

# Voktora

**Project Manager** — Gérez, lancez et automatisez vos projets de développement.

par [**yolezz**](https://github.com/yo-le-zz)

[![Version](https://img.shields.io/badge/version-1.0.3-89b4fa?style=flat-square)](https://github.com/yo-le-zz/Voktora/releases)
[![Python](https://img.shields.io/badge/python-3.13+-cba6f7?style=flat-square)](https://python.org)
[![PySide6](https://img.shields.io/badge/PySide6-6.x-a6e3a1?style=flat-square)](https://pypi.org/project/PySide6/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-fab387?style=flat-square)](#installation)
[![License](https://img.shields.io/badge/license-MIT-f38ba8?style=flat-square)](LICENSE)

[**Télécharger**](https://github.com/yo-le-zz/Voktora/releases/latest) · [**Documentation**](doc/) · [**Changelog**](CHANGELOG.md)

</div>

---

## Présentation

Voktora est un gestionnaire de projets de développement avec interface graphique (**thème Catppuccin Mocha**). Il centralise tous vos projets Git — classés par catégories que vous créez, ou par organisation GitHub — avec profils de lancement, hooks d'automatisation, vault de secrets, snapshots, analytics et plugins.

---

## Installation

| Plateforme | Téléchargement | Commande |
|-----------|---------------|---------|
| 🐧 Linux (Debian/Ubuntu) | `voktora_1.0.3_amd64.deb` | `sudo dpkg -i voktora_*.deb` |
| 🪟 Windows 10/11 x64 | `Voktora_1.0.3_x64.msi` | Double-cliquer |

→ [Guide d'installation complet](doc/INSTALL.md)

---

## Fonctionnalités

| Fonctionnalité | Description |
|---------------|-------------|
| 🗂 Vue liste / grille | Projets en liste compacte ou cartes visuelles, regroupés par catégorie, organisation GitHub, langage ou statut |
| 📂 Catégories | Créez les vôtres (nom, emoji, couleur), glissez-y vos projets, ou générez-les depuis vos organisations GitHub |
| 📥 Import | Dossier (déplacé, copié ou ajouté sur place) ou archive ZIP, avec progression et annulation — glisser-déposer accepté |
| 🐙 Clone GitHub | Choisissez parmi vos dépôts et ceux de vos organisations, ou collez une URL |
| 🔐 Vault AES-256 | Stockage chiffré de tokens, clés SSH, API keys |
| ⚡ Profils d'exécution | Commande, env vars, scripts pre/post run par projet |
| 🪝 Hooks | Automatisations shell/Python sur 7 événements Git/projet |
| 📸 Snapshots | Capture, restauration, diff entre états d'un projet |
| 🧱 Templates | Python, C++, Web, Discord Bot, Minecraft Mod |
| 📊 Dashboard | Score de santé 0–100, stats d'usage, .gitignore check |
| 🧩 Plugins | Système extensible, rechargement à chaud |
| 🐙 GitHub App | JWT RS256, token renouvelé automatiquement |
| 🧠 Smart commit | Messages Conventional Commits sans IA |

---

## Documentation

| Doc | Contenu |
|-----|---------|
| [INSTALL.md](doc/INSTALL.md) | Installation .deb, .msi, depuis les sources |
| [BUILD.md](doc/BUILD.md) | Compilation Nuitka, packaging .deb / .msi |
| [PLUGINS.md](doc/PLUGINS.md) | Développer des plugins |
| [VAULT.md](doc/VAULT.md) | Vault & sécurité |
| [HOOKS.md](doc/HOOKS.md) | Système de hooks |
| [PROFILES.md](doc/PROFILES.md) | Profils d'exécution |
| [SNAPSHOTS.md](doc/SNAPSHOTS.md) | Snapshots de projets |
| [DASHBOARD.md](doc/DASHBOARD.md) | Dashboard santé & usage |
| [TEMPLATES.md](doc/TEMPLATES.md) | Templates de projets |
| [PROJECTS.md](doc/PROJECTS.md) | Projets, catégories, import, clone GitHub |
| [SECURITY.md](doc/SECURITY.md) | Modèle de sécurité et audit |
| [CHANGELOG.md](CHANGELOG.md) | Historique des versions |

---

## Structure

```
Voktora/
├── voktora/                Code source Python
│   ├── main.py             Point d'entrée
│   ├── core/               Logique métier (package)
│   │   ├── config_store.py   config.json, migrations, entrées normalisées
│   │   ├── projects.py       Création, import (ZIP/dossier/clone), export
│   │   ├── archive.py        Extraction/copie/déplacement/export avec progression
│   │   ├── categories.py     Catégories créées par l'utilisateur
│   │   ├── organize.py       Recherche, tri, regroupement (logique pure)
│   │   ├── github_api.py     Dépôts et organisations GitHub
│   │   ├── github_auth.py    OAuth / GitHub App
│   │   ├── git_ops.py        Opérations Git (authentification sûre)
│   │   └── …                 crypto, diagnostics, drives, paths, system
│   ├── ui_main/            Fenêtre principale et dialogues (import, clone, progression…)
│   ├── ui_dialogs/         Autres dialogues (catégories, personnalisation…)
│   ├── ui_project_view.py  Vues liste (arbre groupé) et grille
│   ├── ui_project_panel.py Panneau projet
│   ├── task_worker.py      Thread de travail (progression, annulation)
│   ├── vault.py · hooks.py · profiles.py · templates.py · snapshots.py
│   ├── dashboard.py · plugins.py · theme_manager.py · mc.py · git.py
│   └── themes/             CSS Catppuccin
├── tests/                  Suite pytest (`uv run pytest`)
├── assets/                 Icônes
├── Installers/             Scripts .deb (Linux) et .msi (Windows)
├── docker/                 Compilation reproductible
├── doc/                    Documentation
├── WebSite/                Page de téléchargement
└── .github/workflows/      CI/CD
```

---

## Raccourcis

| Raccourci | Action |
|-----------|--------|
| `F5` | Actualiser |
| `Ctrl+N` | Nouveau projet |
| `Ctrl+I` | Importer un dossier ou un ZIP |
| `Ctrl+F` | Rechercher / switcher projet |
| `Escape` | Effacer la recherche |

---

## Développement

```bash
uv sync                       # installe les dépendances (Python 3.13)
uv run pytest                 # tests (QT_QPA_PLATFORM=offscreen pour l'UI sans écran)
uv run ruff check .           # lint
uv run python voktora/main.py # lance l'application
```

---

## Licence

MIT — [LICENSE](LICENSE)

Créé par [yolezz](https://github.com/yo-le-zz)
