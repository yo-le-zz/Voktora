#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Voktora — build_arch.sh
# Empaquète Voktora au format Arch Linux (.pkg.tar.zst) : Arch, Omarchy, EndeavourOS, Manjaro, CachyOS…
# Installation : sudo pacman -U voktora-<VERSION>-1-x86_64.pkg.tar.zst
#
# Le paquet est assemblé à la main (.PKGINFO + .INSTALL + arbre de fichiers, compressés en zstd) : il se
# construit donc depuis n'importe quelle distribution, sans makepkg — comme le .deb et le .rpm.
# Réutilise la compilation Nuitka de build_deb.sh si elle existe (dist/linux/nuitka_out/main.dist).
#
# Usage : ./Installers/Arch\ installer/build_arch.sh [VERSION]
# Dépendances build : uv, patchelf, tar, zstd
# Sortie : dist/linux/voktora-<VERSION>-1-x86_64.pkg.tar.zst
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=../linux_common.sh
source "$ROOT/Installers/linux_common.sh"

VERSION="$(voktora_clean_version "${1:-$(tr -d '[:space:]' < "$ROOT/voktora/version.txt")}")"
# pacman interdit le tiret dans pkgver : « 1.0.7-rc1 » devient « 1.0.7rc1 ».
VERSION="${VERSION//-/}"
if [[ ! "$VERSION" =~ ^[0-9][A-Za-z0-9._+]*$ ]]; then
    echo "Version invalide pour un paquet Arch : '$VERSION'" >&2
    exit 1
fi
for tool in tar zstd; do
    command -v "$tool" >/dev/null 2>&1 || { echo "$tool introuvable (installez-le pour construire le paquet Arch)." >&2; exit 1; }
done

DIST_DIR="$ROOT/dist/linux"
STAGE="$DIST_DIR/arch_stage"
OUT="$DIST_DIR/voktora-${VERSION}-1-x86_64.pkg.tar.zst"

echo "=== Voktora Arch builder ==="
echo "Version : $VERSION"

voktora_compile "$ROOT" "$DIST_DIR"

rm -rf "$STAGE"
voktora_stage_tree "$STAGE" "$ROOT" "$ONEDIR" "$VERSION"

SIZE="$(du -sb "$STAGE" | cut -f1)"
BUILDDATE="${SOURCE_DATE_EPOCH:-$(date +%s)}"

cat > "$STAGE/.PKGINFO" <<PKG
pkgname = voktora
pkgbase = voktora
pkgver = ${VERSION}-1
pkgdesc = Voktora — gestionnaire de projets de développement (Git, coffre chiffré, snapshots, synchronisation entre PC)
url = https://github.com/yo-le-zz/Voktora
builddate = ${BUILDDATE}
packager = yolezz <https://github.com/yo-le-zz>
size = ${SIZE}
arch = x86_64
license = MIT
depend = glibc
depend = libglvnd
depend = glib2
depend = fontconfig
depend = libxkbcommon-x11
depend = xcb-util-cursor
depend = xcb-util-image
depend = xcb-util-keysyms
depend = xcb-util-renderutil
depend = xcb-util-wm
optdepend = git: clonage et gestion des dépôts
optdepend = tailscale: synchronisation entre PC hors du réseau local
PKG

cat > "$STAGE/.INSTALL" <<'INST'
post_install() {
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
}
post_upgrade() { post_install; }
post_remove() { post_install; }
INST

echo ">>> Création de l'archive..."
(
    cd "$STAGE"
    # .PKGINFO en premier (exigé par pacman), puis le reste ; propriétaire root:root.
    tar --owner=0 --group=0 --numeric-owner -cf - .PKGINFO .INSTALL \
        $(find . -mindepth 1 -maxdepth 1 ! -name .PKGINFO ! -name .INSTALL -printf '%f\n' | sort) \
        | zstd -19 -T0 -q -o "$OUT" -f
)
rm -rf "$STAGE"

echo ""
echo "=== Succès ==="
echo "Paquet : $OUT"
echo "Taille : $(du -sh "$OUT" | cut -f1)"
echo "Installation : sudo pacman -U \"$OUT\""
