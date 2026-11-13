"""Project Knowledge : BM25, indexation incrémentale, symboles/rôles, wiki (liens, péremption), diagrammes, exports, interface."""

import importlib
import sys
import types
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent / "marketplace" / "plugins" / "project-knowledge"


@pytest.fixture(scope="module")
def pk():
    pkg = types.ModuleType("project_knowledge")
    pkg.__path__ = [str(PLUGIN)]
    sys.modules["project_knowledge"] = pkg
    yield
    for n in [n for n in sys.modules if n == "project_knowledge" or n.startswith("project_knowledge.")]:
        del sys.modules[n]


def mod(n):
    return importlib.import_module("project_knowledge." + n)


@pytest.fixture
def proj(tmp_path):
    r = tmp_path / "demo"
    files = {
        "main.py": '"""Entrée."""\nfrom core.engine import run_engine\n\nif __name__ == "__main__":\n    run_engine()\n',
        "core/__init__.py": "",
        "core/engine.py": 'class Engine:\n    """Moteur de calcul des factures."""\n    def compute_invoice(self, amount):\n        return amount * 1.2\n\n'
                          'def run_engine():\n    """Lance le moteur."""\n    return Engine().compute_invoice(10)\n\ndef _private():\n    pass\n',
        "ui/window.py": "from core import engine\n\ndef open_window():\n    return engine.run_engine()\n",
        "tests/test_engine.py": "def test_x():\n    assert True\n",
        "src/lib.rs": "pub fn add(a: i32) -> i32 { a }\nstruct Point;\nmod util;\nuse crate::util;\n",
        "web/app.js": "export function startApp() {}\nimport { x } from './helper.js';\n",
        "web/helper.js": "export const x = () => 1;\n",
        "README.md": "# Demo\n\nUn projet de facturation.\n",
        "Cargo.toml": "[package]\nname='d'\n",
        ".gitignore": "ignored/\n*.log\n",
        "ignored/secret.py": "x = 1\n",
        "debug.log": "x",
        "node_modules/a.js": "x",
    }
    for rel, text in files.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return r


def test_tokenizer(pk):
    t = mod("core.text").tokens
    assert t("getUserName") == ["getusername", "get", "user", "name"]
    assert t("snake_case_é") == ["snake_case_e", "snake", "case"] or "snake" in t("snake_case_é")
    assert "le" not in t("le chat") and t("Éléphant") == ["elephant"]


def test_bm25_ranking_remove_persist(pk):
    B = mod("core.bm25").BM25
    b = B()
    b.add("a", "facture client calcul facture")
    b.add("b", "calcul de la taxe")
    b.add("c", "interface fenêtre bouton")
    assert b.search("facture")[0][0] == "a" and b.search("calcul")[0][0] in ("a", "b")
    assert b.search("fact")[0][0] == "a"                    # préfixe
    assert b.search("introuvable") == [] and b.search("") == []
    r = B.from_dict(b.to_dict())
    assert r.search("taxe")[0][0] == "b" and len(r) == 3
    b.remove("a")
    assert b.search("facture") == [] and len(b) == 2 and "facture" not in b.post
    s = b.similar("calcul taxe")
    assert s[0][0] == "b" and 0 < s[0][1] <= 1.0001


def test_symbols_roles_imports(pk):
    sy = mod("core.symbols")
    py = sy.extract("a.py", "python", "class A(Base):\n    '''Doc A.'''\n    def m(self, x, *a, **k): ...\n\nasync def f(): ...\ndef _p(): ...\n")
    names = {(s["name"], s["kind"], s["public"]) for s in py}
    assert ("A", "class", True) in names and ("m", "method", True) in names and ("f", "function", True) in names and ("_p", "function", False) in names
    assert next(s for s in py if s["name"] == "m")["signature"] == "def m(self, x, *a, **k)"
    assert [s["name"] for s in sy.extract("x.rs", "rust", "pub fn a() {}\nstruct B;\npub(crate) enum C {}\n")] == ["a", "B", "C"]
    assert {s["name"] for s in sy.extract("x.js", "javascript", "export function f(){}\nclass K {}\nconst g = (a) => 1\n")} == {"f", "K", "g"}
    assert sy.extract("bad.py", "python", "def (:") == []
    assert sy.imports("python", "import os\nfrom .a import b\nfrom x.y import z") == ["os", ".a", ".a.b", "x.y", "x.y.z"]
    assert sy.imports("javascript", "import a from './a.js'\nconst b = require('b')") == ["./a.js", "b"]
    assert sy.role_of("tests/test_x.py", "python") == "test" and sy.role_of("main.py", "python") == "entrée"
    assert sy.role_of("docs/a.md", "markdown") == "documentation" and sy.role_of("Cargo.toml", "toml") == "build"
    assert sy.role_of("ui/dialog.py", "python") == "interface" and sy.role_of("core/x.py", "python") == "service"


def test_index_scan_incremental_and_search(pk, proj):
    ix = mod("core.index").ProjectIndex(proj)
    rep = ix.update()
    assert "ignored/secret.py" not in ix.files and "debug.log" not in ix.files and not any("node_modules" in f for f in ix.files)
    assert rep["added"] and not rep["modified"] and ix.stats()["symbols"] >= 8
    again = ix.update()
    assert not (again["added"] or again["modified"] or again["removed"]) and again["unchanged"] == len(ix.files)
    (proj / "core/engine.py").write_text((proj / "core/engine.py").read_text() + "\ndef nouvelle_fonction():\n    pass\n")
    (proj / "README.md").unlink()
    third = ix.update()
    assert third["modified"] == ["core/engine.py"] and third["removed"] == ["README.md"] and any("nouvelle_fonction" in s for s in third["symbols_added"])
    assert ix.search("moteur factures")[0]["path"] == "core/engine.py"
    hit = ix.search("compute_invoice")[0]
    assert hit["path"] == "core/engine.py" and "compute_invoice" in hit["snippet"] and hit["role"] == "service"
    assert "core/engine.py" in [h["path"] for h in ix.search("Engine", "similar")[:3]]
    edges = set(ix.internal_imports())
    assert ("main.py", "core/engine.py") in edges and ("ui/window.py", "core/engine.py") in edges and ("web/app.js", "web/helper.js") in edges
    import threading
    ev = threading.Event()
    ev.set()
    (proj / "x.py").write_text("y=1")
    with pytest.raises(RuntimeError):
        ix.update(cancel=ev)
    restored = mod("core.index").ProjectIndex.from_dict(proj, ix.to_dict())
    assert restored.search("moteur")[0]["path"] == "core/engine.py" and len(restored.files) == len(ix.files)


def test_wiki_links_stale_generated(pk, proj):
    w, ix = mod("core.wiki"), mod("core.index").ProjectIndex(proj)
    ix.update()
    wk = w.Wiki()
    assert set(wk.generate(ix, "demo", ix.changes)) == set(w.GENERATED)
    assert wk.generate(ix, "demo", ix.changes) == []                         # idempotent
    wk.set_page("Facturation", "# F\nVoir [[Architecture]], [[Inexistante|x]] et `core/engine.py`.", index=ix)
    wk.set_page("Orpheline", "texte")
    assert wk.broken_links() == [{"page": "Facturation", "target": "Inexistante"}]
    assert "Facturation" in wk.backlinks("Architecture") and "Orpheline" in wk.orphans()
    assert wk.stale(ix) == []
    (proj / "core/engine.py").write_text("def autre(): pass\n")
    ix.update()
    assert wk.stale(ix) == [{"page": "Facturation", "files": ["core/engine.py"]}]
    wk.mark_fresh("Facturation", ix)
    assert wk.stale(ix) == []
    wk.set_page("Architecture", "# mon architecture à moi")                 # page manuelle du même nom
    wk.generate(ix, "demo", ix.changes)
    assert wk.pages["Architecture"]["text"] == "# mon architecture à moi"
    assert "API interne" in wk.pages and "autre" in wk.pages["API interne"]["text"]
    with pytest.raises(ValueError):
        wk.set_page(" ", "x")
    html = w.md_to_html("# T\n- a [[Facturation]]\n- b [[Rien]]\n```\n<x>\n```\n| a | b |\n|---|---|\n| 1 | 2 |\n**g** `c`", exists=lambda n: n == "Facturation")
    assert 'class="wiki"' in html and 'class="broken"' in html and "&lt;x&gt;" in html and "<table>" in html and "<strong>g</strong>" in html
    assert "<script" not in w.md_to_html("<script>alert(1)</script>")


def test_diagram_and_apidoc(pk, proj):
    d, ix = mod("core.diagrams"), mod("core.index").ProjectIndex(proj)
    ix.update()
    svg = d.svg(sorted(ix.files), ix.internal_imports())
    import xml.dom.minidom as md
    md.parseString(svg)
    assert "core/engine.py" in svg and "marker-end" in svg
    big = [f"d{i % 7}/f{i}.py" for i in range(200)]
    nodes, _ = d.group_edges(big, [(big[0], big[1]), (big[0], big[8])])
    assert len(nodes) <= 60
    assert d.layers(["a", "b"], [("a", "b"), ("b", "a")])                       # cycle : pas de boucle infinie
    doc = mod("core.apidoc").api_markdown(ix)
    assert "class Engine" in doc and "Moteur de calcul" in doc and "_private" not in doc


def test_exports(pk, proj, tmp_path):
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    K, ex, store = mod("services.knowledge").Knowledge, mod("core.exporters"), mod("storage.store").Store(tmp_path / "s")
    k = K(store, proj)
    rep = k.refresh()
    assert rep["pages_updated"]
    k.save_page("Notes", "# Notes\nVoir [[Vue d'ensemble]] et [[Absente]].")
    md = ex.to_markdown(k.wiki, "demo", k.index)
    assert "Notes" in md and "Vue d'ensemble" in md
    svg = k.wiki.diagram_svg(k.index)
    html = ex.to_html(k.wiki, "demo", svg)
    assert "<svg" in html and 'href="#notes"' in html and "https://cdn" not in html
    out = tmp_path / "site"
    written = ex.to_site(k.wiki, "demo", out, svg)
    assert (out / "index.html").exists() and (out / "search.js").exists() and "notes.html" in written
    assert 'class="broken"' in (out / "notes.html").read_text()
    assert "Pages liées" in (out / (mod("core.wiki").slug("Vue d'ensemble") + ".html")).read_text()
    assert "idx=" in (out / "search.js").read_text().replace(" ", "")
    pdf = tmp_path / "k.pdf"
    ex.to_pdf(k.wiki, "demo", pdf, svg)
    assert pdf.read_bytes().startswith(b"%PDF") and pdf.stat().st_size > 1500
    again = K(store, proj)                                                       # rechargé depuis le disque
    assert again.wiki.pages["Notes"]["text"].startswith("# Notes") and again.index.search("moteur")


def test_widget(pk, proj, tmp_path):
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    w = mod("ui.widget").KnowledgeWidget(mod("storage.store").Store(tmp_path / "s"))
    w.set_project(proj)
    assert "Premier lancement" in w.status.text()
    w.refresh()
    assert "Index : +" in w.status.text() and w.pages.count() >= 5 and w.syms.rowCount() > 5
    w.q.setText("facture")
    w.search()
    assert w.results.rowCount() >= 1 and w.results.item(0, 0).text()
    w.new_page("Ma page")
    w.pages.setCurrentRow(w.pages.findItems("Ma page", __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.MatchStartsWith) and 0)
    w.show_page("Ma page")
    w.editor.setPlainText("# Ma page\nLien [[Cassé]]")
    assert w.save_page() and "1 lien(s) cassé(s)" in w.issues.text()
    assert Path(w.do_export(str(tmp_path / "e.md"), "Markdown")).exists()
    assert Path(w.do_export(str(tmp_path / "e.html"), "HTML")).exists()
