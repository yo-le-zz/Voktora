<div align="center">

<img src="assets/Voktora.png" alt="Voktora" width="80"/>

# Voktora

**Project Instance Manager** — Gérez, lancez et automatisez vos projets de développement.

par [**yolezz**](https://github.com/yo-le-zz)

[![Version](https://img.shields.io/badge/version-1.0.0-89b4fa?style=flat-square)](https://github.com/yo-le-zz/Voktora/releases)
[![Python](https://img.shields.io/badge/python-3.11+-cba6f7?style=flat-square)](https://python.org)
[![PySide6](https://img.shields.io/badge/PySide6-6.x-a6e3a1?style=flat-square)](https://pypi.org/project/PySide6/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-fab387?style=flat-square)](#installation)
[![License](https://img.shields.io/badge/license-MIT-f38ba8?style=flat-square)](LICENSE)

[**Télécharger**](https://github.com/yo-le-zz/Voktora/releases/latest) · [**Documentation**](docs/) · [**Changelog**](docs/CHANGELOG.md)

</div>

---

## Présentation

Voktora est un gestionnaire de projets de développement avec interface graphique (**thème Catppuccin Mocha**). Il centralise tous vos projets Git : instances actives, intents à démarrer, profils de lancement, hooks d'automatisation, vault de secrets, snapshots, analytics et plugins.

---

## Installation

| Plateforme | Téléchargement | Commande |
|-----------|---------------|---------|
| 🐧 Linux (Debian/Ubuntu) | `voktora_1.0.0_amd64.deb` | `sudo dpkg -i voktora_*.deb` |
| 🪟 Windows 10/11 x64 | `Voktora_1.0.0_x64.msi` | Double-cliquer |

→ [Guide d'installation complet](docs/INSTALL.md)

---

## Fonctionnalités

| Fonctionnalité | Description |
|---------------|-------------|
| 🗂 Vue liste / grille | Projets en liste compacte ou cartes visuelles avec icône personnalisable |
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
| [INSTALL.md](docs/INSTALL.md) | Installation .deb, .msi, depuis les sources |
| [BUILD.md](docs/BUILD.md) | Compilation Nuitka, packaging .deb / .msi |
| [PLUGINS.md](docs/PLUGINS.md) | Développer des plugins |
| [VAULT.md](docs/VAULT.md) | Vault & sécurité |
| [HOOKS.md](docs/HOOKS.md) | Système de hooks |
| [PROFILES.md](docs/PROFILES.md) | Profils d'exécution |
| [SNAPSHOTS.md](docs/SNAPSHOTS.md) | Snapshots de projets |
| [DASHBOARD.md](docs/DASHBOARD.md) | Dashboard santé & usage |
| [TEMPLATES.md](docs/TEMPLATES.md) | Templates de projets |
| [CHANGELOG.md](docs/CHANGELOG.md) | Historique des versions |

---

## Structure

```
Voktora/
├── src/                    Code source Python
│   ├── main.py             Point d'entrée
│   ├── core.py             Logique, config, crypto AES-256
│   ├── vault.py            Vault sécurisé
│   ├── git.py              Git automation
│   ├── hooks.py            Hooks
│   ├── profiles.py         Profils d'exécution
│   ├── templates.py        Templates projets
│   ├── snapshots.py        Snapshots
│   ├── dashboard.py        Analytics
│   ├── plugins.py          Plugins
│   ├── migration.py        Migration config
│   ├── theme_manager.py    Thèmes
│   ├── ui_main.py          MainWindow
│   ├── ui_project_view.py  Vue liste/grille
│   ├── ui_project_panel.py Panneau projet
│   ├── ui_dialogs.py       Dialogs
│   └── themes/             CSS Catppuccin
├── assets/
│   ├── Voktora.png         Icône (unique source)
│   └── Voktora.ico         Icône Windows
├── packaging/
│   ├── build_deb.sh        Script .deb Linux
│   ├── build_msi.py        Script .msi Windows
│   └── voktora.wxs         Définition WiX
├── docs/                   Documentation complète
├── web/                    Page de téléchargement Cloudflare
└── .github/workflows/      CI/CD
```

---

## Raccourcis

| Raccourci | Action |
|-----------|--------|
| `F5` | Actualiser |
| `Ctrl+N` | Nouvelle instance |
| `Ctrl+F` | Rechercher / switcher projet |
| `Escape` | Effacer la recherche |

---

## Licence

MIT — [LICENSE](LICENSE)

Créé par [yolezz](https://github.com/yo-le-zz)
