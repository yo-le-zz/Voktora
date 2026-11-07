"""
Voktora — sync.merge
Fusion à trois voies (comme git) : si le même fichier a été modifié sur les deux PC à des endroits différents,
les deux modifications sont appliquées ; si elles se chevauchent, c'est un conflit (le principal gagnera).
"""

from __future__ import annotations

import difflib


def _hunks(base: list[str], other: list[str]) -> list[tuple[int, int, list[str]]]:
    """Modifications de `base` vers `other` : [(début, fin, lignes de remplacement)] (indices dans base)."""
    matcher = difflib.SequenceMatcher(None, base, other, autojunk=False)
    return [(i1, i2, other[j1:j2]) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"]


def diff3(base: str, local: str, remote: str) -> tuple[str, bool]:
    """(texte fusionné, conflit ?). En cas de conflit le texte retourné est celui de `local`."""
    if local == remote:
        return local, False
    if local == base:
        return remote, False
    if remote == base:
        return local, False
    b, a, r = base.splitlines(keepends=True), local.splitlines(keepends=True), remote.splitlines(keepends=True)
    ha, hr = _hunks(b, a), _hunks(b, r)
    out: list[str] = []
    pos = ia = ir = 0
    while ia < len(ha) or ir < len(hr):
        na = ha[ia] if ia < len(ha) else None
        nr = hr[ir] if ir < len(hr) else None
        # Chevauchement (ou insertions au même point) : identique = ok, sinon conflit.
        if na and nr and (na[0] < nr[1] and nr[0] < na[1] or na[0] == nr[0]):
            if na == nr:
                out.extend(b[pos:na[0]])
                out.extend(na[2])
                pos = na[1]
                ia += 1
                ir += 1
                continue
            return local, True
        take_a = na is not None and (nr is None or na[0] < nr[0] or (na[0] == nr[0] and na[1] <= nr[1]))
        hunk = na if take_a else nr
        out.extend(b[pos:hunk[0]])
        out.extend(hunk[2])
        pos = hunk[1]
        if take_a:
            ia += 1
        else:
            ir += 1
    out.extend(b[pos:])
    return "".join(out), False


def is_text(data: bytes) -> bool:
    if b"\0" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
