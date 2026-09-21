import core


class TestTokenEncryption:
    def test_round_trip(self):
        blob = core.token_encrypt("ghp_supersecrettoken", "correct horse")
        assert core.token_decrypt(blob, "correct horse") == "ghp_supersecrettoken"

    def test_wrong_password_returns_empty_string(self):
        blob = core.token_encrypt("ghp_supersecrettoken", "correct horse")
        assert core.token_decrypt(blob, "wrong password") == ""

    def test_corrupted_blob_returns_empty_string(self):
        assert core.token_decrypt("not-a-valid-blob", "correct horse") == ""

    def test_two_encryptions_of_same_secret_differ(self):
        # Le sel est régénéré à chaque appel : deux chiffrements du même
        # secret avec le même mot de passe doivent produire des blobs
        # différents (protection contre les attaques par dictionnaire).
        blob_a = core.token_encrypt("same-secret", "pw")
        blob_b = core.token_encrypt("same-secret", "pw")
        assert blob_a != blob_b
        assert core.token_decrypt(blob_a, "pw") == "same-secret"
        assert core.token_decrypt(blob_b, "pw") == "same-secret"

    def test_empty_plaintext_round_trip(self):
        blob = core.token_encrypt("", "pw")
        assert core.token_decrypt(blob, "pw") == ""
