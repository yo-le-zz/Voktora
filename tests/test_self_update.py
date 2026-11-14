import hashlib
import io

import pytest
import self_update as su


def payload(tag="v9.0.0", **kw):
    return {"tag_name": tag, "body": "notes", "html_url": "https://github.com/x", "assets": [
        {"name": "Voktora-linux-x86_64.tar.gz", "browser_download_url": "https://github.com/a.tgz", "size": 5,
         "digest": "sha256:" + hashlib.sha256(b"hello").hexdigest()},
        {"name": "Voktora-windows.exe", "browser_download_url": "https://github.com/a.exe", "size": 5}], **kw}


def test_versions():
    assert su.is_newer("v1.1.1", "1.1.0") and not su.is_newer("1.1.0", "1.1.0") and not su.is_newer("garbage", "1.0.0")
    assert su.parse_release(payload("latest")) is None and su.parse_release(payload(prerelease=True)) is None


def test_pick_and_download(isolated_data_dir, monkeypatch):
    release = su.parse_release(payload())
    monkeypatch.setattr(su.sys, "platform", "linux")
    assert su.pick_asset(release) == "Voktora-linux-x86_64.tar.gz"

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(su.urllib.request, "urlopen", lambda *a, **k: R(b"hello"))
    path = su.download(release)
    assert path.read_bytes() == b"hello"
    monkeypatch.setattr(su.urllib.request, "urlopen", lambda *a, **k: R(b"HELLO"))
    with pytest.raises(su.UpdateError):
        su.download(release)
    assert not list(su.staging_dir().glob("*.part"))


def test_refuses_without_checksum(isolated_data_dir):
    release = su.parse_release(payload())
    with pytest.raises(su.UpdateError):
        su.download(release, "Voktora-windows.exe")


def test_http_refused():
    with pytest.raises(su.UpdateError):
        su._get("http://example.org")


# ── 1.1.3 : installation automatique (script détaché), architecture, distribution ──────────────

import subprocess  # noqa: E402

import update_install as ui  # noqa: E402


def test_arch_detection():
    assert ui.file_arch("Voktora-1.1.3-aarch64.rpm") == "aarch64" and ui.file_arch("voktora_1.1.3_amd64.deb") == "x86_64"
    assert ui.file_arch("Voktora-1.1.3.AppImage") is None
    assert ui.arch_matches("a-x86_64.rpm", "x86_64") and not ui.arch_matches("a-arm64.deb", "x86_64")


def test_pick_asset_follows_distro_and_arch(monkeypatch):
    names = ["Voktora-1.1.3-x86_64.rpm", "Voktora-1.1.3-aarch64.rpm", "voktora_1.1.3_amd64.deb", "Voktora-linux.tar.gz"]
    release = su.Release("v1.1.3", "1.1.3", assets={n: {"url": "https://x/" + n, "size": 1, "digest": ""} for n in names})
    monkeypatch.setattr(su.sys, "platform", "linux")
    monkeypatch.setattr(ui, "machine_arch", lambda: "aarch64")
    monkeypatch.setattr(ui, "distro_family", lambda: "fedora")
    assert su.pick_asset(release) == "Voktora-1.1.3-aarch64.rpm"
    monkeypatch.setattr(ui, "machine_arch", lambda: "x86_64")
    monkeypatch.setattr(ui, "distro_family", lambda: "debian")
    assert su.pick_asset(release) == "voktora_1.1.3_amd64.deb"
    monkeypatch.setattr(ui, "distro_family", lambda: "other")
    assert su.pick_asset(release) == "Voktora-linux.tar.gz"
    monkeypatch.setattr(ui, "machine_arch", lambda: "riscv64")
    assert su.pick_asset(release) == "Voktora-linux.tar.gz"       # sans architecture dans le nom : acceptée


def _script(tmp_path, name, pid=0):
    f = tmp_path / name
    f.write_bytes(b"x")
    return ui.prepare(f, tmp_path / "logs", "1.1.2", pid=pid)


def _dry(script, **env):
    import os
    return subprocess.run(["/bin/sh", str(script)], capture_output=True, text=True, timeout=30, check=False,
                          env={**os.environ, "VOKTORA_UPDATE_DRYRUN": "1", **env})


def test_scripts_are_valid_shell_for_every_kind(tmp_path):
    for name, _expected in (("Voktora-x86_64.rpm", "dnf install"), ("v_amd64.deb", "apt-get install"),
                           ("Voktora.pkg.tar.zst", "pacman -U"), ("Voktora.AppImage", "AppImage"), ("Voktora.tar.gz", "archive")):
        script = _script(tmp_path, name)
        assert subprocess.run(["/bin/sh", "-n", str(script)], check=False).returncode == 0
        if "x86_64" in name and ui.machine_arch() != "x86_64":
            continue
        out = _dry(script)
        assert out.returncode == 0 and "installation terminée" in out.stdout and "relance" in out.stdout, out.stdout + out.stderr


def test_script_kills_running_voktora_and_logs(tmp_path):
    victim = subprocess.Popen(["sleep", "60"])
    script = _script(tmp_path, "Voktora.tar.gz", pid=victim.pid)
    import os
    out = subprocess.run(["/bin/sh", str(script)], capture_output=True, text=True, timeout=30, check=False,
                         env={**os.environ, "VOKTORA_INSTALL_DIR": str(tmp_path / "dest")})
    assert victim.wait(timeout=5) != 0                       # tué (TERM)
    log = (tmp_path / "logs" / "update.log").read_text()
    assert "arrêt de Voktora" in log and "ÉCHEC" in log     # « x » n'est pas une archive valide : échec propre
    assert out.returncode == 1 and "relance" not in out.stdout


def test_wrong_architecture_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "machine_arch", lambda: "x86_64")
    f = tmp_path / "Voktora-aarch64.rpm"
    f.write_bytes(b"x")
    with pytest.raises(ui.InstallError):
        ui.prepare(f, tmp_path / "l")
    # et le script lui-même se protège si on le lance sur une autre machine
    script = ui.build_sh(f, "rpm", 0, tmp_path / "l.log", ["true"], arch="aarch64")
    p = tmp_path / "s.sh"
    p.write_text(script)
    out = subprocess.run(["/bin/sh", str(p)], capture_output=True, text=True, timeout=20, check=False,
                         env={"PATH": "/usr/bin:/bin", "VOKTORA_UPDATE_DRYRUN": ""})
    if ui.machine_arch() != "aarch64":
        assert out.returncode == 1 and "ARM" not in out.stdout and "aarch64" in (tmp_path / "l.log").read_text()


def test_powershell_script_text(tmp_path):
    f = tmp_path / "Voktora-x64.msi"
    f.write_bytes(b"x")
    text = ui.build_ps1(f, "msi", 123, tmp_path / "u.log", "C:\\Voktora\\Voktora.exe", "1.1.2")
    assert "msiexec" in text and "Stop-Process -Id $Pid_" in text and "'C:\\Voktora\\Voktora.exe'" in text and "{" in text
    assert ui.kind_of("x.MSI") == "msi" and ui.kind_of("a.dmg") == "dmg"
    with pytest.raises(ui.InstallError):
        ui.kind_of("a.zip")
