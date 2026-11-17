#!/usr/bin/env bash
# Voktora — build.sh : compilation LOCALE rapide (Linux ou macOS).
#   ./build.sh            compile en mode rapide (sans LTO, ccache si présent) dans dist/local/ puis affiche comment lancer
#   ./build.sh run        compile (si besoin) puis lance
#   ./build.sh release    comme la CI : LTO activé (plus lent, un peu plus rapide à l'exécution)
#   ./build.sh clean      supprime dist/local
#   ./build.sh dev        pas de compilation : lance directement les sources (uv run), le plus rapide pour tester
# Recompiler seulement après un changement : les 2e compilations sont bien plus rapides grâce à ccache et au cache de Nuitka.
# Variables : VOKTORA_JOBS (défaut : nombre de CPU), VOKTORA_LTO=yes|no
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$ROOT"
MODE="${1:-fast}"; OUT="$ROOT/dist/local"
command -v uv >/dev/null || { echo "uv introuvable : curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; exit 1; }

case "$MODE" in
  clean) rm -rf "$OUT"; echo "dist/local supprimé"; exit 0 ;;
  dev)   exec uv run --project "$ROOT" python voktora/main.py "${@:2}" ;;
  fast|run|release) ;;
  *) sed -n 2,9p "$0"; exit 2 ;;
esac

JOBS="${VOKTORA_JOBS:-$( (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2) )}"
LTO="${VOKTORA_LTO:-$([[ $MODE == release ]] && echo yes || echo no)}"
OS="$(uname -s)"
command -v ccache >/dev/null || echo "(astuce : installez ccache — dnf/apt/brew install ccache — pour des recompilations 3 à 10 fois plus rapides)"

ICON=(); PLAT=()
# Familles de plugins Qt : « styles » n'existe que sous macOS/Windows ; sous Linux, Nuitka refuse ce nom.
QT_PLUGINS="iconengines,imageformats,platforms,platformthemes,tls,xcbglintegrations"
if [[ "$OS" == Darwin ]]; then
  QT_PLUGINS="iconengines,imageformats,platforms,styles,tls"
  mkdir -p "$OUT"; bash "$ROOT/Installers/macOS installer/make_icns.sh" "$OUT/Voktora.icns"
  ICON=(--macos-app-icon="$OUT/Voktora.icns"); PLAT=(--macos-create-app-bundle --macos-app-name=Voktora)
fi

mkdir -p "$OUT"
echo ">>> Nuitka ($MODE, LTO=$LTO, $JOBS tâches)"
uv run --project "$ROOT" --group build python -m nuitka \
  --standalone ${PLAT[@]+"${PLAT[@]}"} ${ICON[@]+"${ICON[@]}"} \
  --lto="$LTO" --jobs="$JOBS" \
  --python-flag=no_docstrings --python-flag=no_asserts \
  --noinclude-unittest-mode=nofollow --noinclude-pytest-mode=nofollow --noinclude-setuptools-mode=nofollow \
  --nofollow-import-to=tkinter,test,pydoc,doctest,lib2to3 \
  --enable-plugin=pyside6 --include-qt-plugins="$QT_PLUGINS" \
  --assume-yes-for-downloads --output-dir="$OUT/nuitka" --output-filename=voktora \
  voktora/main.py

if [[ "$OS" == Darwin ]]; then BIN_DIR="$(find "$OUT/nuitka" -maxdepth 1 -name '*.app' | head -n1)/Contents/MacOS"; RUN="open \"${BIN_DIR%/Contents/MacOS}\""
else BIN_DIR="$OUT/nuitka/main.dist"; RUN="\"$BIN_DIR/voktora\""; fi
cp -r voktora/themes "$BIN_DIR/themes"; cp -r assets "$BIN_DIR/assets"
cp voktora/version.txt voktora/trusted_keys.json "$BIN_DIR/"
echo ">>> OK : $BIN_DIR"; echo ">>> Lancer : $RUN"
[[ "$MODE" == run ]] && eval "$RUN"
exit 0
