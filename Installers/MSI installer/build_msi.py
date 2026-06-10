"""
build_msi.py - Voktora Windows MSI builder
Compile avec Nuitka (--onedir) puis empaquete en .msi via WiX Toolset 4.x

Arborescence attendue :
    Voktora/
    +-assets/
    +-Installers/
    |  +-MSI installer/
    |  |  +-build_msi.py     <- CE FICHIER
    |  |  +-voktora.wxs
    |  +-DEB installer/
    |     +-build_deb.sh
    +-voktora/
       +-main.py
       +-themes/
       +-version.txt

Prerequis :
    pip install nuitka pyside6 cryptography
    winget install WiXToolset.WiX
    wix extension add --global WixToolset.UI.wixext/4.0.6

Usage :
    python "Installers/MSI installer/build_msi.py" [VERSION]
"""

import sys
import io
import uuid
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

# Force UTF-8 sur stdout/stderr (Windows utilise cp1252 par defaut)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ce fichier est dans  Voktora/Installers/MSI installer/
ROOT    = Path(__file__).resolve().parent.parent.parent
VERSION = sys.argv[1] if len(sys.argv) > 1 else (ROOT / "voktora" / "version.txt").read_text().strip()
DIST    = ROOT / "dist" / "windows"

# Nuitka nomme le dossier d'apres le fichier source (main.py -> main.dist)
ONEDIR  = DIST / "main.dist"

WXS_DIR = ROOT / "Installers" / "MSI installer"


def run(cmd, **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True, **kw)


def generate_files_wxs(onedir: Path, out: Path) -> None:
    """
    Genere voktora_files.wxs en parcourant le onedir avec rglob.
    Remplace wix harvest / heat.exe.
    voktora.exe est exclu (deja dans MainExecutable de voktora.wxs).

    Structure produite (fichier include WiX 4) :
      <Include>
        <Fragment>
          <DirectoryRef Id="VOKTORA_DIR">
            <Directory Id="dir_foo" Name="foo"> ... </Directory>
          </DirectoryRef>
        </Fragment>
        <Fragment>
          <ComponentGroup Id="VoktoraFiles">
            <Component ...> <File .../> </Component>
            ...
          </ComponentGroup>
        </Fragment>
      </Include>
    """
    print(f"\n>>> Generation {out.name} ({onedir})...")

    WIX = "http://wixtoolset.org/schemas/v4/wxs"
    ET.register_namespace("", WIX)

    # Racine obligatoire pour un fichier include WiX 4 : <Include>
    root_el = ET.Element(f"{{{WIX}}}Include")

    # -- Fragment 1 : arborescence des sous-repertoires -----------------------
    dir_frag = ET.SubElement(root_el, f"{{{WIX}}}Fragment")
    dir_ref  = ET.SubElement(dir_frag, f"{{{WIX}}}DirectoryRef", Id="VOKTORA_DIR")

    dir_elements: dict = {onedir: dir_ref}
    dir_ids:      dict = {}

    def dir_id(p: Path) -> str:
        if p not in dir_ids:
            rel  = p.relative_to(onedir)
            safe = str(rel).replace("\\", "_").replace("/", "_") \
                           .replace(" ", "_").replace("-", "_").replace(".", "_")
            dir_ids[p] = f"dir_{safe}"
        return dir_ids[p]

    def ensure_dir(p: Path) -> None:
        if p in dir_elements:
            return
        ensure_dir(p.parent)
        parent_el = dir_elements[p.parent]
        el = ET.SubElement(parent_el, f"{{{WIX}}}Directory",
                           Id=dir_id(p), Name=p.name)
        dir_elements[p] = el

    for d in sorted(p for p in onedir.rglob("*") if p.is_dir()):
        ensure_dir(d)

    # -- Fragment 2 : ComponentGroup avec tous les fichiers -------------------
    file_frag = ET.SubElement(root_el, f"{{{WIX}}}Fragment")
    cg        = ET.SubElement(file_frag, f"{{{WIX}}}ComponentGroup",
                              Id="VoktoraFiles", Directory="VOKTORA_DIR")

    file_counter = 0
    for src in sorted(onedir.rglob("*")):
        if not src.is_file():
            continue
        if src.name.lower() == "voktora.exe":
            continue  # deja dans MainExecutable

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

    ET.indent(ET.ElementTree(root_el), space="  ")
    out.write_bytes(
        b'<?xml version="1.0" encoding="UTF-8"?>\n' +
        ET.tostring(root_el, encoding="unicode").encode("utf-8")
    )
    print(f"    {file_counter} fichiers indexes -> {out}")


def main():
    print("=== Voktora MSI builder ===")
    print(f"Version : {VERSION}")
    print(f"Root    : {ROOT}")

    # -- 1. Nettoyage ----------------------------------------------------------
    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir(parents=True)

    # -- 2. Compilation Nuitka ------------------------------------------------
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

    # Nuitka cree main.dist/ -> renommer en voktora.dist/
    onedir_final = DIST / "voktora.dist"
    if ONEDIR.exists():
        ONEDIR.rename(onedir_final)

    # Copier ressources
    shutil.copytree(ROOT / "voktora" / "themes", onedir_final / "themes", dirs_exist_ok=True)
    shutil.copytree(ROOT / "assets",             onedir_final / "assets",  dirs_exist_ok=True)
    shutil.copy(ROOT / "voktora" / "version.txt", onedir_final / "version.txt")

    # -- 3. Generer voktora_files.wxs (pur Python, sans wix harvest) ----------
    harvest_out = WXS_DIR / "voktora_files.wxs"
    generate_files_wxs(onedir_final, harvest_out)

    # -- 4. Build MSI ---------------------------------------------------------
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

    print(f"\n=== Succes ===")
    print(f"MSI : {msi_out}")
    print(f"Taille : {msi_out.stat().st_size / 1_048_576:.1f} MB")


if __name__ == "__main__":
    main()