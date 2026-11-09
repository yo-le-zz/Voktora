# Voktora — Guide de compilation

> Créé par **yolezz** · [github.com/yo-le-zz/Voktora](https://github.com/yo-le-zz/Voktora)

---

> 🐳 **Docker : usage local optionnel uniquement.** La CI GitHub Actions
> compile directement sur les runners (voir `.github/workflows/build-release.yml`),
> pas via Docker — Windows notamment ne peut pas compiler via Docker sur les
> runners GitHub hébergés (Docker Desktop n'y est pas installé). Les
> `Dockerfile` dans `docker/` restent disponibles pour qui veut un
> environnement reproductible en local. Voir [`docker/README.md`](../docker/README.md)
> (y compris un problème connu non résolu sur le build Linux via Docker).
> Le reste de ce guide décrit la compilation manuelle directe, la méthode
> utilisée par la CI.

---

## Prérequis

| Outil | Version | Installation |
|-------|---------|--------------|
| Python | 3.11+ | [python.org](https://python.org) |
| uv | dernière | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (Windows : `irm https://astral.sh/uv/install.ps1 \| iex`) |
| Rust (optionnel) | stable | [rustup.rs](https://rustup.rs) — pour l'extension native ; sans lui, Python pur |

Nuitka, PySide6 et cryptography sont installés **par uv** depuis `uv.lock` : n'utilisez jamais `pip`.
Les scripts `Installers/*` lancent tout via `uv run` : un simple `./Installers/RPM\ installer/build_rpm.sh`
suffit (uv synchronise l'environnement, compile l'extension Rust si `cargo` est présent, puis Nuitka).

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
uv sync                          # environnement + dépendances depuis uv.lock
uv run python voktora/main.py
```

---

## Compilation Nuitka (onedir)

### Linux

```bash
uv run --group build python -m nuitka \
  --standalone \
  --remove-output \
  --enable-plugin=pyside6 \
  --disable-console \
  --linux-icon=assets/Voktora.png \
  --output-dir=dist/linux \
  --output-filename=voktora \
  voktora/main.py

# Copier les ressources
cp -r voktora/themes dist/linux/main.dist/themes
cp -r assets     dist/linux/main.dist/assets
cp voktora/version.txt dist/linux/main.dist/version.txt

# Lancer
./dist/linux/main.dist/voktora
```

### Windows (PowerShell)

```powershell
uv run --group build python -m nuitka `
  --standalone `
  --remove-output `
  --enable-plugin=pyside6 `
  --windows-icon-from-ico=assets\Voktora.ico `
  --windows-console-mode=disable `
  --output-dir=dist\windows `
  --output-filename=voktora `
  voktora\main.py

# Copier les ressources
Copy-Item -Recurse voktora\themes dist\windows\main.dist\themes
Copy-Item -Recurse assets     dist\windows\main.dist\assets
Copy-Item voktora\version.txt     dist\windows\main.dist\version.txt

# Lancer
.\dist\windows\main.dist\voktora.exe
```

---

## Créer le paquet .deb (Linux)

```bash
# Script automatique (compile + package en .deb)
bash "Installers/DEB installer/build_deb.sh" 1.1.0

# Résultat
ls dist/linux/voktora_1.1.0_amd64.deb
```

Le script :
1. Compile avec Nuitka `--standalone` (onedir) — sauf si `dist/linux/nuitka_out/main.dist` existe déjà
   (forcer avec `VOKTORA_FORCE_COMPILE=1`)
2. Construit l'arborescence installée (`Installers/linux_common.sh`) : `/opt/voktora/`, symlink
   `/usr/bin/voktora`, icône, `.desktop`, AppStream XML, licence
3. Crée la structure `DEBIAN/` (control, postinst, prerm)
4. Appelle `dpkg-deb --build`

---

## Créer le paquet .rpm (Linux)

```bash
# Prérequis : paquet « rpm » (Debian/Ubuntu) ou « rpm-build » (Fedora/RHEL)
bash "Installers/RPM installer/build_rpm.sh" 1.1.0

# Résultat
ls dist/linux/voktora-1.1.0-1.x86_64.rpm
```
## Paquet Arch / Omarchy (`.pkg.tar.zst`)

Assemblé à la main (`.PKGINFO` + `.INSTALL` + arbre de fichiers, zstd) : se construit depuis n'importe quelle
distribution, sans `makepkg`. Réutilise la compilation Nuitka du `.deb`. Dépend de `zstd`.

```bash
bash "Installers/Arch installer/build_arch.sh" 1.1.0
ls dist/linux/voktora-1.1.0-1-x86_64.pkg.tar.zst
```

`1.1.0-rc1` devient `1.1.0rc1` (pacman interdit le tiret dans `pkgver`).


Le script réutilise la compilation Nuitka du `.deb` si elle existe (la CI compile **une seule fois**
puis produit les deux paquets), construit la même arborescence installée, puis lance `rpmbuild -bb`
avec `Installers/RPM installer/voktora.spec`. Particularités :

- paquet binaire (`ExclusiveArch: x86_64`), compression xz, sans `debuginfo` ni strip (Nuitka embarque Qt) ;
- dépendances déclarées **par bibliothèque** (`libGL.so.1()(64bit)`…) : valables sur Fedora, RHEL et openSUSE ;
- une version de préversion `1.1.0-rc1` devient `1.1.0~rc1` (le tiret est interdit dans le champ `Version`) ;
- contrôle rapide : `rpm -qpl`, `rpm -qpR` et `rpm -qpi` sur le fichier produit.

---

## Créer le paquet .msi (Windows)

```powershell
# Script automatique (compile + package en .msi via WiX)
uv run --group build python "Installers\MSI installer\build_msi.py" 1.1.0

# Résultat
dir dist\windows\Voktora_1.1.0_x64.msi
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
Squash & Merge → build `.deb` + `.rpm` (Linux) et `.msi` (Windows) → release GitHub (avec `SHA256SUMS`).
Le titre de la PR est validé (`v1.2.3`) avant d'être utilisé : il ne peut pas injecter de commande dans le build.

Voir `.github/workflows/build-release.yml` pour les détails.

---

## Variables importantes

| Variable | Fichier | Description |
|----------|---------|-------------|
| `APP_VERSION` | `src/core.py` | Version de l'app (surchargée par `version.txt`) |
| `APP_NAME` | `src/core.py` | Nom affiché (`"Voktora"`) |
| `GITHUB_API_LATEST` | `src/core.py` | URL API GitHub pour les mises à jour |
| `PBKDF2_ITERATIONS` | `src/core.py` | Itérations PBKDF2 (480 000) |
