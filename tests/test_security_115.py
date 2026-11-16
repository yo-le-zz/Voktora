"""Régressions de sécurité 1.1.5."""

from pathlib import Path

import archiving
import pytest
import shops
from sync import store


def test_preview_refuses_bad_id_and_names():
    with pytest.raises(shops.ShopError):
        shops.preview_files(shops.ShopItem("icons", "../evil", "x", "1", "a", files={"a.svg": "0" * 64}))
    with pytest.raises(Exception):  # noqa: B017
        shops.preview_files(shops.ShopItem("icons", "ok", "x", "1", "a", files={"../../x.svg": "0" * 64}))


def test_archive_outside_dir_refused(isolated_data_dir, tmp_path):
    outside = tmp_path / "x.zip"
    outside.write_bytes(b"x")
    with pytest.raises(archiving.ArchiveError):
        archiving._own_archive(str(outside))
    assert archiving._own_archive(str(archiving.archives_dir() / "ok.zip")).name == "ok.zip"


def test_marketplace_never_synced():
    assert "marketplace" in store.APP_CONFIG_LOCAL_ONLY


def test_git_neutralised_and_notify_dashdash():
    root = Path(__file__).resolve().parents[1] / "voktora"
    git = (root / "ai_git.py").read_text(encoding="utf-8")
    assert "core.hooksPath=/dev/null" in git and "core.fsmonitor=false" in git and "--no-ext-diff" in git
    assert '"--"' in (root / "notifications.py").read_text(encoding="utf-8")
