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


def test_system_bundle_always_loaded_even_if_default_store_looks_filled(monkeypatch, tmp_path):
    """Régression Fedora : le magasin par défaut non vide mais inutile empêchait de charger le lot système."""
    loaded = []
    real = ssl.SSLContext.load_verify_locations

    def spy(self, cafile=None, *a, **k):
        loaded.append(cafile)
        return real(self, cafile, *a, **k)
    bundle = tmp_path / "ca.crt"
    bundle.write_text("pas un certificat")
    monkeypatch.setattr(tls, "_context", None)
    monkeypatch.setattr(tls, "SYSTEM_BUNDLES", (str(bundle),))
    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", spy)
    tls.make_context()
    assert str(bundle) in loaded
    monkeypatch.setattr(tls, "_context", None)


def test_export_environment_never_overrides_user(monkeypatch, tmp_path):
    bundle = tmp_path / "ca.crt"
    bundle.write_text("x")
    monkeypatch.setattr(tls, "SYSTEM_BUNDLES", (str(bundle),))
    for name in tls._ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    mine = tmp_path / "mien.pem"
    mine.write_text("x")
    monkeypatch.setenv("GIT_SSL_CAINFO", str(mine))
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/inexistant.pem")
    assert tls.export_environment() == str(bundle)
    import os
    assert os.environ["SSL_CERT_FILE"] == str(bundle) and os.environ["CURL_CA_BUNDLE"] == str(bundle)
    assert os.environ["GIT_SSL_CAINFO"] == str(mine)                  # valide : respecté
    assert os.environ["REQUESTS_CA_BUNDLE"] == str(bundle)            # cassé : remplacé
