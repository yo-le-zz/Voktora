"""
build_msi.py - Voktora Windows MSI builder
Compile avec Nuitka (--onedir) puis empaquete en .msi via WiX Toolset 4.x

Prerequis :
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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT    = Path(__file__).resolve().parent.parent.parent
VERSION = sys.argv[1] if len(sys.argv) > 1 else (ROOT / "voktora" / "version.txt").read_text().strip()
DIST    = ROOT / "dist" / "windows"
WXS_DIR = ROOT / "Installers" / "MSI installer"


def run(cmd, **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True, **kw)


def find_nuitka_onedir() -> Path:
    """
    Nuitka cree un dossier  <output-filename>.dist  ou  <source>.dist
    selon la version. On cherche tous les candidats et on prend le plus gros.
    """
    candidates = list(DIST.glob("*.dist"))
    if not candidates:
        raise FileNotFoundError(
            f"Aucun dossier *.dist trouve dans {DIST}\n"
            f"Contenu : {list(DIST.iterdir())}"
        )
    # Prendre le dossier avec le plus de fichiers (= le vrai onedir)
    best = max(candidates, key=lambda p: sum(1 for _ in p.rglob("*") if _.is_file()))
    total = sum(1 for _ in best.rglob("*") if _.is_file())
    print(f"    onedir detecte : {best.name}  ({total} fichiers)")
    return best


def generate_files_wxs(onedir: Path, out: Path) -> None:
    """
    Genere voktora_files.wxs — fichier WiX source autonome (racine <Wix>).
    Passe directement a  wix build  en complement de voktora.wxs.

    Structure :
      <Wix>
        <Fragment>
          <DirectoryRef Id="VOKTORA_DIR">
            <Directory Id="dir_assets" Name="assets"/>
            <Directory Id="dir_themes" Name="themes">...</Directory>
          </DirectoryRef>
        </Fragment>
        <Fragment>
          <ComponentGroup Id="VoktoraFiles">
            <Component ...><File .../></Component>
            ...
          </ComponentGroup>
        </Fragment>
      </Wix>
    """
    print(f"\n>>> Generation {out.name} ({onedir})...")

    WIX = "http://wixtoolset.org/schemas/v4/wxs"
    ET.register_namespace("", WIX)

    wix_el = ET.Element(f"{{{WIX}}}Wix")

    # -- Fragment 1 : sous-repertoires via DirectoryRef -----------------------
    frag_dirs = ET.SubElement(wix_el, f"{{{WIX}}}Fragment")
    dir_ref   = ET.SubElement(frag_dirs, f"{{{WIX}}}DirectoryRef", Id="VOKTORA_DIR")

    dir_elements: dict = {onedir: dir_ref}
    dir_ids:      dict = {}

    def dir_id(p: Path) -> str:
        if p not in dir_ids:
            rel  = p.relative_to(onedir)
            safe = (str(rel)
                    .replace("\\", "_").replace("/", "_")
                    .replace(" ", "_").replace("-", "_").replace(".", "_"))
            dir_ids[p] = f"dir_{safe}"
        return dir_ids[p]

    def ensure_dir(p: Path) -> ET.Element:
        if p in dir_elements:
            return dir_elements[p]
        parent_el = ensure_dir(p.parent)
        el = ET.SubElement(parent_el, f"{{{WIX}}}Directory",
                           Id=dir_id(p), Name=p.name)
        dir_elements[p] = el
        return el

    for d in sorted(p for p in onedir.rglob("*") if p.is_dir()):
        ensure_dir(d)

    # -- Fragment 2 : ComponentGroup avec tous les fichiers -------------------
    frag_files = ET.SubElement(wix_el, f"{{{WIX}}}Fragment")
    cg         = ET.SubElement(frag_files, f"{{{WIX}}}ComponentGroup",
                               Id="VoktoraFiles")

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

    ET.indent(ET.ElementTree(wix_el), space="  ")
    out.write_bytes(
        b'<?xml version="1.0" encoding="UTF-8"?>\n' +
        ET.tostring(wix_el, encoding="unicode").encode("utf-8")
    )
    print(f"    {file_counter} fichiers indexes -> {out}")


def main():
    print("=== Voktora MSI builder ===")
    print(f"Version : {VERSION}")
    print(f"Root    : {ROOT}")

    shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir(parents=True)

    # -- Compilation Nuitka ---------------------------------------------------
    print("\n>>> Compilation Nuitka...")
    run([
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--remove-output",
        "--enable-plugin=pyside6",
        "--include-qt-plugins=all",
        "--assume-yes-for-downloads",
        f"--windows-icon-from-ico={ROOT / 'assets' / 'Voktora.ico'}",
        "--windows-console-mode=disable",
        f"--output-dir={DIST}",
        "--output-filename=voktora",
        ROOT / "voktora" / "main.py",
    ])

    # Detecter le dossier onedir cree par Nuitka (main.dist ou voktora.dist)
    raw_onedir = find_nuitka_onedir()

    # Renommer en voktora.dist si ce n'est pas deja le cas
    onedir_final = DIST / "voktora.dist"
    if raw_onedir != onedir_final:
        raw_onedir.rename(onedir_final)
        print(f"    renomme : {raw_onedir.name} -> voktora.dist")

    # Verifier que le onedir n'est pas vide
    n_files = sum(1 for _ in onedir_final.rglob("*") if _.is_file())
    print(f"    onedir final : {onedir_final}  ({n_files} fichiers)")
    if n_files < 50:
        raise RuntimeError(
            f"Le onedir semble incomplet ({n_files} fichiers). "
            "Verifiez la compilation Nuitka."
        )

    # Copier ressources
    shutil.copytree(ROOT / "voktora" / "themes", onedir_final / "themes", dirs_exist_ok=True)
    shutil.copytree(ROOT / "assets",             onedir_final / "assets",  dirs_exist_ok=True)
    shutil.copy(ROOT / "voktora" / "version.txt", onedir_final / "version.txt")

    n_final = sum(1 for _ in onedir_final.rglob("*") if _.is_file())
    print(f"    apres copie ressources : {n_final} fichiers")

    # -- Generer voktora_files.wxs --------------------------------------------
    files_wxs = WXS_DIR / "voktora_files.wxs"
    generate_files_wxs(onedir_final, files_wxs)

    # -- Build MSI ------------------------------------------------------------
    print("\n>>> Build MSI (wix build)...")
    msi_out = DIST / f"Voktora_{VERSION}_x64.msi"
    run([
        "wix", "build",
        str(WXS_DIR / "voktora.wxs"),
        str(files_wxs),
        "-d", f"VERSION={VERSION}",
        "-d", f"SourceDir={onedir_final}",
        "-ext", "WixToolset.UI.wixext",
        "-o", str(msi_out),
    ])

    size_mb = msi_out.stat().st_size / 1_048_576
    print(f"\n=== Succes ===")
    print(f"MSI    : {msi_out}")
    print(f"Taille : {size_mb:.1f} MB")
    if size_mb < 50:
        print(f"AVERTISSEMENT : MSI anormalement petit ({size_mb:.1f} MB) — "
              "les DLLs sont peut-etre manquantes.")


if __name__ == "__main__":
    main()