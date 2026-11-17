#!/bin/sh
# Voktora — installation en UNE commande (Linux : distribution détectée · macOS Intel) :
#   curl -fsSL https://raw.githubusercontent.com/yo-le-zz/Voktora/main/Installers/install.sh | sh
# Télécharge le paquet de la dernière release (.deb, .rpm, .pkg.tar.zst ou .dmg), VÉRIFIE son empreinte SHA-256 avec le
# fichier SHA256SUMS de la release, puis l'installe. Variables : VOKTORA_VERSION=1.1.6 (défaut : dernière release),
# VOKTORA_DRY_RUN=1 (affiche ce qui serait fait, sans rien télécharger ni installer).
set -eu

REPO="yo-le-zz/Voktora"
say() { printf '\033[1mVoktora\033[0m  %s\n' "$*"; }
die() { printf 'Voktora : %s\n' "$*" >&2; exit 1; }

OS="${VOKTORA_FORCE_OS:-$(uname -s)}"
ARCH="${VOKTORA_FORCE_ARCH:-$(uname -m)}"
DRY="${VOKTORA_DRY_RUN:-0}"

# --- version -------------------------------------------------------------------------------------------------------
TAG=""
VER="${VOKTORA_VERSION:-}"
if [ -n "$VER" ]; then
  VER="${VER#v}"; TAG="v$VER"
else
  command -v curl >/dev/null 2>&1 || die "curl est requis."
  TAG=$(curl -fsSL --max-time 20 "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
        | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1 || true)
  [ -n "$TAG" ] || die "impossible de déterminer la dernière version (réseau ? limite GitHub ?). Essayez VOKTORA_VERSION=x.y.z."
  VER="${TAG#v}"
fi
case "$VER" in ""|*[!0-9A-Za-z.~+-]*) die "version invalide : $VER" ;; esac

# --- choix du paquet -----------------------------------------------------------------------------------------------
KIND=""; ASSET=""; FAMILY=""
SUDO=""
if [ "$(id -u 2>/dev/null || echo 1)" != "0" ]; then SUDO="sudo"; fi

if [ "$OS" = "Darwin" ]; then
  KIND="dmg"; ASSET="Voktora_${VER}_x86_64.dmg"
  if [ "$ARCH" != "x86_64" ]; then
    say "Mac Apple Silicon ($ARCH) : seul un build Intel existe ; il ne fonctionne que si Rosetta 2 est installée."
  fi
elif [ "$OS" = "Linux" ]; then
  case "$ARCH" in x86_64|amd64) ;; *) die "architecture non prise en charge : $ARCH (seul x86_64 est publié)." ;; esac
  REL="${VOKTORA_OS_RELEASE:-/etc/os-release}"
  [ -r "$REL" ] || die "impossible de lire $REL : distribution inconnue. Voir https://voktora.pages.dev/download.html"
  # shellcheck disable=SC1090
  ID=$( . "$REL"; printf '%s' "${ID:-}" ); LIKE=$( . "$REL"; printf '%s' "${ID_LIKE:-}" )
  FAMILY=""
  for w in $ID $LIKE; do
    case "$w" in
      debian|ubuntu|linuxmint|pop|raspbian|elementary|zorin|kali|neon) FAMILY="deb"; break ;;
      fedora|rhel|centos|rocky|almalinux|ol|nobara|amzn) FAMILY="rpm"; break ;;
      opensuse*|suse|sles|sled) FAMILY="zypper"; break ;;
      arch|archarm|manjaro|endeavouros|cachyos|garuda|artix|omarchy) FAMILY="pacman"; break ;;
    esac
  done
  case "$FAMILY" in
    deb)    KIND="deb";  ASSET="voktora_${VER}_amd64.deb" ;;
    rpm)    KIND="rpm";  ASSET="voktora-${VER}-1.x86_64.rpm" ;;
    zypper) KIND="rpm";  ASSET="voktora-${VER}-1.x86_64.rpm" ;;
    pacman) KIND="arch"; ASSET="voktora-${VER}-1-x86_64.pkg.tar.zst" ;;
    *) die "distribution non reconnue (ID=$ID ID_LIKE=$LIKE). Voir https://voktora.pages.dev/download.html ou installez depuis les sources." ;;
  esac
  say "distribution : ${ID:-?} → paquet $KIND"
else
  die "système non pris en charge par ce script : $OS (Windows : install.ps1)."
fi

BASE="https://github.com/$REPO/releases/download/$TAG"
say "version $VER — $ASSET"
if [ "$DRY" = "1" ]; then
  case "$FAMILY:$KIND" in
    deb:*) CMD="$SUDO apt-get install -y ./$ASSET" ;;
    rpm:*) CMD="$SUDO dnf install -y ./$ASSET" ;;
    zypper:*) CMD="$SUDO zypper --non-interactive install --allow-unsigned-rpm ./$ASSET" ;;
    pacman:*) CMD="$SUDO pacman -U --noconfirm ./$ASSET" ;;
    *) CMD="copie de Voktora.app dans /Applications" ;;
  esac
  echo "DRY-RUN kind=$KIND asset=$ASSET url=$BASE/$ASSET"
  echo "DRY-RUN install=$(printf '%s' "$CMD" | sed 's/^ *//')"
  exit 0
fi

command -v curl >/dev/null 2>&1 || die "curl est requis."
if [ -n "$SUDO" ] && [ "$KIND" != "dmg" ]; then command -v sudo >/dev/null 2>&1 || die "sudo est requis (ou lancez ce script en root)."; fi

TMP=$(mktemp -d "${TMPDIR:-/tmp}/voktora-install.XXXXXXXX") || die "dossier temporaire impossible."
chmod 755 "$TMP"                      # lisible par apt (sandbox _apt)
trap 'rm -rf "$TMP"' EXIT INT TERM HUP
say "téléchargement…"
curl -fL --progress-bar --max-time 900 -o "$TMP/$ASSET" "$BASE/$ASSET" || die "téléchargement impossible : $BASE/$ASSET"
curl -fsSL --max-time 60 -o "$TMP/SHA256SUMS" "$BASE/SHA256SUMS" || die "SHA256SUMS introuvable : la vérification est obligatoire."

# --- vérification SHA-256 (obligatoire) ------------------------------------------------------------------------------
WANT=$(awk -v f="$ASSET" '$2==f || $2=="*"f {print $1; exit}' "$TMP/SHA256SUMS")
[ -n "$WANT" ] || die "aucune empreinte pour $ASSET dans SHA256SUMS."
if command -v sha256sum >/dev/null 2>&1; then GOT=$(sha256sum "$TMP/$ASSET" | awk '{print $1}')
elif command -v shasum >/dev/null 2>&1; then GOT=$(shasum -a 256 "$TMP/$ASSET" | awk '{print $1}')
else die "sha256sum/shasum introuvable : impossible de vérifier le fichier."; fi
[ "$WANT" = "$GOT" ] || die "EMPREINTE INCORRECTE (attendu $WANT, obtenu $GOT) : fichier refusé."
say "empreinte SHA-256 vérifiée."

# --- installation --------------------------------------------------------------------------------------------------
case "$FAMILY:$KIND" in
  deb:*)    $SUDO apt-get install -y "$TMP/$ASSET" ;;
  rpm:*)    $SUDO dnf install -y "$TMP/$ASSET" ;;
  zypper:*) $SUDO zypper --non-interactive install --allow-unsigned-rpm "$TMP/$ASSET" ;;
  pacman:*) $SUDO pacman -U --noconfirm "$TMP/$ASSET" ;;
  *)
    MNT="$TMP/mnt"; mkdir -p "$MNT"
    hdiutil attach -nobrowse -readonly -quiet -mountpoint "$MNT" "$TMP/$ASSET" || die "montage du .dmg impossible."
    rm -rf /Applications/Voktora.app 2>/dev/null || true
    cp -R "$MNT/Voktora.app" /Applications/ || { hdiutil detach -quiet "$MNT" || true; die "copie dans /Applications impossible (droits ?)."; }
    hdiutil detach -quiet "$MNT" || true
    xattr -dr com.apple.quarantine /Applications/Voktora.app 2>/dev/null || true ;;
esac
if [ "$KIND" = "dmg" ]; then say "installé : /Applications/Voktora.app (ouvrez-le depuis Launchpad)."; else say "installé. Lancez : voktora"; fi
