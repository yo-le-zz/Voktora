import ssl

from core import tls


def test_context_verifies_certificates():
    context = tls.make_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_falls_back_to_system_bundle(monkeypatch, tmp_path):
    bundle = tmp_path / "ca.crt"
    bundle.write_text("x")
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    monkeypatch.setattr(tls, "SYSTEM_BUNDLES", ())
    assert str(bundle) in tls._bundle_candidates()


def test_install_is_idempotent(monkeypatch):
    original = ssl._create_default_https_context
    monkeypatch.setattr(tls, "_installed", False)
    try:
        tls.install()
        tls.install()
        assert ssl._create_default_https_context is tls.make_context
    finally:
        ssl._create_default_https_context = original
