#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Voktora — build_deb.sh
# Compile avec Nuitka (--standalone, réutilisé si déjà compilé) puis empaquète en .deb
#
# Arborescence attendue :
#   Voktora/
#   ├── assets/                  ← icônes sources
#   ├── Installers/
#   │   ├── linux_common.sh      ← fonctions partagées .deb / .rpm
#   │   ├── DEB installer/
#   │   │   └── build_deb.sh     ← CE FICHIER
#   │   ├── RPM installer/
#   │   │   ├── build_rpm.sh
#   │   │   └── voktora.spec
#   │   └── MSI installer/
#   │       ├── build_msi.py
#   │       └── voktora.wxs
#   └── voktora/
#       ├── main.py
#       ├── themes/
#       └── version.txt
#
# Usage :
#   ./Installers/DEB\ installer/build_deb.sh [VERSION]
#   VERSION par défaut : contenu de voktora/version.txt
#
# Dépendances build :
#   pip install nuitka pyside6 cryptography
#   sudo apt install patchelf dpkg-dev
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Ce fichier est dans  Voktora/Installers/DEB installer/
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=../linux_common.sh
source "$ROOT/Installers/linux_common.sh"

VERSION="$(voktora_clean_version "${1:-$(tr -d '[:space:]' < "$ROOT/voktora/version.txt")}")"
# Le numero de version Debian DOIT commencer par un chiffre (regle dpkg-deb).
if [[ ! "$VERSION" =~ ^[0-9][A-Za-z0-9.+~:-]*$ ]]; then
    echo "Version invalide pour un paquet Debian : '$VERSION'" >&2
    exit 1
fi
ARCH="amd64"
PKG_NAME="voktora"
DIST_DIR="$ROOT/dist/linux"
DEB_ROOT="$DIST_DIR/${PKG_NAME}_${VERSION}_${ARCH}"
DEB_FILE="$DIST_DIR/${PKG_NAME}_${VERSION}_${ARCH}.deb"

echo "=== Voktora DEB builder ==="
echo "Version : $VERSION"
echo "Root    : $ROOT"

# ── 1. Compilation Nuitka (partagée avec le .rpm) ────────────────────────────
voktora_compile "$ROOT" "$DIST_DIR"

# ── 2. Structure du paquet .deb ──────────────────────────────────────────────
echo ""
echo ">>> Création de la structure DEB..."
rm -f "$DEB_FILE"
voktora_stage_tree "$DEB_ROOT" "$ROOT" "$ONEDIR" "$VERSION"

mkdir -p "$DEB_ROOT/DEBIAN"
cat > "$DEB_ROOT/DEBIAN/control" << EOF
Package: voktora
Version: $VERSION
Architecture: $ARCH
Maintainer: yolezz <https://github.com/yo-le-zz>
Section: devel
Priority: optional
Depends: libgl1, libegl1, libopengl0, libglib2.0-0, libfontconfig1, libxcb-xinerama0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-xkb1, libxcb-cursor0, libxkbcommon-x11-0
Description: Voktora — Project Instance Manager
 Gestionnaire de projets de développement avec interface graphique.
 Supporte instances/intents, coffre chiffré (Fernet), profils d'exécution,
 hooks, snapshots, dashboard de santé et système de plugins.
 Thème Catppuccin Mocha. Authentification GitHub App ou OAuth.
 .
 Créé par yolezz.
Homepage: https://github.com/yo-le-zz/Voktora
EOF

# DEBIAN/postinst — mise à jour du cache icônes/apps
cat > "$DEB_ROOT/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache /usr/share/icons/hicolor || true
fi
EOF
chmod 755 "$DEB_ROOT/DEBIAN/postinst"

# DEBIAN/prerm — nettoyage avant suppression
cat > "$DEB_ROOT/DEBIAN/prerm" << 'EOF'
#!/bin/bash
set -e
EOF
chmod 755 "$DEB_ROOT/DEBIAN/prerm"

# ── 3. Build .deb ────────────────────────────────────────────────────────────
echo ""
echo ">>> Build du paquet DEB..."
dpkg-deb --build --root-owner-group "$DEB_ROOT" "$DEB_FILE"
rm -rf "$DEB_ROOT"

echo ""
echo "=== Succès ==="
echo "Paquet : $DEB_FILE"
echo "Taille : $(du -sh "$DEB_FILE" | cut -f1)"
