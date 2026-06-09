"""
build_msi.py — Voktora Windows MSI builder
Compile avec Nuitka (--onedir) puis empaquète en .msi via WiX Toolset 4.x

Arborescence attendue :
    Voktora/
    ├── assets/                  ← icônes sources
    ├── Installers/
    │   ├── MSI installer/
    │   │   ├── build_msi.py     ← CE FICHIER
    │   │   └── voktora.wxs
    │   └── DEB installer/
    │       └── build_deb.sh
    └── voktora/
        ├── main.py
        ├── themes/
        └── version.txt

Prérequis :
    pip install nuitka pyside6 cryptography
    winget install WiXToolset.WiX
    wix extension add WixToolset.UI.wixext

Usage :
    python "Installers/MSI installer/build_msi.py" [VERSION]
"""

import sys
import shutil
import subprocess
from pathlib import Path

# Ce fichier est dans  Voktora/Installers/MSI installer/
ROOT    = Path(__file__).resolve().parent.parent.parent
VERSION = sys.argv[1] if len(sys.argv) > 1 else (ROOT / "voktora" / "version.txt").read_text().strip()
DIST    = ROOT / "dist" / "windows"

# Nuitka nomme le dossier d'après le fichier source (main.py → main.dist),
# indépendamment de --output-filename.
ONEDIR  = DIST / "main.dist"

WXS_DIR = ROOT / "Installers" / "MSI installer"


def run(cmd, **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True, **kw)


def main():
    print("=== Voktora MSI builder ===")
    print(f"Version : {VERSION}")
    print(f"Root    : {ROOT}")

    # ── 1. Nettoyage ──────────────────────────────────────────────────────────
    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir(parents=True)

    # ── 2. Compilation Nuitka --onedir ────────────────────────────────────────
    print("\n>>> Compilation Nuitka...")
    run([
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--remove-output",
        "--enable-plugin=pyside6",
        "--assume-yes-for-downloads",           # CI : accepte Dependency Walker etc.
        f"--windows-icon-from-ico={ROOT / 'assets' / 'Voktora.ico'}",
        "--windows-console-mode=disable",
        f"--output-dir={DIST}",
        "--output-filename=voktora",
        ROOT / "voktora" / "main.py",
    ])

    # Nuitka crée main.dist/ (nom du .py source).
    # On le renomme en voktora.dist/ pour la cohérence.
    final_onedir = DIST / "voktora.dist"
    if ONEDIR.exists():
        ONEDIR.rename(final_onedir)
    ONEDIR_FINAL = final_onedir

    # Copier ressources dans le onedir
    shutil.copytree(ROOT / "voktora" / "themes", ONEDIR_FINAL / "themes", dirs_exist_ok=True)
    shutil.copytree(ROOT / "assets",             ONEDIR_FINAL / "assets",  dirs_exist_ok=True)
    shutil.copy(ROOT / "voktora" / "version.txt", ONEDIR_FINAL / "version.txt")

    # ── 3. Build MSI (WiX 4 — HarvestDirectory dans le .wxs) ─────────────────
    # Pas de `wix harvest` : WiX 4 utilise HarvestDirectory directement dans
    # voktora.wxs, piloté par la variable SourceDir.
    print("\n>>> Build MSI (wix build)...")
    msi_out = DIST / f"Voktora_{VERSION}_x64.msi"
    run([
        "wix", "build",
        str(WXS_DIR / "voktora.wxs"),
        "-d", f"VERSION={VERSION}",
        "-d", f"SourceDir={ONEDIR_FINAL}",
        "-ext", "WixToolset.UI.wixext",
        "-o", str(msi_out),
    ])

    print(f"\n=== Succès ===")
    print(f"MSI : {msi_out}")
    size_mb = msi_out.stat().st_size / 1_048_576
    print(f"Taille : {size_mb:.1f} MB")


if __name__ == "__main__":
    main()