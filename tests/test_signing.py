"""Index signé du marketplace (Ed25519)."""
import pytest
import signing
from plugins import market


def test_sign_verify_roundtrip_and_tamper():
    private, public = signing.generate_keypair()
    sig = signing.sign(b"index", private)
    assert signing.verify(b"index", sig, [public]) == public
    with pytest.raises(signing.SignatureError):
        signing.verify(b"index modifie", sig, [public])
    with pytest.raises(signing.SignatureError):
        signing.verify(b"index", sig, [signing.generate_keypair()[1]])
    with pytest.raises(signing.SignatureError):
        signing.verify(b"index", "pas du base64 !", [public])


def test_trusted_keys_filter_invalid():
    got = signing.trusted_keys(["zz", "A" * 64])
    assert "a" * 64 in got and "zz" not in got


def test_keys_file_lists_yolezz_key():
    keys = signing.load_keys_file()
    assert "447b1d786bc4c7434e15a3da852781668c3018d1a648b6cfb4c0c9d4e72cce0a" in keys
    assert all(len(k) == 64 for k in keys)


def test_keys_file_shipped_by_builds():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for script in ("Installers/linux_common.sh", "Installers/MSI installer/build_msi.py", "Installers/macOS installer/build_dmg.sh"):
        assert "trusted_keys.json" in (root / script).read_text(encoding="utf-8"), script
    assert "macos-15-intel" in (root / ".github/workflows/build-release.yml").read_text(encoding="utf-8")


def test_fetch_index_requires_valid_signature_when_keys_configured(isolated_data_dir, monkeypatch):
    private, public = signing.generate_keypair()
    from pathlib import Path
    index = (Path(__file__).resolve().parents[1] / "marketplace" / "index.json").read_bytes()
    good = signing.sign(index, private)
    served = {"index.json": index, "index.json.sig": good.encode()}

    def fake(url, timeout=0, limit=0):
        name = url.rsplit("/", 1)[1]
        if name not in served:
            raise market.MarketError("404")
        return served[name]
    monkeypatch.setattr(market, "_fetch", fake)
    monkeypatch.setattr(signing, "trusted_keys", lambda extra=None: [public])
    assert market.fetch_index("https://x")[0]
    served["index.json.sig"] = signing.sign(b"autre", private).encode()
    with pytest.raises(market.MarketError, match="authentique"):
        market.fetch_index("https://x", use_cache_on_error=False)
    del served["index.json.sig"]
    with pytest.raises(market.MarketError, match="authentique"):
        market.fetch_index("https://x", use_cache_on_error=False)
