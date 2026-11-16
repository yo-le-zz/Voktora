#!/usr/bin/env bash
# Voktora — make_icns.sh : convertit assets/Voktora.png en .icns avec les outils de macOS (sips + iconutil).
# Évite la dépendance « imageio » que Nuitka exige pour convertir un PNG. Usage : make_icns.sh SORTIE.icns [source.png]
set -euo pipefail
OUT="$1"
SRC="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/assets/Voktora.png}"
SET="$(mktemp -d)/Voktora.iconset"; mkdir -p "$SET"
for s in 16 32 64 128 256 512; do
  sips -z "$s" "$s" "$SRC" --out "$SET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); sips -z "$d" "$d" "$SRC" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o "$OUT"
rm -rf "$(dirname "$SET")"
