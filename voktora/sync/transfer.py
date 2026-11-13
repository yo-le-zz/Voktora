"""
Voktora — sync.transfer (1.1.1)
Transferts plus légers entre deux PC :
  • **delta par blocs** : pour un gros fichier déjà présent des deux côtés, on compare des empreintes de blocs de 1 Mio et
    on ne transfère que les blocs qui diffèrent (journaux, bases de données, images disque, archives qui grandissent…) ;
    le résultat final est de toute façon vérifié par l'empreinte SHA-256 du fichier entier (sinon : transfert complet) ;
  • **compression** zlib (niveau 1, peu coûteuse) des fichiers compressibles, bloc par bloc, avec repli « brut » par bloc.
Aucune dépendance : zlib et hashlib suffisent. Les deux PC doivent être en 1.1.1 ; avec un pair plus ancien, la synchro
retombe automatiquement sur le transfert complet.
"""

from __future__ import annotations

import hashlib
import tempfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from . import secure

BLOCK = secure.CHUNK                     # 1 Mio : un bloc = un message chiffré
DELTA_MIN = 8 * 1024 * 1024              # en dessous, un transfert complet est aussi simple
DELTA_MAX_RATIO = 0.7                    # si > 70 % des blocs changent, mieux vaut tout envoyer
COMPRESS_MIN = 64 * 1024
RAW, ZLIB = b"\x00", b"\x01"
PIECE = secure.CHUNK - 1                 # 1 octet est réservé au marqueur : le bloc chiffré reste ≤ CHUNK

NO_COMPRESS = {".zip", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".7z", ".rar", ".jpg", ".jpeg", ".png", ".gif", ".webp",
               ".mp3", ".mp4", ".mkv", ".webm", ".avi", ".mov", ".ogg", ".flac", ".aac", ".pdf", ".woff", ".woff2",
               ".jar", ".apk", ".deb", ".rpm", ".whl", ".docx", ".xlsx", ".pptx", ".odt", ".heic", ".avif"}


def wants_compression(rel: str, size: int) -> bool:
    return size >= COMPRESS_MIN and Path(rel).suffix.lower() not in NO_COMPRESS


# ── compression ──────────────────────────────────────────────────────────────

def _reslice(chunks: Iterable[bytes], size: int) -> Iterator[bytes]:
    buf = bytearray()
    emitted = False
    for chunk in chunks:
        buf += chunk
        while len(buf) >= size:
            yield bytes(buf[:size])
            del buf[:size]
            emitted = True
    if buf or not emitted:
        yield bytes(buf)


def compress_chunks(chunks: Iterable[bytes]) -> Iterator[bytes]:
    for piece in _reslice(chunks, PIECE):
        packed = zlib.compress(piece, 1) if piece else b""
        yield (ZLIB + packed) if piece and len(packed) < len(piece) else (RAW + piece)


def decompress_chunks(chunks: Iterable[bytes]) -> Iterator[bytes]:
    for chunk in chunks:
        if not chunk:
            raise ValueError("bloc compressé vide")
        mark, body = chunk[:1], chunk[1:]
        if mark == RAW:
            yield body
        elif mark == ZLIB:
            decomp = zlib.decompressobj()
            data = decomp.decompress(body, secure.CHUNK * 4)           # borne : protège d'une « bombe » de décompression
            if decomp.unconsumed_tail or not decomp.eof:
                raise ValueError("bloc compressé trop grand ou tronqué")
            yield data
        else:
            raise ValueError("marqueur de compression inconnu")


class Spool:
    """Fichier temporaire des blocs compressés : permet de connaître la taille chiffrée AVANT d'envoyer (Content-Length)."""

    def __init__(self, chunks: Iterable[bytes]):
        self._file = tempfile.TemporaryFile()  # noqa: SIM115 — fermé par close()
        self.lengths: list[int] = []
        for block in compress_chunks(chunks):
            self._file.write(block)
            self.lengths.append(len(block))
        self._file.flush()

    @property
    def encrypted_length(self) -> int:
        return sum(self.lengths) + len(self.lengths) * secure.FRAME_OVERHEAD

    def iter(self) -> Iterator[bytes]:
        self._file.seek(0)
        for length in self.lengths:
            yield self._file.read(length)

    def close(self) -> None:
        self._file.close()


# ── delta par blocs ──────────────────────────────────────────────────────────

def hash_block(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=12).hexdigest()


def block_hashes(path: Path, throttle: float = 0.0, cancel: Callable[[], bool] | None = None,
                 sleep: Callable[[float], None] | None = None) -> list[str]:
    import time
    pause = sleep or time.sleep
    out: list[str] = []
    with open(path, "rb") as handle:
        while block := handle.read(BLOCK):
            if cancel and cancel():
                raise InterruptedError("annulé")
            out.append(hash_block(block))
            if throttle:
                pause(throttle * len(block) / BLOCK)
    return out


def changed_blocks(have: list[str], want: list[str]) -> list[int]:
    """Indices des blocs de `want` (version cible) à transférer pour qui possède déjà `have`."""
    return [i for i, h in enumerate(want) if i >= len(have) or have[i] != h]


def worth_delta(changed: list[int], total_blocks: int) -> bool:
    return total_blocks > 0 and len(changed) <= total_blocks * DELTA_MAX_RATIO


def encode_ranges(indices: list[int]) -> str:
    """[0,1,2,5,7,8] → « 0-2,5,7-8 » (reste court même pour des milliers de blocs : limite de l'URL)."""
    out: list[str] = []
    start = prev = None
    for i in sorted(indices):
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            out.append(f"{start}-{prev}" if prev != start else str(start))
            start = prev = i
    if start is not None:
        out.append(f"{start}-{prev}" if prev != start else str(start))
    return ",".join(out)


def decode_ranges(text: str, limit: int = 10_000_000) -> list[int]:
    out: list[int] = []
    for part in filter(None, text.split(",")):
        lo, _, hi = part.partition("-")
        a, b = int(lo), int(hi or lo)
        if a < 0 or b < a or b - a > limit or len(out) + (b - a + 1) > limit:
            raise ValueError("plage de blocs invalide")
        out.extend(range(a, b + 1))
    return out
