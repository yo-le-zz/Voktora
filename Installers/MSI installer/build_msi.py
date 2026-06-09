"""
build_msi.py — Voktora Windows MSI builder
Compile avec Nuitka (--onedir) puis empaquète en .msi via WiX Toolset 4.x

Prérequis :
    pip install nuitka pyside6 cryptography
    winget install WiXToolset.WiX  (ou via MSI sur wixtoolset.org)

Usage :
    python packaging/build_msi.py [VERSION]
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent
VERSION = sys.argv[1] if len(sys.argv) > 1 else (ROOT / "voktora" / "version.txt").read_text().strip()
DIST    = ROOT / "dist" / "windows"
ONEDIR  = DIST / "voktora.dist"


def run(cmd, **kw):
    print(f"  $ {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    subprocess.run(cmd, check=True, **kw)


def main():
    print("=== Voktora MSI builder ===")
    print(f"Version : {VERSION}")

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
        f"--windows-icon-from-ico={str(ROOT / 'assets' / 'Voktora.ico')}",
        "--windows-console-mode=disable",
        f"--output-dir={DIST}",
        "--output-filename=voktora",
        str(ROOT / "voktora" / "main.py"),
    ])

    # Copier ressources dans le onedir
    shutil.copytree(ROOT / "voktora" / "themes", ONEDIR / "themes", dirs_exist_ok=True)
    shutil.copytree(ROOT / "assets",          ONEDIR / "assets",  dirs_exist_ok=True)
    shutil.copy(ROOT / "voktora" / "version.txt", ONEDIR / "version.txt")

    # ── 3. Harvest des fichiers pour WiX ──────────────────────────────────────
    print("\n>>> Génération voktora_files.wxs (wix harvest)...")
    # WiX 4.x : wix extension add WixToolset.UI.wixext
    # puis wix harvest directory  (remplace heat.exe de WiX 3.x)
    harvest_out = ROOT / "packaging" / "voktora_files.wxs"
    try:
        run([
            "wix", "harvest", "directory",
            str(ONEDIR),
            "-cg", "VoktoraFiles",
            "-dr", "VOKTORA_DIR",
            "-var", "var.SourceDir",
            "-gg", "-scom", "-sreg",
            "-o", str(harvest_out),
        ])
    except FileNotFoundError:
        # Fallback heat.exe (WiX 3.x)
        run([
            "heat.exe", "dir", str(ONEDIR),
            "-cg", "VoktoraFiles",
            "-dr", "VOKTORA_DIR",
            "-var", "var.SourceDir",
            "-gg", "-scom", "-sreg",
            "-o", str(harvest_out),
        ])

    # ── 4. Build MSI ──────────────────────────────────────────────────────────
    print("\n>>> Build MSI (wix build)...")
    msi_out = DIST / f"Voktora_{VERSION}_x64.msi"
    try:
        run([
            "wix", "build",
            str(ROOT / "packaging" / "voktora.wxs"),
            "-d", f"VERSION={VERSION}",
            "-d", f"SourceDir={ONEDIR}",
            "-ext", "WixToolset.UI.wixext",
            "-o", str(msi_out),
        ])
    except FileNotFoundError:
        # Fallback WiX 3.x candle + light
        wixobj = DIST / "voktora.wixobj"
        run(["candle.exe",
             f"-dVERSION={VERSION}",
             f"-dSourceDir={ONEDIR}",
             str(ROOT / "packaging" / "voktora.wxs"),
             str(harvest_out),
             "-o", str(wixobj)])
        run(["light.exe", str(wixobj),
             "-ext", "WixUIExtension",
             "-o", str(msi_out)])

    print(f"\n=== Succès ===")
    print(f"MSI : {msi_out}")
    size_mb = msi_out.stat().st_size / 1_048_576
    print(f"Taille : {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
