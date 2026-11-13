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
