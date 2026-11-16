#!/bin/sh
# Voktora — mode LIVE (Linux / macOS) : essayer Voktora sans rien installer.
#   curl -fsSL https://raw.githubusercontent.com/yo-le-zz/Voktora/main/Installers/live/install-live.sh | sh
# Tout (code, Python, dépendances, configuration, projets créés) vit dans un dossier temporaire voktora-live-XXXXXXXX
# et est SUPPRIMÉ à la fermeture (même après Ctrl+C ou fermeture du terminal). Rien n'est écrit dans votre HOME.
# Variables : VOKTORA_LIVE_REF=<tag|branche> (défaut : dernière release, sinon main) · VOKTORA_LIVE_KEEP=1 (debug : ne rien supprimer).
set -eu

REPO="yo-le-zz/Voktora"
say() { printf '\033[1mVoktora live\033[0m  %s\n' "$*"; }
die() { printf 'Voktora live : %s\n' "$*" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || die "curl est requis."
command -v tar  >/dev/null 2>&1 || die "tar est requis."

ROOT="${TMPDIR:-/tmp}"
ROOT="${ROOT%/}"
[ -d "$ROOT" ] && [ -w "$ROOT" ] || die "dossier temporaire inutilisable : $ROOT"

# 1) Nettoie les sessions live abandonnées (script tué brutalement) dont le processus n'existe plus.
for d in "$ROOT"/voktora-live-*; do
  [ -d "$d" ] && [ ! -L "$d" ] && [ -f "$d/.voktora-live" ] || continue
  old=$(cat "$d/.pid" 2>/dev/null || echo 0)
  if [ "${old:-0}" -gt 1 ] 2>/dev/null && kill -0 "$old" 2>/dev/null; then continue; fi
  rm -rf "$d"
done

# 2) Dossier live privé + marqueur (Voktora refuse de supprimer un dossier sans ce marqueur).
LIVE=$(mktemp -d "$ROOT/voktora-live-XXXXXXXX") || die "impossible de créer le dossier temporaire."
chmod 700 "$LIVE"
: > "$LIVE/.voktora-live"
echo $$ > "$LIVE/.pid"
CHILD=""

cleanup() {
  trap - EXIT INT TERM HUP
  if [ -n "$CHILD" ] && kill -0 "$CHILD" 2>/dev/null; then kill "$CHILD" 2>/dev/null || true; sleep 1; kill -9 "$CHILD" 2>/dev/null || true; fi
  if [ "${VOKTORA_LIVE_KEEP:-0}" = "1" ]; then say "VOKTORA_LIVE_KEEP=1 : dossier conservé : $LIVE"; return; fi
  case "$LIVE" in "$ROOT"/voktora-live-*) rm -rf "$LIVE" ;; esac
  say "tout a été supprimé."
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

# 3) Version à lancer : dernière release GitHub, sinon main.
REF="${VOKTORA_LIVE_REF:-}"
if [ -z "$REF" ]; then
  REF=$(curl -fsSL --max-time 20 "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
        | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1 || true)
fi
case "$REF" in ""|*[!A-Za-z0-9._/-]*) REF="main" ;; esac
say "version : $REF"

mkdir -p "$LIVE/app" "$LIVE/cache"
URL="https://github.com/$REPO/archive/refs/tags/$REF.tar.gz"
[ "$REF" = "main" ] && URL="https://github.com/$REPO/archive/refs/heads/main.tar.gz"
say "téléchargement du code…"
if ! curl -fsSL --max-time 300 "$URL" | tar -xzf - --strip-components=1 -C "$LIVE/app"; then
  [ "$REF" != "main" ] || die "téléchargement impossible."
  say "tag introuvable, essai avec main…"
  curl -fsSL --max-time 300 "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar -xzf - --strip-components=1 -C "$LIVE/app" \
    || die "téléchargement impossible."
fi
[ -f "$LIVE/app/voktora/main.py" ] || die "archive inattendue (voktora/main.py absent)."

# 4) Python 3.13 + dépendances, tout dans le dossier live (uv, installé dans le dossier live s'il est absent).
UV=$(command -v uv 2>/dev/null || true)
if [ -z "$UV" ]; then
  say "installation temporaire de uv (supprimé à la fermeture)…"
  curl -LsSf https://astral.sh/uv/install.sh | UV_UNMANAGED_INSTALL="$LIVE/uv" sh >/dev/null 2>&1 || die "installation de uv impossible."
  UV="$LIVE/uv/uv"
fi
export UV_CACHE_DIR="$LIVE/cache/uv" UV_PYTHON_INSTALL_DIR="$LIVE/python" UV_NO_CONFIG=1 UV_PYTHON_PREFERENCE=managed
say "préparation de Python 3.13 et des dépendances (1-2 min la première fois)…"
"$UV" venv --quiet --python 3.13 "$LIVE/venv" || die "Python 3.13 indisponible."
"$UV" pip install --quiet --python "$LIVE/venv/bin/python" "pyside6>=6.5" "cryptography>=42.0" || die "installation des dépendances impossible."

# 5) Lancement (données, caches et projets dans le dossier live).
say "lancement — tout sera supprimé à la fermeture de Voktora."
VOKTORA_LIVE_DIR="$LIVE" VOKTORA_NO_NATIVE=1 PYTHONDONTWRITEBYTECODE=1 \
  XDG_CACHE_HOME="$LIVE/cache" XDG_DATA_HOME="$LIVE/xdg-data" \
  "$LIVE/venv/bin/python" "$LIVE/app/voktora/main.py" --live &
CHILD=$!
set +e
wait "$CHILD"
code=$?
CHILD=""
exit "$code"
