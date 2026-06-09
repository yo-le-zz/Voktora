"""
build_msi.py — Voktora Windows MSI builder
Compile avec Nuitka (--onedir) puis empaquète en .msi via WiX Toolset 4.x

Arborescence attendue :
    Voktora/
    ├── assets/
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
    wix extension add --global WixToolset.UI.wixext/4.0.6

Usage :
    python "Installers/MSI installer/build_msi.py" [VERSION]
"""

import sys
import uuid
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

# Ce fichier est dans  Voktora/Installers/MSI installer/
ROOT    = Path(__file__).resolve().parent.parent.parent
VERSION = sys.argv[1] if len(sys.argv) > 1 else (ROOT / "voktora" / "version.txt").read_text().strip()
DIST    = ROOT / "dist" / "windows"

# Nuitka nomme le dossier d'après le fichier source (main.py → main.dist)
ONEDIR  = DIST / "main.dist"

WXS_DIR = ROOT / "Installers" / "MSI installer"


def run(cmd, **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True, **kw)


def generate_files_wxs(onedir: Path, out: Path) -> None:
    """
    Génère voktora_files.wxs en parcourant le onedir avec os.walk.
    Remplace complètement wix harvest / heat.exe.
    voktora.exe est exclu (déjà déclaré dans voktora.wxs).
    """
    print(f"\n>>> Génération {out.name} ({onedir})...")

    WIX = "http://wixtoolset.org/schemas/v4/wxs"
    ET.register_namespace("", WIX)

    wix_el  = ET.Element(f"{{{WIX}}}Wix")
    frag    = ET.SubElement(wix_el, f"{{{WIX}}}Fragment")
    cg      = ET.SubElement(frag,   f"{{{WIX}}}ComponentGroup",
                            Id="VoktoraFiles", Directory="VOKTORA_DIR")

    dir_refs: dict[Path, str] = {}   # path → DirectoryRef Id

    def dir_id(p: Path) -> str:
        if p not in dir_refs:
            rel = p.relative_to(onedir)
            safe = str(rel).replace("\\", "_").replace("/", "_").replace(" ", "_").replace("-", "_")
            dir_refs[p] = f"dir_{safe}"
        return dir_refs[p]

    # Déclarer les sous-répertoires
    dir_frag = ET.SubElement(frag, f"{{{WIX}}}Fragment")
    std_dir  = ET.SubElement(dir_frag, f"{{{WIX}}}StandardDirectory", Id="ProgramFiles64Folder")
    root_dir = ET.SubElement(std_dir,  f"{{{WIX}}}Directory", Id="VOKTORA_DIR", Name="Voktora")

    created_dirs: set[Path] = set()

    def ensure_dir(p: Path):
        if p == onedir or p in created_dirs:
            return
        ensure_dir(p.parent)
        parent_el = root_dir if p.parent == onedir else _dir_elements[p.parent]
        el = ET.SubElement(parent_el, f"{{{WIX}}}Directory",
                           Id=dir_id(p), Name=p.name)
        _dir_elements[p] = el
        created_dirs.add(p)

    _dir_elements: dict[Path, ET.Element] = {onedir: root_dir}

    # Ajouter les fichiers
    file_counter = 0
    for src in sorted(onedir.rglob("*")):
        if not src.is_file():
            continue
        if src.name.lower() == "voktora.exe":
            continue          # déjà dans MainExecutable

        ensure_dir(src.parent)
        file_counter += 1
        fid  = f"f{file_counter:05d}"
        cid  = f"c{file_counter:05d}"
        dref = "VOKTORA_DIR" if src.parent == onedir else dir_id(src.parent)

        comp = ET.SubElement(cg, f"{{{WIX}}}Component",
                             Id=cid,
                             Guid=str(uuid.uuid4()).upper(),
                             Directory=dref)
        ET.SubElement(comp, f"{{{WIX}}}File",
                      Id=fid,
                      Source=str(src),
                      Name=src.name,
                      KeyPath="yes")

    tree = ET.ElementTree(wix_el)
    ET.indent(tree, space="  ")
    out.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n' +
                    ET.tostring(wix_el, encoding="unicode").encode("utf-8"))
    print(f"    {file_counter} fichiers indexés → {out}")


def main():
    print("=== Voktora MSI builder ===")
    print(f"Version : {VERSION}")
    print(f"Root    : {ROOT}")

    # ── 1. Nettoyage ──────────────────────────────────────────────────────────
    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir(parents=True)

    # ── 2. Compilation Nuitka ─────────────────────────────────────────────────
    print("\n>>> Compilation Nuitka...")
    run([
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--remove-output",
        "--enable-plugin=pyside6",
        "--assume-yes-for-downloads",
        f"--windows-icon-from-ico={ROOT / 'assets' / 'Voktora.ico'}",
        "--windows-console-mode=disable",
        f"--output-dir={DIST}",
        "--output-filename=voktora",
        ROOT / "voktora" / "main.py",
    ])

    # Nuitka crée main.dist/ → renommer en voktora.dist/
    onedir_final = DIST / "voktora.dist"
    if ONEDIR.exists():
        ONEDIR.rename(onedir_final)

    # Copier ressources
    shutil.copytree(ROOT / "voktora" / "themes", onedir_final / "themes", dirs_exist_ok=True)
    shutil.copytree(ROOT / "assets",             onedir_final / "assets",  dirs_exist_ok=True)
    shutil.copy(ROOT / "voktora" / "version.txt", onedir_final / "version.txt")

    # ── 3. Générer voktora_files.wxs (pur Python, sans wix harvest) ──────────
    harvest_out = WXS_DIR / "voktora_files.wxs"
    generate_files_wxs(onedir_final, harvest_out)

    # ── 4. Build MSI ──────────────────────────────────────────────────────────
    print("\n>>> Build MSI (wix build)...")
    msi_out = DIST / f"Voktora_{VERSION}_x64.msi"
    run([
        "wix", "build",
        str(WXS_DIR / "voktora.wxs"),
        str(harvest_out),
        "-d", f"VERSION={VERSION}",
        "-d", f"SourceDir={onedir_final}",
        "-ext", "WixToolset.UI.wixext",
        "-o", str(msi_out),
    ])

    print(f"\n=== Succès ===")
    print(f"MSI : {msi_out}")
    print(f"Taille : {msi_out.stat().st_size / 1_048_576:.1f} MB")


if __name__ == "__main__":
    main()