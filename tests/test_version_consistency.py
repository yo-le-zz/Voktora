"""La version est déclarée à plusieurs endroits : ils doivent toujours concorder."""

import re
import tomllib
from pathlib import Path

import core

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _version_txt() -> str:
    return (ROOT / "voktora" / "version.txt").read_text(encoding="utf-8").strip().lstrip("v")


def _changelog_top_version() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^##\s*\[?v?(\d+\.\d+\.\d+)", text, re.MULTILINE)
    assert match, "aucune version trouvée dans CHANGELOG.md"
    return match.group(1)


def test_all_version_declarations_match():
    assert _pyproject_version() == _version_txt() == core.APP_VERSION == _changelog_top_version()
