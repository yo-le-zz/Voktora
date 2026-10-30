#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Voktora — build_rpm.sh
# Empaquète Voktora en .rpm (Fedora, RHEL/Rocky/Alma, openSUSE…).
# Réutilise la compilation Nuitka déjà produite par build_deb.sh si elle existe
# (dist/linux/nuitka_out/main.dist) ; sinon compile d'abord.
#
# Usage :
#   ./Installers/RPM\ installer/build_rpm.sh [VERSION]
#   VERSION par défaut : contenu de voktora/version.txt
#
# Dépendances build :
#   pip install nuitka pyside6 cryptography
#   sudo apt install patchelf rpm        # Debian/Ubuntu (fournit rpmbuild)
#   sudo dnf install patchelf rpm-build  # Fedora/RHEL
#
# Sortie : dist/linux/voktora-<VERSION>-1.x86_64.rpm
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Ce fichier est dans  Voktora/Installers/RPM installer/
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=../linux_common.sh
source "$ROOT/Installers/linux_common.sh"

VERSION="$(voktora_clean_version "${1:-$(tr -d '[:space:]' < "$ROOT/voktora/version.txt")}")"
# RPM interdit le tiret dans « Version » (il sépare version et release) :
# « 1.0.4-rc1 » devient « 1.0.4~rc1 » (le tilde trie avant 1.0.4, comme une préversion).
VERSION="${VERSION//-/\~}"
if [[ ! "$VERSION" =~ ^[0-9][A-Za-z0-9.+~_]*$ ]]; then
    echo "Version invalide pour un paquet RPM : '$VERSION'" >&2
    exit 1
fi
if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "rpmbuild introuvable : installez le paquet « rpm » (Debian/Ubuntu) ou « rpm-build » (Fedora/RHEL)." >&2
    exit 1
fi

DIST_DIR="$ROOT/dist/linux"
STAGE="$DIST_DIR/rpm_stage"
TOPDIR="$DIST_DIR/rpmbuild"

echo "=== Voktora RPM builder ==="
echo "Version : $VERSION"
echo "Root    : $ROOT"

# ── 1. Compilation Nuitka (partagée avec le .deb) ────────────────────────────
voktora_compile "$ROOT" "$DIST_DIR"

# ── 2. Arborescence installée (identique à celle du .deb) ────────────────────
echo ""
echo ">>> Préparation de l'arborescence..."
voktora_stage_tree "$STAGE" "$ROOT" "$ONEDIR" "$VERSION"

# ── 3. rpmbuild ──────────────────────────────────────────────────────────────
echo ""
echo ">>> Build du paquet RPM..."
rm -rf "$TOPDIR"
mkdir -p "$TOPDIR"/{BUILD,RPMS,SPECS,SRPMS}
cp "$SCRIPT_DIR/voktora.spec" "$TOPDIR/SPECS/voktora.spec"

# Compression xz : bien supportée par toutes les versions de rpm récentes (RHEL 8+, Fedora, openSUSE).
rpmbuild -bb "$TOPDIR/SPECS/voktora.spec" \
    --target x86_64-linux \
    --define "_topdir $TOPDIR" \
    --define "voktora_version $VERSION" \
    --define "voktora_stage $STAGE" \
    --define "voktora_date $(LC_ALL=C date -u '+%a %b %d %Y')" \
    --define "_binary_payload w6.xzdio" \
    --define "_build_name_fmt %%{NAME}-%%{VERSION}-%%{RELEASE}.%%{ARCH}.rpm"

RPM_FILE="$(find "$TOPDIR/RPMS" -name '*.rpm' -print -quit)"
if [[ -z "$RPM_FILE" ]]; then
    echo "Aucun .rpm produit par rpmbuild." >&2
    exit 1
fi
cp "$RPM_FILE" "$DIST_DIR/"
FINAL="$DIST_DIR/$(basename "$RPM_FILE")"
rm -rf "$STAGE" "$TOPDIR"

echo ""
echo "=== Succès ==="
echo "Paquet : $FINAL"
echo "Taille : $(du -sh "$FINAL" | cut -f1)"
