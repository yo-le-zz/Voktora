"""Quick Notes — petites fonctions pures."""

from __future__ import annotations


def stats(text: str) -> tuple[int, int, int]:
    """(mots, caractères, lignes)."""
    return len(text.split()), len(text), (text.count("\n") + 1 if text else 0)


def describe(text: str) -> str:
    words, chars, lines = stats(text)
    if not text:
        return "Note vide"
    return f"{words} mot{'s' if words > 1 else ''} · {chars} caractères · {lines} ligne{'s' if lines > 1 else ''}"


def to_markdown(project: str, text: str) -> str:
    return f"# Notes — {project}\n\n{text.rstrip()}\n"
