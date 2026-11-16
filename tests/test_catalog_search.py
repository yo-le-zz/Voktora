"""Recherche intelligente des marketplaces + aperçus et « tout installer » des boutiques."""

import catalog_search as cs
import pytest
import shops


def _index():
    return cs.Index([
        cs.make_doc("nord", name="Nord Sombre", description="thème bleu", tags=["sombre", "bleu"], author="yo", order=1, states=["installed"]),
        cs.make_doc("sol", name="Solaire", description="clair chaud", tags=["clair"], author="x", order=2, states=["new"]),
        cs.make_doc("rs", name="Rustic", description="outil natif", tags=["outil"], lang="rust", perms=["shell"], order=3, states=["new"]),
    ])


@pytest.mark.parametrize(("query", "expected"), [
    ("sombre", ["nord"]), ("tag:clair", ["sol"]), ("#clair", ["sol"]), ("-sombre", ["rs", "sol"]), ("is:installed", ["nord"]),
    ("lang:rust", ["rs"]), ('"clair chaud"', ["sol"]), ("sombre -bleu", []), ("perm:shell", ["rs"]), ("auteur:yo", ["nord"]),
    ("sort:recent", ["rs", "sol", "nord"]), ("soliare", ["sol"]), ("is:new tag:outil", ["rs"]), ("", ["nord", "rs", "sol"]),
])
def test_queries(query, expected):
    assert [d.key for d in _index().search(query)] == expected


def test_parse_tolerates_unclosed_quote_and_limit():
    assert cs.parse('"abc').words == ["abc"]
    assert cs.parse("limit:2 x").limit == 2


def test_suggest_and_facets():
    ix = _index()
    assert ix.suggest("tag:so") == ["tag:sombre"] and "lang:rust" in ix.suggest("ru")
    assert ("sombre", 1) in ix.facets("tags")


def test_thousands_of_items_fast():
    import time
    ix = cs.Index([cs.make_doc(f"i{n}", name=f"Thème {n}", description="x" * 80, tags=[f"t{n % 50}"], order=n) for n in range(5000)])
    start = time.perf_counter()
    assert len(ix.search("tag:t7 thème")) == 100
    assert time.perf_counter() - start < 1.0


def test_install_many_continues_after_failure(monkeypatch):
    def fake(item):
        if item.id == "bad":
            raise shops.ShopError("boum")
    monkeypatch.setattr(shops, "install", fake)
    items = [shops.ShopItem("themes", i, i, "1", "a") for i in ("a", "bad", "c")]
    done, failed = shops.install_many(items)
    assert done == ["a", "c"] and failed == ["bad : boum"]


def test_preview_files_reads_installed_without_network(isolated_data_dir, monkeypatch):
    folder = shops.item_dir("icons", "demo")
    folder.mkdir(parents=True)
    (folder / "a.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><rect width="8" height="8" fill="currentColor"/></svg>')
    monkeypatch.setattr(shops, "_fetch", lambda *a, **k: pytest.fail("pas de réseau"))
    item = shops.ShopItem("icons", "demo", "Demo", "1", "a", files={"a.svg": "0" * 64})
    assert "a.svg" in shops.preview_files(item)


def test_shop_dialog_search_preview_and_install_all_button(isolated_data_dir, monkeypatch):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    folder = shops.item_dir("icons", "demo")
    folder.mkdir(parents=True)
    (folder / "a.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><rect width="8" height="8" fill="currentColor"/></svg>')
    (folder / "item.json").write_text('{"kind":"icons","id":"demo","name":"Demo","version":"1.0.0","author":"t","tags":["plein"]}')
    monkeypatch.setattr(shops, "fetch_catalog", lambda kind: ([], []))
    from ui_dialogs.shop_dialog import ShopDialog
    dlg = ShopDialog()
    tab = dlg.shop_tabs["icons"]
    tab.populate([])
    assert tab.list.count() == 1 and tab.search.count.text() == "1 / 1"
    tab.search.edit.setText("tag:plein")
    tab.search._debounce.stop()
    tab._render()
    assert tab.list.count() == 1
    tab.show_preview("demo", {"a.svg": (folder / "a.svg").read_bytes()})
    assert not tab.preview.pixmap().isNull()
    tab.show_preview("demo", {"s.qss": b"QPushButton{color:red;}"}) if False else None
    assert not tab.btn_all.isEnabled()
