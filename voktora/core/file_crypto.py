"""
Voktora — core.file_crypto
Chiffrement de fichiers en flux, authentifié (AES-256-GCM, construction STREAM).

Pourquoi : l'ancien format `.menc` n'était qu'un XOR avec SHA-512(mot de passe) —
sans sel, sans authentification, trivialement cassable, et il chargeait le
fichier entier en mémoire (impossible sur un fichier de plusieurs Go). Le
nouveau format traite le fichier par blocs de 1 Mo : mémoire constante, une
mauvaise clé ou un fichier altéré/tronqué est détecté avant toute écriture
définitive.

Format d'un fichier `.vkenc` :
    magic(8) | sel(16) | préfixe de nonce(7) | taille de bloc u32 | blocs…
Chaque bloc est chiffré avec AES-256-GCM ; son nonce = préfixe(7) || compteur u32 || drapeau
« dernier bloc »(1). L'en-tête complet est lié à chaque bloc (AAD) : toute
modification de l'en-tête, réordonnancement ou troncature fait échouer le
déchiffrement. La clé vient de scrypt (n=2^15, r=8, p=1) et est calculée une
seule fois par opération grâce à un sel commun au projet.

Le format historique (`.menc`, `.encrypted`) reste déchiffrable pour que les
projets déjà chiffrés ne soient pas perdus, mais n'est plus jamais produit.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import struct
from collections.abc import Callable
from pathlib import Path

from . import constants

MAGIC = b"VKTENC2\n"
SUFFIX = ".vkenc"
LEGACY_SUFFIXES = (".menc", ".encrypted")
BLOCK_SIZE = 1024 * 1024
_TAG = 16
_SALT_LEN = 16
_PREFIX_LEN = 7
_HEADER_LEN = len(MAGIC) + _SALT_LEN + _PREFIX_LEN + 4
_MAX_BLOCK_SIZE = 64 * 1024 * 1024    # borne anti-allocation démesurée sur un en-tête hostile
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1

ByteProgress = Callable[[int], None]
CancelCheck = Callable[[], bool]


class DecryptionError(constants.ArchiveError):
    """Mot de passe incorrect, fichier altéré ou format inconnu."""


def new_salt() -> bytes:
    return os.urandom(_SALT_LEN)


def derive_key(password: str, salt: bytes) -> bytes:
    """Clé AES-256 dérivée du mot de passe (scrypt, ~32 Mo de mémoire)."""
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
                          maxmem=64 * 1024 * 1024, dklen=32)


def _nonce(prefix: bytes, counter: int, last: bool) -> bytes:
    return prefix + struct.pack(">IB", counter, 1 if last else 0)


def _check(cancel: CancelCheck | None) -> None:
    if cancel is not None and cancel():
        raise constants.OperationCancelled("Opération annulée.")


def _read_blocks(stream, size: int):
    """Itère (bloc, est_dernier) en lisant un bloc d'avance."""
    current = stream.read(size)
    while True:
        following = stream.read(size)
        yield current, not following
        if not following:
            return
        current = following


def encrypt_file(src: Path, dst: Path, key: bytes, salt: bytes,
                 on_bytes: ByteProgress | None = None, cancel: CancelCheck | None = None) -> None:
    """Chiffre `src` vers `dst` (écrit dans `dst` + « .part » puis renomme)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aead = AESGCM(key)
    prefix = os.urandom(_PREFIX_LEN)
    header = MAGIC + salt + prefix + struct.pack(">I", BLOCK_SIZE)
    part = dst.with_name(dst.name + ".part")
    try:
        with open(src, "rb") as fin, open(part, "wb") as fout:
            fout.write(header)
            for counter, (block, last) in enumerate(_read_blocks(fin, BLOCK_SIZE)):
                _check(cancel)
                fout.write(aead.encrypt(_nonce(prefix, counter, last), block, header))
                if on_bytes:
                    on_bytes(len(block))
            fout.flush()
            os.fsync(fout.fileno())
        part.replace(dst)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def read_header(path: Path) -> tuple[bytes, bytes, int] | None:
    """(sel, préfixe, taille de bloc) si `path` est au format `.vkenc`, sinon None."""
    try:
        with open(path, "rb") as f:
            head = f.read(_HEADER_LEN)
    except OSError:
        return None
    if len(head) < _HEADER_LEN or not head.startswith(MAGIC):
        return None
    salt = head[len(MAGIC):len(MAGIC) + _SALT_LEN]
    prefix = head[len(MAGIC) + _SALT_LEN:len(MAGIC) + _SALT_LEN + _PREFIX_LEN]
    (block_size,) = struct.unpack(">I", head[-4:])
    if not 0 < block_size <= _MAX_BLOCK_SIZE:
        return None
    return salt, prefix, block_size


def decrypt_file(src: Path, dst: Path, key: bytes,
                 on_bytes: ByteProgress | None = None, cancel: CancelCheck | None = None) -> None:
    """Déchiffre `src` vers `dst` ; lève DecryptionError sans rien laisser si la clé est mauvaise."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    info = read_header(src)
    if info is None:
        raise DecryptionError(f"Format de chiffrement inconnu : {src.name}")
    _salt, prefix, block_size = info
    aead = AESGCM(key)
    part = dst.with_name(dst.name + ".part")
    try:
        with open(src, "rb") as fin, open(part, "wb") as fout:
            header = fin.read(_HEADER_LEN)
            for counter, (block, last) in enumerate(_read_blocks(fin, block_size + _TAG)):
                _check(cancel)
                try:
                    plain = aead.decrypt(_nonce(prefix, counter, last), block, header)
                except InvalidTag as exc:
                    raise DecryptionError(
                        f"Mot de passe incorrect ou fichier altéré : {src.name}") from exc
                fout.write(plain)
                if on_bytes:
                    on_bytes(len(block))
            fout.flush()
            os.fsync(fout.fileno())
        part.replace(dst)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


# ──────────────────────────────────────────────
# FORMAT HISTORIQUE (XOR) — lecture seule
# ──────────────────────────────────────────────

def legacy_decrypt_file(src: Path, dst: Path, password: str,
                        on_bytes: ByteProgress | None = None, cancel: CancelCheck | None = None) -> None:
    """Déchiffre un ancien fichier `.menc` (XOR avec SHA-512) en flux, sans le charger en mémoire.

    Ce format n'est pas authentifié : un mauvais mot de passe produit un fichier
    illisible au lieu d'une erreur. Il ne sert qu'à récupérer d'anciens projets.
    """
    key = hashlib.sha512(password.encode("utf-8")).digest()          # 64 octets
    block = len(key) * 16384                                          # multiple de 64 → clé toujours alignée
    keystream = int.from_bytes(key * (block // len(key)), "big")
    part = dst.with_name(dst.name + ".part")
    try:
        with open(src, "rb") as fin, open(part, "wb") as fout:
            while chunk := fin.read(block):
                _check(cancel)
                ks = keystream if len(chunk) == block else int.from_bytes((key * (block // len(key)))[:len(chunk)], "big")
                out = int.from_bytes(chunk, "big") ^ ks
                fout.write(out.to_bytes(len(chunk), "big"))
                if on_bytes:
                    on_bytes(len(chunk))
        part.replace(dst)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def is_encrypted_name(path: Path) -> bool:
    return path.suffix in (SUFFIX, *LEGACY_SUFFIXES)


def remove_quietly(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()
