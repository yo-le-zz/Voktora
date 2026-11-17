"""Scripts d'installation en une commande (1.1.6)."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "Installers" / "install.sh"


def run(tmp_path, ident, like="", os_name="Linux", arch="x86_64"):
    rel = tmp_path / "os-release"
    rel.write_text(f'ID={ident}\nID_LIKE="{like}"\n')
    env = {**os.environ, "VOKTORA_OS_RELEASE": str(rel), "VOKTORA_VERSION": "1.1.6", "VOKTORA_DRY_RUN": "1",
           "VOKTORA_FORCE_OS": os_name, "VOKTORA_FORCE_ARCH": arch}
    return subprocess.run(["sh", str(SH)], capture_output=True, text=True, env=env, check=False)


@pytest.mark.parametrize("ident,like,asset,tool", [
    ("ubuntu", "debian", "voktora_1.1.6_amd64.deb", "apt-get"),
    ("fedora", "", "voktora-1.1.6-1.x86_64.rpm", "dnf"),
    ("nobara", "fedora", "voktora-1.1.6-1.x86_64.rpm", "dnf"),
    ("opensuse-tumbleweed", "suse", "voktora-1.1.6-1.x86_64.rpm", "zypper"),
    ("endeavouros", "arch", "voktora-1.1.6-1-x86_64.pkg.tar.zst", "pacman"),
])
def test_linux_distribution_detected(tmp_path, ident, like, asset, tool):
    r = run(tmp_path, ident, like)
    assert r.returncode == 0, r.stderr
    assert f"asset={asset}" in r.stdout and tool in r.stdout and f"/download/v1.1.6/{asset}" in r.stdout


def test_unknown_distro_and_arch_refused(tmp_path):
    assert run(tmp_path, "weird").returncode != 0
    assert run(tmp_path, "debian", arch="aarch64").returncode != 0


def test_macos_dmg(tmp_path):
    r = run(tmp_path, "x", os_name="Darwin")
    assert r.returncode == 0 and "Voktora_1.1.6_x86_64.dmg" in r.stdout


def test_scripts_verify_sha_and_site_copies_in_sync():
    for name in ("install.sh", "install.ps1"):
        text = (ROOT / "Installers" / name).read_text(encoding="utf-8")
        assert "SHA256SUMS" in text and ("sha256" in text.lower())
        assert text == (ROOT / "WebSite" / name).read_text(encoding="utf-8")
    pages = {p: (ROOT / "WebSite" / p).read_text(encoding="utf-8") for p in ("index.html", "download.html", "live.html")}
    assert "Installers/install.sh" in pages["index.html"] and "Installers/install.ps1" in pages["download.html"]
    assert "install-live.ps1" in pages["live.html"] and "macOS" in pages["index.html"]
