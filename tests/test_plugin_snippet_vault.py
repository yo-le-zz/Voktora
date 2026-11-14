"""Snippet Vault : stockage, recherche par portée, export/import Markdown, interface."""

from pathlib import Path

import pytest
from plugin_stub import StubApi, load_plugin, submodule


@pytest.fixture(scope="module")
def plg():
    return load_plugin("snippet-vault"), submodule("snippet-vault", "core")


def test_vault_crud_and_persistence(plg, tmp_path):
    _m, core = plg
    v = core.Vault(tmp_path / "v" / "s.json")
    a = v.add("Boucle", "for i in x: pass", "python", ["Boucle", "#py"])
    assert a.id and v.update(a.id, title="  ", code="x").title == "Sans titre"
    assert core.Vault(tmp_path / "v" / "s.json").items[a.id].code == "x"           # relu depuis le disque
    assert v.delete(a.id) and not v.delete(a.id) and core.Vault(tmp_path / "v" / "s.json").items == {}
    (tmp_path / "v" / "s.json").write_text("{ pas du json")
    assert core.Vault(tmp_path / "v" / "s.json").items == {}                        # fichier corrompu : repart vide
    (tmp_path / "v" / "s.json").write_text('[{"id": "1"}, 3, {"id": "2", "title": "ok", "tags": ["t"]}]')
    assert list(core.Vault(tmp_path / "v" / "s.json").items) == ["2"]


def test_tags_and_search_scoping(plg, tmp_path):
    _m, core = plg
    assert core.parse_tags("Web, #api;  web ,,") == ["web", "api"]
    v = core.Vault(tmp_path / "s.json")
    v.add("Requête HTTP", "requests.get(url)", "python", ["http"])
    v.add("Secret projet A", "token", "", [], project="/p/a")
    v.add("Secret projet B", "token", "", [], project="/p/b")
    titles = lambda **k: [s.title for s in v.search(**k)]  # noqa: E731
    assert titles(project="/p/a") == ["Secret projet A", "Requête HTTP"] or set(titles(project="/p/a")) == {"Secret projet A", "Requête HTTP"}
    assert "Secret projet B" not in titles(project="/p/a") and titles(project="/p/a", only_project=True) == ["Secret projet A"]
    assert titles(query="http", project="") == ["Requête HTTP"] and titles(query="requests.get") == ["Requête HTTP"]
    assert titles(tag="http") == ["Requête HTTP"] and titles(query="zzz") == []
    assert v.all_tags() == ["http"]
    ranked = core.Vault(tmp_path / "r.json")
    ranked.add("autre", "def parse(): ...")
    ranked.add("parse", "x")
    assert [s.title for s in ranked.search("parse")] == ["parse", "autre"]            # titre avant code


def test_markdown_export_import_roundtrip(plg, tmp_path):
    _m, core = plg
    v = core.Vault(tmp_path / "s.json")
    v.add("Avec fence", "a\n```\nb\n```", "markdown", ["doc"])
    v.add("Simple", "print(1)", "python")
    md = core.to_markdown(v.search())
    assert "````markdown" in md and "Étiquettes : `doc`" in md
    got = {t: (lang, code) for t, lang, code in core.import_markdown_free(md)}
    assert got["Simple"] == ("python", "print(1)") and got["Avec fence"] == ("markdown", "a\n```\nb\n```")


def test_tab_flow(plg, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    mod, _core = plg
    api = StubApi(tmp_path / "d")
    mod.on_load(api)
    tab = api.tabs[0][1](None)
    tab.set_project(Path("/p/a"))
    tab.title.setText("Mon snippet")
    tab.tags.setText("Un, deux")
    tab.language.setCurrentText("python")
    tab.code.setPlainText("print('x')")
    tab.save()
    assert tab.list.count() == 1 and tab.state.text() == "Enregistré" and tab.tag.count() == 3
    tab.code.setPlainText("print('y')")
    tab.save()                                            # mise à jour, pas de doublon
    assert tab.list.count() == 1
    tab.project_only.setChecked(True)
    tab.save()
    tab.set_project(Path("/p/b"))
    assert tab.list.count() == 0                          # réservé au projet A
    tab.set_project(Path("/p/a"))
    assert tab.list.count() == 1
    tab.list.setCurrentRow(0)
    tab.copy()
    assert api.clipboard == "print('y')"
    api.choice = "Mon snippet"
    api.current_project = lambda: Path("/p/a")
    api.palette[0][1]()
    assert api.clipboard == "print('y')"
    tab.delete()
    assert tab.list.count() == 0 and tab.title.text() == ""
    tab.export()
    assert "# Snippets" in api.clipboard
