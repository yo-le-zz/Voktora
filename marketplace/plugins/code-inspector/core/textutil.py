"""Utilitaires texte : suppression des commentaires/chaînes (Rust, JS, C/C++), correspondance d'accolades, blocs dupliqués."""

from __future__ import annotations

import hashlib
import re


def mask_c_like(src: str, *, templates: bool = False, rust: bool = False, keep_strings: bool = False) -> str:
    """Remplace commentaires et contenus de chaînes par des espaces (mêmes longueurs et sauts de ligne) :
    les numéros de ligne et les positions restent valables, les accolades dans les chaînes disparaissent."""
    out, i, n = [], 0, len(src)
    while i < n:
        c, nxt = src[i], src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
        elif rust and c == "r" and re.match(r'r#*"', src[i:i + 12]) and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_")):
            m = re.match(r'r(#*)"', src[i:])
            end = '"' + m.group(1)
            j = src.find(end, i + m.end())
            j = n if j < 0 else j + len(end)
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
        elif c == '"' or (templates and c == "`"):
            q, j = c, i + 1
            while j < n and src[j] != q:
                j += 2 if src[j] == "\\" else 1
            j = min(n, j + 1)
            out.append(src[i:j] if keep_strings else q + re.sub(r"[^\n]", " ", src[i + 1:j - 1]) + (q if j - 1 > i else ""))
            i = j
        elif c == "'" and not rust:
            j = i + 1
            while j < n and src[j] != "'" and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            j = min(n, j + 1)
            out.append(src[i:j] if keep_strings else "'" + re.sub(r"[^\n]", " ", src[i + 1:j - 1]) + "'")
            i = j
        elif rust and c == "'":
            m = re.match(r"'(\\.|[^\\'])'", src[i:])        # littéral de caractère ; sinon durée de vie ('a)
            if m:
                out.append("'" + " " * (m.end() - 2) + "'")
                i += m.end()
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def match_brace(text: str, open_index: int, open_ch: str = "{", close_ch: str = "}") -> int:
    """Index de l'accolade fermante correspondant à `open_index` (texte déjà masqué), ou -1."""
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def line_starts(text: str) -> list[int]:
    starts = [0]
    for m in re.finditer("\n", text):
        starts.append(m.end())
    return starts


def line_at(starts: list[int], index: int) -> int:
    import bisect
    return bisect.bisect_right(starts, index)


WINDOW = 6


def duplicate_blocks(lines: list[str], window: int = WINDOW) -> list[list]:
    """Hachages de fenêtres de `window` lignes significatives normalisées : [[hash, première, dernière]]."""
    kept = [(i + 1, re.sub(r"\s+", " ", ln).strip()) for i, ln in enumerate(lines)]
    kept = [(i, t) for i, t in kept if len(t) > 3 and t not in {"{", "}", "(", ")", "else:", "else {", "});", "end"}
            and not t.startswith(("#", "//", "import ", "from ", "use ", "#include", "*", "/*"))]
    out = []
    for k in range(len(kept) - window + 1):
        chunk = kept[k:k + window]
        digest = hashlib.sha1("\n".join(t for _, t in chunk).encode("utf-8", "replace")).hexdigest()[:12]
        out.append([digest, chunk[0][0], chunk[-1][0]])
    return out


def file_digest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()
