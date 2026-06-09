# Voktora — Guide d'installation

> Créé par **yolezz**

---

## 🐧 Linux (Debian / Ubuntu / Mint)

### Via le paquet .deb (recommandé)

```bash
# 1. Télécharger le .deb depuis la dernière release
wget https://github.com/yo-le-zz/Voktora/releases/latest/download/voktora_1.0.0_amd64.deb

# 2. Installer
sudo dpkg -i voktora_1.0.0_amd64.deb

# 3. Si des dépendances manquent
sudo apt-get install -f

# 4. Lancer
voktora
# ou depuis le menu Applications → Développement → Voktora
```

### Désinstallation Linux

```bash
sudo dpkg -r voktora
# ou complète (supprime les fichiers de config système)
sudo dpkg --purge voktora
```

Les données utilisateur (`~/.voktora/`) ne sont **pas** supprimées.

---

## 🪟 Windows 10/11

### Via le .msi (recommandé)

1. Télécharger `Voktora_1.0.0_x64.msi` depuis [les releases GitHub](https://github.com/yo-le-zz/Voktora/releases/latest)
2. Double-cliquer sur le `.msi`
3. Suivre l'assistant d'installation (Next → Install → Finish)
4. Voktora est disponible dans le menu Démarrer et sur le Bureau

**Dossier d'installation :** `C:\Program Files\Voktora\`

### Désinstallation Windows

- Paramètres → Applications → Voktora → Désinstaller
- ou Panneau de configuration → Programmes → Voktora → Désinstaller

Les données utilisateur (`%LOCALAPPDATA%\Voktora\` ou `~/.voktora/`) ne sont **pas** supprimées.

---

## 📦 Depuis les sources

```bash
git clone https://github.com/yo-le-zz/Voktora.git
cd Voktora
pip install uv
uv pip install pyside6 cryptography
python src/main.py
```

Voir [BUILD.md](BUILD.md) pour les détails de compilation.

---

## 🔐 Premier lancement

Au premier démarrage, Voktora vous demande de créer un **mot de passe maître**.

Ce mot de passe :
- **n'est jamais stocké** (seul un verifier PBKDF2 est conservé)
- dérive une clé AES-256 unique pour chaque type de secret
- protège vos tokens GitHub, clés SSH et API keys dans le vault

Vous pouvez cliquer **Passer** pour un vault non chiffré (déconseillé).

---

## 📁 Données utilisateur

Voktora stocke ses données dans `~/.voktora/` :

```
~/.voktora/
├── voktora_config.json   ← Configuration principale
├── vault_meta.json       ← Métadonnées vault (non chiffrées)
├── hooks.json            ← Hooks configurés
├── usage.json            ← Stats d'usage locales
├── profiles/             ← Profils d'exécution par projet
├── snapshots/            ← Snapshots de projets
└── plugins/              ← Plugins installés
```

---

## ✅ Dépendances runtime Linux

Installées automatiquement avec le `.deb` :

- `libgl1` — OpenGL
- `libglib2.0-0` — GLib
- `libxcb-xinerama0`, `libxcb-icccm4`, `libxcb-image0` — XCB Qt
- `libxcb-keysyms1`, `libxcb-randr0`, `libxcb-render-util0`
- `libxcb-xkb1`, `libxkbcommon-x11-0`
