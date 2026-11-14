"""TODO Scanner 1.1 : détection dans les commentaires, filtres, exports, options et interface."""

from pathlib import Path

import pytest
from plugin_stub import StubApi, load_plugin, submodule


@pytest.fixture(scope="module")
def plg():
    mod = load_plugin("todo-scanner")
    return mod, submodule("todo-scanner", "scanner")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "demo"
    files = {
        "a.py": "x = 1  # TODO: renommer\n# FIXME(ana): crash au démarrage\nprint('TODO dans une chaîne')\n",
        "src/b.rs": "// HACK contournement\n/* BUG: fuite mémoire */\nlet todo = 1;\n",
        "web/c.js": "/** NOTE: à documenter */\n// XXX\n",
        "README.md": "- [ ] TODO écrire la doc\n",
        "node_modules/x.js": "// TODO ignoré\n",
        "bin.dat": "\x00\x01 TODO binaire",
    }
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return root


def test_only_real_comments_are_matched(plg, project):
    _m, sc = plg
    items, truncated = sc.scan(project)
    kinds = [(i.kind, i.path) for i in items]
    assert not truncated
    assert ("TODO", "a.py") in kinds and ("FIXME", "a.py") in kinds and ("BUG", "src/b.rs") in kinds
    assert not any(i.text.startswith("dans une chaîne") for i in items)          # chaîne ≠ commentaire
    assert not any("node_modules" in i.path or i.path == "bin.dat" for i in items)
    fix = next(i for i in items if i.kind == "FIXME")
    assert fix.author == "ana" and fix.text == "crash au démarrage"
    assert any(i.kind == "NOTE" and i.text == "à documenter" for i in items)        # « */ » retiré
    assert any(i.path == "README.md" and i.kind == "TODO" for i in items)


def test_sorted_by_urgency_and_summary(plg, project):
    _m, sc = plg
    items, _ = sc.scan(project)
    assert [i.kind for i in items][0] == "BUG"
    counts = sc.summarize(items)
    assert list(counts)[:2] == ["BUG", "FIXME"] and counts["TODO"] == 2


def test_custom_markers_and_limits(plg, project):
    _m, sc = plg
    items, _ = sc.scan(project, markers=["HACK"])
    assert {i.kind for i in items} == {"HACK"}
    _items, truncated = sc.scan(project, max_files=2)
    assert truncated


def test_filters_and_exports(plg, project):
    _m, sc = plg
    items, _ = sc.scan(project)
    assert {i.kind for i in sc.filter_items(items, kind="TODO")} == {"TODO"}
    assert len(sc.filter_items(items, query="ANA")) == 1 and sc.filter_items(items, query="zzz") == []
    md = sc.to_markdown(items, "demo")
    assert "# Marqueurs à traiter — demo" in md and "- [ ] `a.py:1` renommer" in md and "## BUG" in md
    assert sc.to_markdown([], "x").strip().endswith("_Aucun marqueur._")
    csv_text = sc.to_csv(items)
    assert csv_text.splitlines()[0] == "type,fichier,ligne,auteur,texte" and "FIXME,a.py,2,ana" in csv_text


def test_parse_list(plg):
    _m, sc = plg
    assert sc.parse_list("todo, fix;  hack", upper=True) == ["TODO", "FIX", "HACK"] and sc.parse_list("") == []


def test_tab_scans_filters_and_copies(plg, project, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    mod, _sc = plg
    api = StubApi(tmp_path / "data")
    mod.on_load(api)
    assert api.options.get("max_files") == 4000 and api.tabs[0][0] == "TODO"
    tab = api.tabs[0][1](None)
    tab.set_project(Path(project))
    assert tab._tree.topLevelItemCount() == 7 and "BUG 1" in tab._summary.text()
    tab._search.setText("mémoire")
    assert tab._tree.topLevelItemCount() == 1
    tab._copy()
    assert "fuite mémoire" in api.clipboard and api.notices
    tab._search.setText("")
    tab.set_project(None)
    assert tab._tree.topLevelItemCount() == 0
