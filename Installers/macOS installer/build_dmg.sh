#!/usr/bin/env bash
# Voktora — build_dmg.sh : compile avec Nuitka (macOS Intel x86_64 UNIQUEMENT, pas arm64) et produit Voktora_<version>_x86_64.dmg.
# Usage : build_dmg.sh [VERSION]      Prérequis : uv, Xcode command line tools.   (non testé sur un vrai Mac au moment de l'écriture)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${1:-$(tr -d '[:space:]' < "$ROOT/voktora/version.txt")}"; VERSION="${VERSION#[vV]}"
if [[ "$(uname -m)" != "x86_64" ]]; then echo "Ce build vise macOS Intel (x86_64) ; machine détectée : $(uname -m)" >&2; exit 1; fi
DIST="$ROOT/dist/macos"; rm -rf "$DIST"; mkdir -p "$DIST"
UV=(uv run --frozen --project "$ROOT" --group build)
# Icône : PNG -> .icns avec sips/iconutil (Nuitka exigerait sinon le paquet « imageio »)
ICNS="$DIST/Voktora.icns"; bash "$ROOT/Installers/macOS installer/make_icns.sh" "$ICNS"
# Compilation plus rapide : pas de LTO par défaut (VOKTORA_LTO=yes pour l'activer) ; ccache est utilisé automatiquement par Nuitka s'il est installé

"${UV[@]}" python -m nuitka \
  --standalone --macos-create-app-bundle \
  --macos-app-name=Voktora --macos-app-version="$VERSION" \
  --macos-app-icon="$ICNS" \
  --lto="${VOKTORA_LTO:-no}" --python-flag=no_docstrings --python-flag=no_asserts \
  --noinclude-unittest-mode=nofollow --noinclude-pytest-mode=nofollow --noinclude-setuptools-mode=nofollow \
  --nofollow-import-to=tkinter,test,pydoc,doctest,lib2to3 \
  --enable-plugin=pyside6 --include-qt-plugins=iconengines,imageformats,platforms,styles,tls \
  --assume-yes-for-downloads --remove-output --disable-console \
  --jobs="$(sysctl -n hw.ncpu 2>/dev/null || echo 2)" \
  --output-dir="$DIST/nuitka_out" --output-filename=voktora \
  "$ROOT/voktora/main.py"

APP="$(find "$DIST/nuitka_out" -maxdepth 1 -name '*.app' | head -n1)"
[[ -n "$APP" ]] || { echo "Bundle .app introuvable" >&2; exit 1; }
BIN="$APP/Contents/MacOS"
cp -r "$ROOT/voktora/themes" "$BIN/themes"; cp -r "$ROOT/assets" "$BIN/assets"
cp "$ROOT/voktora/version.txt" "$BIN/version.txt"; cp "$ROOT/voktora/trusted_keys.json" "$BIN/trusted_keys.json"

STAGE="$DIST/dmg"; mkdir -p "$STAGE"; cp -R "$APP" "$STAGE/Voktora.app"; ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Voktora $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DIST/Voktora_${VERSION}_x86_64.dmg"
echo "OK : $DIST/Voktora_${VERSION}_x86_64.dmg  (non signé : clic droit > Ouvrir au premier lancement)"
