"""Boutiques d'apparence 1.1.1 : index par type, installation vérifiée, thèmes/icônes/styles, plugins."""

import hashlib
import json
from pathlib import Path

import icons
import pytest
import shops
import theme_manager

REPO = Path(__file__).resolve().parent.parent
MARKET = REPO / "marketplace"


@pytest.fixture
def served(isolated_data_dir, monkeypatch):
    """Sert marketplace/ en mémoire à la place du réseau."""
    def fake(url, limit=shops.MAX_FILE_BYTES):
        base = shops.DEFAULT_BASE
        assert url.startswith(base)
        path = MARKET / url[len(base) + 1:]
        if not path.is_file():
            raise shops.ShopError("404")
        return path.read_bytes()
    monkeypatch.setattr(shops, "_fetch", fake)


def test_catalogs_and_neon_moved_out_of_plugins(served):
    themes, errors = shops.fetch_catalog("themes")
    assert not errors and {"neon-night", "coffee", "mint"} <= {t.id for t in themes}
    assert not (MARKET / "plugins" / "neon-themes").exists()
    assert shops.fetch_catalog("icons")[0] and shops.fetch_catalog("styles")[0]


def test_install_theme_and_use_it(served):
    item = next(t for t in shops.fetch_catalog("themes")[0] if t.id == "neon-night")
    shops.install(item)
    assert "neon-night" in theme_manager.get_available_themes()
    assert theme_manager.load_theme("neon-night")["colors"]["base"]
    assert shops.uninstall("themes", "neon-night") and "neon-night" not in theme_manager.get_available_themes()


def test_tampered_file_is_rejected(served, monkeypatch):
    item = next(t for t in shops.fetch_catalog("themes")[0] if t.id == "mint")
    item.files["theme.json"] = hashlib.sha256(b"autre").hexdigest()
    with pytest.raises(shops.ShopError, match="empreinte"):
        shops.install(item)
    assert shops.installed("themes") == []


def test_icon_pack_overrides_and_falls_back(served, qapp_offscreen=None):
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    assert _app is not None
    icons.load()
    pack = shops.fetch_catalog("icons")[0][0]
    shops.install(pack)
    shops.set_icon_pack(pack.id)
    assert shops.icon_file("folder").name == "folder.svg" and shops.icon_file("zzz") is None
    assert not icons.icon("mdi:folder").isNull() and not icons.icon("mdi:home").isNull()
    shops.uninstall("icons", pack.id)
    assert shops.active_icon_pack() == ""


def test_styles_enabled_in_stylesheet(served):
    style = next(s for s in shops.fetch_catalog("styles")[0] if s.id == "arrondi")
    shops.install(style)
    assert shops.extra_stylesheet() == ""
    shops.set_style_enabled("arrondi", True)
    assert "border-radius" in shops.extra_stylesheet()
    assert "border-radius" in theme_manager._build_qss(theme_manager.load_theme("default")) + shops.extra_stylesheet()


@pytest.mark.parametrize("kind,name,data", [
    ("icons", "x.svg", b"<svg><script>alert(1)</script></svg>"),
    ("icons", "x.svg", b"<svg onload='x()'/>"),
    ("icons", "x.svg", b"<svg><image href='http://evil/x.png'/></svg>"),
    ("styles", "x.qss", b"QWidget { background: url(http://evil/x.png); }"),
    ("themes", "t.json", b"{pas du json"),
])
def test_active_content_refused(kind, name, data):
    with pytest.raises(shops.ShopError):
        shops.check_content(kind, name, data)


@pytest.mark.parametrize("name", ["../x.json", "/abs.json", "a\\b.json", ".caché.json", "x.exe", "x.py"])
def test_unsafe_names_refused(name):
    with pytest.raises(shops.ShopError):
        shops.safe_name("themes", name)


def test_sources_user_and_plugin(isolated_data_dir):
    with pytest.raises(shops.ShopError):
        shops.add_source("themes", "x", "http://pas-https.example")
    shops.add_source("themes", "Ma boutique", "https://exemple.org/market")
    undo = shops.register_plugin_source("mon-plugin", "themes", "Boutique plugin", "https://plugin.example/m")
    urls = [u for _n, u in shops.sources("themes")]
    assert "https://exemple.org/market" in urls and "https://plugin.example/m" in urls
    undo()
    assert "https://plugin.example/m" not in [u for _n, u in shops.sources("themes")]


def test_install_local_folder(isolated_data_dir, tmp_path):
    folder = tmp_path / "mon-theme"
    folder.mkdir()
    (folder / "item.json").write_text(json.dumps({"id": "mon-theme", "name": "Mon thème", "version": "1.0.0", "author": "moi"}))
    (folder / "theme.json").write_text(json.dumps({"colors": {"base": "#101010"}}))
    shops.install_local("themes", folder)
    assert "mon-theme" in shops.installed_themes()


def test_shop_dialog_opens(served):
    from PySide6.QtWidgets import QApplication
    from ui_dialogs import ShopDialog
    _app = QApplication.instance() or QApplication([])
    icons.load()
    dlg = ShopDialog()
    assert dlg.tabs.count() == 3
    dlg.shop_tabs["themes"].populate(shops.fetch_catalog("themes")[0])
    assert dlg.shop_tabs["themes"].list.count() >= 6
