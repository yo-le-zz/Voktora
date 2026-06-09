# Voktora — Guide de compilation

> Créé par **yolezz** · [github.com/yo-le-zz/Voktora](https://github.com/yo-le-zz/Voktora)

---

## Prérequis

| Outil | Version | Installation |
|-------|---------|--------------|
| Python | 3.11+ | [python.org](https://python.org) |
| uv | dernière | `pip install uv` |
| Nuitka | 2.x | `uv pip install nuitka` |
| PySide6 | 6.x | `uv pip install pyside6` |
| cryptography | dernière | `uv pip install cryptography` |

**Linux uniquement :**
```bash
sudo apt install patchelf dpkg-dev \
  libxcb-xinerama0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
  libxcb-xkb1 libxkbcommon-x11-0 libgl1 libglib2.0-0
```

**Windows uniquement :**
```powershell
dotnet tool install --global wix
wix extension add WixToolset.UI.wixext
```

---

## Lancement en mode développement

```bash
git clone https://github.com/yo-le-zz/Voktora.git
cd Voktora
uv venv
source .venv/bin/activate  # Windows : .venv\Scripts\activate
uv pip install pyside6 cryptography
python src/main.py
```

---

## Compilation Nuitka (onedir)

### Linux

```bash
python -m nuitka \
  --standalone \
  --remove-output \
  --enable-plugin=pyside6 \
  --disable-console \
  --linux-icon=assets/Voktora.png \
  --output-dir=dist/linux \
  --output-filename=voktora \
  src/main.py

# Copier les ressources
cp -r src/themes dist/linux/main.dist/themes
cp -r assets     dist/linux/main.dist/assets
cp src/version.txt dist/linux/main.dist/version.txt

# Lancer
./dist/linux/main.dist/voktora
```

### Windows (PowerShell)

```powershell
python -m nuitka `
  --standalone `
  --remove-output `
  --enable-plugin=pyside6 `
  --windows-icon-from-ico=assets\Voktora.ico `
  --windows-console-mode=disable `
  --output-dir=dist\windows `
  --output-filename=voktora `
  src\main.py

# Copier les ressources
Copy-Item -Recurse src\themes dist\windows\main.dist\themes
Copy-Item -Recurse assets     dist\windows\main.dist\assets
Copy-Item src\version.txt     dist\windows\main.dist\version.txt

# Lancer
.\dist\windows\main.dist\voktora.exe
```

---

## Créer le paquet .deb (Linux)

```bash
# Script automatique (compile + package en .deb)
bash packaging/build_deb.sh 1.0.0

# Résultat
ls dist/linux/voktora_1.0.0_amd64.deb
```

Le script :
1. Compile avec Nuitka `--standalone` (onedir)
2. Crée la structure `DEBIAN/` (control, postinst, prerm)
3. Place les fichiers dans `/opt/voktora/`
4. Crée un symlink `/usr/bin/voktora`
5. Génère le `.desktop` et l'AppStream XML
6. Appelle `dpkg-deb --build`

---

## Créer le paquet .msi (Windows)

```powershell
# Script automatique (compile + package en .msi via WiX)
python packaging\build_msi.py 1.0.0

# Résultat
dir dist\windows\Voktora_1.0.0_x64.msi
```

Le script :
1. Compile avec Nuitka `--standalone` (onedir)
2. Harvest les fichiers avec `wix harvest`
3. Build le MSI avec `wix build voktora.wxs`
4. Installe dans `C:\Program Files\Voktora\`
5. Crée des raccourcis Bureau + Menu Démarrer

---

## CI/CD automatique

Push sur `dev` → PR automatique vers `main` (titre = version).  
Squash & Merge → build `.deb` (Linux) + `.msi` (Windows) → release GitHub.

Voir `.github/workflows/build-release.yml` pour les détails.

---

## Variables importantes

| Variable | Fichier | Description |
|----------|---------|-------------|
| `APP_VERSION` | `src/core.py` | Version de l'app (surchargée par `version.txt`) |
| `APP_NAME` | `src/core.py` | Nom affiché (`"Voktora"`) |
| `GITHUB_API_LATEST` | `src/core.py` | URL API GitHub pour les mises à jour |
| `PBKDF2_ITERATIONS` | `src/core.py` | Itérations PBKDF2 (480 000) |
