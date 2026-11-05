"""Chiffrement / déchiffrement d'un dossier sur plusieurs processus (EncryptWorker)."""

from __future__ import annotations

import os

import core
import pytest
from ui_dialogs.encrypt_dialog import EncryptWorker


def _run(worker):
    results = []
    worker.finished.connect(lambda ok, msg: results.append((ok, msg)))
    worker.run()                      # exécution synchrone : pas besoin de boucle d'événements
    return results[0]


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "proj"
    (folder / "sub").mkdir(parents=True)
    contents = {}
    for i in range(6):
        path = folder / ("sub" if i % 2 else ".") / f"file{i}.bin"
        data = os.urandom(5000 + i)
        path.write_bytes(data)
        contents[path.relative_to(folder)] = data
    return folder, contents


def test_parallel_encrypt_then_decrypt_round_trip(project):
    folder, contents = project
    ok, message = _run(EncryptWorker(folder, "mot-de-passe", "encrypt"))
    assert ok, message
    assert not any(p.suffix == ".bin" for p in folder.rglob("*"))
    assert len(list(folder.rglob(f"*{core.SUFFIX}"))) == len(contents)

    ok, message = _run(EncryptWorker(folder, "mot-de-passe", "decrypt"))
    assert ok, message
    for rel, data in contents.items():
        assert (folder / rel).read_bytes() == data
    assert not list(folder.rglob(f"*{core.SUFFIX}"))


def test_parallel_decrypt_with_wrong_password_keeps_encrypted_files(project):
    folder, contents = project
    assert _run(EncryptWorker(folder, "bon", "encrypt"))[0]
    ok, message = _run(EncryptWorker(folder, "mauvais", "decrypt"))
    assert not ok and "incorrect" in message.lower()
    assert len(list(folder.rglob(f"*{core.SUFFIX}"))) == len(contents)
    assert not list(folder.rglob("*.bin"))
