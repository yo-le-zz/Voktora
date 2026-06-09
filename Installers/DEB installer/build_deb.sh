#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Voktora — build_deb.sh
# Compile avec Nuitka (--onedir) puis empaquète en .deb
#
# Usage :
#   ./packaging/build_deb.sh [VERSION]
#   VERSION par défaut : contenu de voktora/version.txt
#
# Dépendances build :
#   pip install nuitka pyside6 cryptography
#   sudo apt install patchelf dpkg-dev
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="${1:-$(cat "$ROOT/voktora/version.txt" | tr -d '[:space:]')}"
ARCH="amd64"
PKG_NAME="voktora"
DIST_DIR="$ROOT/dist/linux"
DEB_ROOT="$DIST_DIR/${PKG_NAME}_${VERSION}_${ARCH}"
INSTALL_DIR="/opt/voktora"

echo "=== Voktora DEB builder ==="
echo "Version : $VERSION"
echo "Root    : $ROOT"

# ── 1. Nettoyage ─────────────────────────────────────────────────────────────
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

# ── 2. Compilation Nuitka --onedir ───────────────────────────────────────────
echo ""
echo ">>> Compilation Nuitka..."
python -m nuitka \
  --standalone \
  --remove-output \
  --enable-plugin=pyside6 \
  --disable-console \
  --linux-icon="$ROOT/assets/Voktora.png" \
  --output-dir="$DIST_DIR/nuitka_out" \
  --output-filename=voktora \
  "$ROOT/voktora/main.py"

ONEDIR="$DIST_DIR/nuitka_out/main.dist"

# Copier ressources
cp -r "$ROOT/voktora/themes" "$ONEDIR/themes"
cp -r "$ROOT/assets"     "$ONEDIR/assets"
cp    "$ROOT/voktora/version.txt" "$ONEDIR/version.txt"

# ── 3. Structure du paquet .deb ──────────────────────────────────────────────
echo ""
echo ">>> Création de la structure DEB..."

# DEBIAN/control
mkdir -p "$DEB_ROOT/DEBIAN"
cat > "$DEB_ROOT/DEBIAN/control" << EOF
Package: voktora
Version: $VERSION
Architecture: $ARCH
Maintainer: yolezz <https://github.com/yo-le-zz>
Section: devel
Priority: optional
Depends: libgl1, libglib2.0-0, libxcb-xinerama0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-xkb1, libxkbcommon-x11-0
Description: Voktora — Project Instance Manager
 Gestionnaire de projets de développement avec interface graphique.
 Supporte instances/intents, vault sécurisé AES-256, profils d'exécution,
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

# Binaire + dépendances → /opt/voktora/
mkdir -p "$DEB_ROOT$INSTALL_DIR"
cp -r "$ONEDIR/." "$DEB_ROOT$INSTALL_DIR/"
chmod +x "$DEB_ROOT$INSTALL_DIR/voktora"

# Symlink → /usr/bin/voktora
mkdir -p "$DEB_ROOT/usr/bin"
ln -s "$INSTALL_DIR/voktora" "$DEB_ROOT/usr/bin/voktora"

# Icône
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/256x256/apps"
cp "$ROOT/assets/Voktora.png" "$DEB_ROOT/usr/share/icons/hicolor/256x256/apps/voktora.png"

# .desktop
mkdir -p "$DEB_ROOT/usr/share/applications"
cat > "$DEB_ROOT/usr/share/applications/voktora.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Voktora
Comment=Project Instance Manager — by yolezz
Exec=$INSTALL_DIR/voktora
Icon=voktora
Categories=Development;Utility;
Terminal=false
StartupWMClass=Voktora
Keywords=project;git;manager;developer;
EOF

# AppStream metainfo
mkdir -p "$DEB_ROOT/usr/share/metainfo"
cat > "$DEB_ROOT/usr/share/metainfo/io.github.yo_le_zz.Voktora.metainfo.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>io.github.yo_le_zz.Voktora</id>
  <name>Voktora</name>
  <summary>Project Instance Manager</summary>
  <description>
    <p>Gestionnaire de projets de développement : instances, intents, vault AES-256,
    profils d'exécution, hooks, snapshots, dashboard et plugins.</p>
  </description>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <url type="homepage">https://github.com/yo-le-zz/Voktora</url>
  <launchable type="desktop-id">voktora.desktop</launchable>
  <releases>
    <release version="$VERSION"/>
  </releases>
</component>
EOF

# ── 4. Build .deb ────────────────────────────────────────────────────────────
echo ""
echo ">>> Build du paquet DEB..."
DEB_FILE="$DIST_DIR/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$DEB_ROOT" "$DEB_FILE"

echo ""
echo "=== Succès ==="
echo "Paquet : $DEB_FILE"
echo "Taille : $(du -sh "$DEB_FILE" | cut -f1)"
