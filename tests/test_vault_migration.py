"""Régression sécurité : le verifier du coffre ne doit jamais révéler la clé maître (format v1)."""

import base64
import hashlib
import os

import core
from core import crypto


def _make_v1_vault(password: str, secrets: dict[str, str]) -> bytes:
    """Fabrique un coffre au format v1 (vulnérable) ; retourne le verifier stocké."""
    salt = os.urandom(32)
    verifier = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 480_000, dklen=64)
    master = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 480_000, dklen=32)
    cfg = core.config_store._load_config()
    cfg["vault"] = {"verifier": base64.b64encode(verifier).decode(), "salt": base64.b64encode(salt).decode()}
    core.config_store._save_config(cfg)
    crypto._VAULT_MASTER_KEY = master
    for name, value in secrets.items():
        core.vault_store(name, value, domain="general")
    crypto.vault_lock()
    return verifier


class TestVaultVerifierDoesNotLeakKey:
    def test_new_vault_verifier_is_not_the_master_key(self, isolated_data_dir):
        core.vault_init("master-pw")
        info = core.config_store._load_config()["vault"]
        verifier = base64.b64decode(info["verifier"])
        assert info["version"] == 2
        assert crypto._VAULT_MASTER_KEY not in (verifier, verifier[:32])

    def test_v1_vault_unlocks_and_is_migrated(self, isolated_data_dir):
        old_verifier = _make_v1_vault("master-pw", {"tok": "ghp_abc", "key": "ssh-xyz"})
        old_salt = core.config_store._load_config()["vault"]["salt"]

        assert core.vault_unlock("master-pw") is True

        info = core.config_store._load_config()["vault"]
        assert info["version"] == 2
        assert info["salt"] != old_salt                           # clé renouvelée
        assert base64.b64decode(info["verifier"]) != old_verifier  # l'ancien verifier a disparu
        assert core.vault_retrieve("tok") == "ghp_abc"
        assert core.vault_retrieve("key") == "ssh-xyz"

        core.vault_lock()
        assert core.vault_unlock("wrong") is False
        assert core.vault_unlock("master-pw") is True
        assert core.vault_retrieve("tok") == "ghp_abc"

    def test_old_leaked_key_cannot_decrypt_migrated_secrets(self, isolated_data_dir):
        old_verifier = _make_v1_vault("master-pw", {"tok": "ghp_abc"})
        core.vault_unlock("master-pw")
        leaked_key = old_verifier[:32]
        crypto._VAULT_MASTER_KEY = leaked_key
        assert core.vault_retrieve("tok") == ""

    def test_v1_vault_with_wrong_password_is_refused(self, isolated_data_dir):
        _make_v1_vault("master-pw", {"tok": "x"})
        assert core.vault_unlock("nope") is False
        assert core.config_store._load_config()["vault"].get("version", 1) == 1
