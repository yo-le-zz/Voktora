"""
Régression : `vault_unlock()` appelait `hmac.compare_digest(...)` sans que
le module `hmac` soit importé dans core.py, ce qui faisait planter le
déverrouillage du coffre (et donc la restauration de tout secret qui y
était stocké, y compris un token GitHub) avec un NameError à chaque essai.
"""

import core


class TestVault:
    def test_not_initialized_by_default(self, isolated_data_dir):
        assert core.vault_is_initialized() is False
        assert core.vault_is_unlocked() is False

    def test_unlock_with_correct_password_succeeds(self, isolated_data_dir):
        core.vault_init("master-pw")
        core.vault_lock()
        assert core.vault_unlock("master-pw") is True
        assert core.vault_is_unlocked() is True

    def test_unlock_with_wrong_password_fails_without_crashing(self, isolated_data_dir):
        core.vault_init("master-pw")
        core.vault_lock()
        assert core.vault_unlock("wrong-pw") is False
        assert core.vault_is_unlocked() is False

    def test_store_and_retrieve_secret_round_trip(self, isolated_data_dir):
        core.vault_init("master-pw")
        core.vault_store("github_token", "ghp_secret", domain="github_token")
        assert core.vault_retrieve("github_token") == "ghp_secret"

    def test_lock_clears_in_memory_key(self, isolated_data_dir):
        core.vault_init("master-pw")
        assert core.vault_is_unlocked() is True
        core.vault_lock()
        assert core.vault_is_unlocked() is False
