"""
Voktora — update_install (1.1.3) : installe une mise à jour déjà téléchargée ET vérifiée (self_update.download).

Voktora ne peut pas remplacer son propre programme en marche. Il écrit donc un petit script autonome, le lance
détaché, puis se ferme. Le script :
  1. contrôle l'architecture du fichier (x86_64 / aarch64…) et la présence de l'outil d'installation ;
  2. arrête Voktora (TERM, puis KILL au bout de 10 s) ;
  3. installe (dnf/yum/zypper/rpm, apt-get/dpkg, pacman, AppImage, tar.gz — ou msiexec/PowerShell, hdiutil), 2 essais,
     avec élévation par pkexec ou sudo -n si nécessaire ;
  4. rouvre Voktora (la nouvelle version, ou l'ancienne si l'installation a échoué) ;
  5. journalise tout dans `<données>/updates/update.log` et affiche le résultat (notify-send / zenity / msg).

Le texte du script est produit par des fonctions pures (testables sans rien installer) ; `VOKTORA_UPDATE_DRYRUN=1`
fait simplement afficher les commandes au lieu de les exécuter.
"""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ARCH_ALIASES = {
    "x86_64": ("x86_64", "amd64", "x64"),
    "aarch64": ("aarch64", "arm64"),
    "armv7l": ("armv7l", "armhf", "armv7"),
    "i686": ("i686", "i386"),
}


class InstallError(RuntimeError):
    pass


def machine_arch() -> str:
    """Architecture normalisée de cette machine (x86_64, aarch64…)."""
    raw = platform.machine().lower()
    for canon, names in ARCH_ALIASES.items():
        if raw == canon or raw in names:
            return canon
    return raw or "x86_64"


def file_arch(name: str) -> str | None:
    """Architecture annoncée dans un nom de fichier (« …-aarch64.rpm » → aarch64), None si non précisée."""
    low = name.lower()
    for canon, names in ARCH_ALIASES.items():
        for alias in names:
            if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", low):
                return canon
    return None


def arch_matches(name: str, arch: str | None = None) -> bool:
    found = file_arch(name)
    return found is None or found == (arch or machine_arch())


def distro_family() -> str:
    """fedora / debian / arch / suse / other (d'après /etc/os-release)."""
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return "other"
    ids = " ".join(line.split("=", 1)[1].strip('"') for line in text.splitlines()
                   if line.startswith(("id=", "id_like=")))
    for family, words in (("arch", ("arch", "manjaro", "endeavouros")), ("debian", ("debian", "ubuntu", "mint")),
                          ("suse", ("suse",)), ("fedora", ("fedora", "rhel", "centos", "rocky", "alma"))):
        if any(w in ids.split() or w in ids for w in words):
            return family
    return "other"


def kind_of(name: str) -> str:
    low = name.lower()
    for suffix, kind in ((".rpm", "rpm"), (".deb", "deb"), (".pkg.tar.zst", "pacman"), (".pkg.tar.xz", "pacman"),
                         (".appimage", "appimage"), (".tar.gz", "tar"), (".tgz", "tar"), (".msi", "msi"),
                         (".exe", "exe"), (".dmg", "dmg")):
        if low.endswith(suffix):
            return kind
    raise InstallError(f"Type de fichier non géré : {name}")


def preferred_kinds(system: str | None = None, family: str | None = None) -> list[str]:
    system = system or sys.platform
    if system == "win32":
        return ["msi", "exe"]
    if system == "darwin":
        return ["dmg"]
    order = {"fedora": ["rpm"], "suse": ["rpm"], "debian": ["deb"], "arch": ["pacman"]}.get(family or distro_family(), [])
    return [*order, "appimage", "tar"]


def relaunch_command() -> list[str]:
    """Commande qui rouvre Voktora après l'installation."""
    exe = Path(sys.argv[0] if sys.argv and sys.argv[0] else sys.executable)
    if getattr(sys, "frozen", False) or "__compiled__" in globals() or exe.name.lower().startswith("voktora"):
        return [str(exe.resolve())]
    return [shutil.which("voktora") or sys.executable, *([] if shutil.which("voktora") else [str(exe.resolve())])]


# ── génération des scripts ───────────────────────────────────────────────────────

def _q(value: str | Path) -> str:
    return shlex.quote(str(value))


SH_HEAD = r"""#!/bin/sh
# Script généré par Voktora {version} — installe la mise à jour puis rouvre Voktora. Ne rien modifier ici.
LOG={log}
PID={pid}
FILE={file}
KIND={kind}
ARCH_WANTED={arch}
RELAUNCH={relaunch}
DRY="${{VOKTORA_UPDATE_DRYRUN:-}}"
mkdir -p "$(dirname "$LOG")" 2>/dev/null
log() {{ printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; [ -n "$DRY" ] && printf '%s\n' "$*"; }}
tell() {{
  if command -v notify-send >/dev/null 2>&1; then notify-send "Voktora" "$1" >/dev/null 2>&1
  elif command -v zenity >/dev/null 2>&1; then zenity --info --title=Voktora --text="$1" >/dev/null 2>&1 &
  fi
}}
relaunch() {{
  [ -n "$DRY" ] && {{ log "relance : $RELAUNCH"; return 0; }}
  nohup setsid sh -c "$RELAUNCH" >/dev/null 2>&1 &
}}
fail() {{ log "ÉCHEC : $*"; tell "Mise à jour échouée : $*  (journal : $LOG)"; relaunch; exit 1; }}
run() {{ log "+ $*"; [ -n "$DRY" ] && return 0; "$@" >>"$LOG" 2>&1; }}
need() {{ command -v "$1" >/dev/null 2>&1 || [ -n "$DRY" ] || fail "outil manquant : $1 ($2)"; }}
asroot() {{
  if [ "$(id -u)" = "0" ]; then run "$@"
  elif command -v pkexec >/dev/null 2>&1; then run pkexec "$@"
  elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then run sudo -n "$@"
  else fail "droits administrateur requis : lancez  sudo $*"
  fi
}}
retry() {{ "$@" && return 0; log "nouvel essai dans 3 s"; sleep 3; "$@"; }}

log "=== mise à jour : $FILE ($KIND, $ARCH_WANTED) ==="
[ -f "$FILE" ] || [ -n "$DRY" ] || fail "fichier introuvable : $FILE"
ARCH_NOW="$(uname -m)"
case "$ARCH_NOW" in amd64|x64) ARCH_NOW=x86_64;; arm64) ARCH_NOW=aarch64;; esac
if [ -n "$ARCH_WANTED" ] && [ "$ARCH_WANTED" != "$ARCH_NOW" ]; then
  fail "ce fichier est pour $ARCH_WANTED mais votre machine est $ARCH_NOW"
fi

# 1. arrêter Voktora
if [ "${{PID:-0}}" -gt 1 ] 2>/dev/null && kill -0 "$PID" 2>/dev/null; then
  log "arrêt de Voktora (pid $PID)"
  [ -n "$DRY" ] || kill -TERM "$PID" 2>/dev/null
  i=0
  while kill -0 "$PID" 2>/dev/null && [ $i -lt 20 ]; do sleep 0.5; i=$((i+1)); done
  if kill -0 "$PID" 2>/dev/null; then log "toujours actif : KILL"; [ -n "$DRY" ] || kill -KILL "$PID" 2>/dev/null; sleep 1; fi
fi

# 2. installer
"""

SH_KINDS = {
    "rpm": r"""if command -v dnf >/dev/null 2>&1; then asroot_cmd="dnf install -y"
elif command -v zypper >/dev/null 2>&1; then asroot_cmd="zypper --non-interactive --no-gpg-checks install"
elif command -v yum >/dev/null 2>&1; then asroot_cmd="yum install -y"
elif command -v rpm >/dev/null 2>&1; then asroot_cmd="rpm -Uvh"
elif [ -n "$DRY" ]; then asroot_cmd="dnf install -y"
else fail "aucun gestionnaire RPM (dnf, zypper, yum, rpm)"; fi
retry asroot $asroot_cmd "$FILE" || fail "l'installation du paquet RPM a échoué"
""",
    "deb": r"""if command -v apt-get >/dev/null 2>&1; then retry asroot apt-get install -y "$FILE" || fail "apt-get a échoué"
elif command -v dpkg >/dev/null 2>&1; then retry asroot dpkg -i "$FILE" || fail "dpkg a échoué"
elif [ -n "$DRY" ]; then log "+ apt-get install -y $FILE"
else fail "ni apt-get ni dpkg"; fi
""",
    "pacman": r"""need pacman "Arch Linux"
retry asroot pacman -U --noconfirm "$FILE" || fail "pacman a échoué"
""",
    "appimage": r"""TARGET="${APPIMAGE:-$HOME/.local/bin/Voktora.AppImage}"
log "AppImage → $TARGET"
if [ -z "$DRY" ]; then
  mkdir -p "$(dirname "$TARGET")" || fail "dossier inaccessible : $(dirname "$TARGET")"
  cp "$FILE" "$TARGET.new" && chmod +x "$TARGET.new" && mv -f "$TARGET.new" "$TARGET" || fail "copie de l'AppImage impossible"
fi
RELAUNCH="$TARGET"
""",
    "tar": r"""need tar "tar"
DEST="${VOKTORA_INSTALL_DIR:-$HOME/.local/opt/voktora}"
log "archive → $DEST"
if [ -z "$DRY" ]; then
  mkdir -p "$DEST.new" && tar -xzf "$FILE" -C "$DEST.new" --strip-components=1 2>>"$LOG" || fail "extraction impossible"
  rm -rf "$DEST.old"; [ -d "$DEST" ] && mv "$DEST" "$DEST.old"; mv "$DEST.new" "$DEST" || fail "remplacement impossible"
fi
""",
    "dmg": r"""need hdiutil "macOS"
MNT="$(mktemp -d)"
run hdiutil attach -nobrowse -quiet -mountpoint "$MNT" "$FILE" || fail "montage du .dmg impossible"
APP="$(ls -d "$MNT"/*.app 2>/dev/null | head -n 1)"
[ -n "$APP" ] || { run hdiutil detach "$MNT"; fail "aucune application dans le .dmg"; }
run rm -rf /Applications/Voktora.app
run cp -R "$APP" /Applications/Voktora.app || { run hdiutil detach "$MNT"; fail "copie vers /Applications impossible"; }
run hdiutil detach "$MNT"
RELAUNCH="open /Applications/Voktora.app"
""",
}

SH_TAIL = r"""
log "installation terminée"
tell "Voktora est à jour."
relaunch
exit 0
"""


def build_sh(file: Path, kind: str, pid: int, log: Path, relaunch: list[str], arch: str | None = None,
             version: str = "") -> str:
    if kind not in SH_KINDS:
        raise InstallError(f"Pas d'installation shell pour « {kind} ».")
    head = SH_HEAD.format(version=version, log=_q(log), pid=_q(str(pid)), file=_q(file), kind=_q(kind),
                          arch=_q(file_arch(file.name) or arch or ""), relaunch=_q(shlex.join(relaunch)))
    return head + SH_KINDS[kind] + SH_TAIL


PS1 = r"""# Script généré par Voktora {version}. Installe la mise à jour puis rouvre Voktora.
$ErrorActionPreference = 'Stop'
$Log = {log}
$File = {file}
$Kind = {kind}
$Pid_ = {pid}
$Relaunch = {relaunch}
function Log($m) {{ Add-Content -Path $Log -Value ("{{0}} {{1}}" -f (Get-Date -Format 's'), $m) }}
function Fail($m) {{
  Log "ECHEC : $m"
  try {{ msg * "Mise a jour de Voktora echouee : $m (journal : $Log)" }} catch {{}}
  if (Test-Path $Relaunch) {{ Start-Process $Relaunch }}
  exit 1
}}
try {{
  Log "=== mise a jour : $File ($Kind) ==="
  if (-not (Test-Path $File)) {{ Fail "fichier introuvable" }}
  $arch = $env:PROCESSOR_ARCHITECTURE
  if ($File -match 'arm64|aarch64' -and $arch -ne 'ARM64') {{ Fail "fichier ARM64 sur une machine $arch" }}
  if ($File -match 'x64|amd64|x86_64' -and $arch -eq 'ARM64') {{ Log "x64 sous ARM64 : emulation" }}
  $p = Get-Process -Id $Pid_ -ErrorAction SilentlyContinue
  if ($p) {{ Log "arret de Voktora"; Stop-Process -Id $Pid_ -Force; Start-Sleep -Seconds 2 }}
  for ($i = 1; $i -le 2; $i++) {{
    if ($Kind -eq 'msi') {{ $r = Start-Process msiexec -ArgumentList @('/i', "`"$File`"", '/passive', '/norestart') -Wait -PassThru -Verb RunAs }}
    else {{ $r = Start-Process $File -ArgumentList '/S' -Wait -PassThru -Verb RunAs }}
    if ($r.ExitCode -eq 0 -or $r.ExitCode -eq 3010) {{ break }}
    Log "code de sortie $($r.ExitCode) (essai $i)"
    if ($i -eq 2) {{ Fail "installation refusee ou echouee (code $($r.ExitCode))" }}
    Start-Sleep -Seconds 3
  }}
  Log "installation terminee"
  if (Test-Path $Relaunch) {{ Start-Process $Relaunch }}
}} catch {{ Fail $_.Exception.Message }}
"""


def _ps(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def build_ps1(file: Path, kind: str, pid: int, log: Path, relaunch: str, version: str = "") -> str:
    return PS1.format(version=version, log=_ps(log), file=_ps(file), kind=_ps(kind), pid=int(pid), relaunch=_ps(relaunch))


# ── lancement ────────────────────────────────────────────────────────────────────

def prepare(file: Path, log_dir: Path, version: str = "", pid: int | None = None) -> Path:
    """Écrit le script d'installation adapté à `file` et renvoie son chemin (rien n'est exécuté)."""
    file = Path(file).resolve()
    if not file.is_file():
        raise InstallError(f"Fichier introuvable : {file}")
    if not arch_matches(file.name):
        raise InstallError(f"Ce fichier est pour {file_arch(file.name)}, votre machine est {machine_arch()}.")
    kind = kind_of(file.name)
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / "update.log"
    pid = os.getpid() if pid is None else pid
    if kind in ("msi", "exe"):
        script = log_dir / "voktora-update.ps1"
        script.write_text(build_ps1(file, kind, pid, log, relaunch_command()[0], version), encoding="utf-8-sig")
    else:
        script = log_dir / "voktora-update.sh"
        script.write_text(build_sh(file, kind, pid, log, relaunch_command(), machine_arch(), version), encoding="utf-8")
        script.chmod(0o700)
    return script


def launch(script: Path) -> None:
    """Lance le script détaché (il survit à la fermeture de Voktora)."""
    if script.suffix == ".ps1":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],  # noqa: S603, S607
                         creationflags=flags, close_fds=True)
    else:
        subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, close_fds=True,  # noqa: S603
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
