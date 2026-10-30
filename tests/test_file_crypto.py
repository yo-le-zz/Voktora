"""Tests du chiffrement de fichiers en flux (AES-256-GCM) et de l'ancien format XOR (lecture seule)."""

import hashlib
import os

import core
import pytest
from core import file_crypto as fc


@pytest.fixture
def keyed():
    salt = fc.new_salt()
    return salt, fc.derive_key("un-bon-mot-de-passe", salt)


class TestStreamEncryption:
    @pytest.mark.parametrize("size", [0, 1, 1000, fc.BLOCK_SIZE - 1, fc.BLOCK_SIZE, fc.BLOCK_SIZE + 1, 3 * fc.BLOCK_SIZE + 7])
    def test_round_trip_all_block_boundaries(self, tmp_path, keyed, size):
        salt, key = keyed
        data = os.urandom(size)
        (tmp_path / "f").write_bytes(data)
        fc.encrypt_file(tmp_path / "f", tmp_path / "f.vkenc", key, salt)
        fc.decrypt_file(tmp_path / "f.vkenc", tmp_path / "out", key)
        assert (tmp_path / "out").read_bytes() == data

    def test_ciphertext_hides_plaintext_and_differs_each_time(self, tmp_path, keyed):
        salt, key = keyed
        (tmp_path / "f").write_bytes(b"A" * 5000)
        fc.encrypt_file(tmp_path / "f", tmp_path / "a.vkenc", key, salt)
        fc.encrypt_file(tmp_path / "f", tmp_path / "b.vkenc", key, salt)
        assert b"AAAA" not in (tmp_path / "a.vkenc").read_bytes()
        assert (tmp_path / "a.vkenc").read_bytes() != (tmp_path / "b.vkenc").read_bytes()

    def test_wrong_password_raises_and_leaves_nothing(self, tmp_path, keyed):
        salt, key = keyed
        (tmp_path / "f").write_bytes(b"secret")
        fc.encrypt_file(tmp_path / "f", tmp_path / "f.vkenc", key, salt)
        with pytest.raises(fc.DecryptionError):
            fc.decrypt_file(tmp_path / "f.vkenc", tmp_path / "out", fc.derive_key("faux", salt))
        assert not (tmp_path / "out").exists()
        assert not (tmp_path / "out.part").exists()

    def test_tampering_is_detected(self, tmp_path, keyed):
        salt, key = keyed
        (tmp_path / "f").write_bytes(os.urandom(5000))
        fc.encrypt_file(tmp_path / "f", tmp_path / "f.vkenc", key, salt)
        raw = bytearray((tmp_path / "f.vkenc").read_bytes())
        raw[-20] ^= 1
        (tmp_path / "f.vkenc").write_bytes(raw)
        with pytest.raises(fc.DecryptionError):
            fc.decrypt_file(tmp_path / "f.vkenc", tmp_path / "out", key)

    def test_truncation_is_detected(self, tmp_path, keyed):
        salt, key = keyed
        (tmp_path / "f").write_bytes(os.urandom(fc.BLOCK_SIZE * 2 + 10))
        fc.encrypt_file(tmp_path / "f", tmp_path / "f.vkenc", key, salt)
        raw = (tmp_path / "f.vkenc").read_bytes()
        (tmp_path / "cut.vkenc").write_bytes(raw[:fc._HEADER_LEN + fc.BLOCK_SIZE + 16])
        with pytest.raises(fc.DecryptionError):
            fc.decrypt_file(tmp_path / "cut.vkenc", tmp_path / "out", key)

    def test_cancel_leaves_no_partial_file(self, tmp_path, keyed):
        salt, key = keyed
        (tmp_path / "f").write_bytes(os.urandom(fc.BLOCK_SIZE * 3))
        with pytest.raises(core.OperationCancelled):
            fc.encrypt_file(tmp_path / "f", tmp_path / "f.vkenc", key, salt, cancel=lambda: True)
        assert not (tmp_path / "f.vkenc").exists() and not (tmp_path / "f.vkenc.part").exists()

    def test_unknown_format_is_refused(self, tmp_path, keyed):
        _salt, key = keyed
        (tmp_path / "x.vkenc").write_bytes(b"pas du tout un fichier chiffre" * 3)
        with pytest.raises(fc.DecryptionError):
            fc.decrypt_file(tmp_path / "x.vkenc", tmp_path / "out", key)

    def test_hostile_block_size_header_is_rejected(self, tmp_path):
        header = fc.MAGIC + b"s" * 16 + b"p" * 7 + (2**31).to_bytes(4, "big")
        (tmp_path / "h.vkenc").write_bytes(header + b"x" * 40)
        assert fc.read_header(tmp_path / "h.vkenc") is None


class TestLegacyDecrypt:
    @pytest.mark.parametrize("size", [0, 5, 64, 70_000, 64 * 16384 * 2 + 3])
    def test_legacy_xor_files_remain_recoverable(self, tmp_path, size):
        key = hashlib.sha512(b"ancien-mdp").digest()
        plain = os.urandom(size)
        (tmp_path / "a.txt.menc").write_bytes(bytes(b ^ key[i % 64] for i, b in enumerate(plain)))
        fc.legacy_decrypt_file(tmp_path / "a.txt.menc", tmp_path / "a.txt", "ancien-mdp")
        assert (tmp_path / "a.txt").read_bytes() == plain
