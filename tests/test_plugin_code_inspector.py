"""Code Inspector : analyseurs, liaison des relations (certitudes), pont Python × Rust, cache incrémental, exports, interface."""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent / "marketplace" / "plugins" / "code-inspector"


@pytest.fixture(scope="module")
def ci():
    pkg = types.ModuleType("code_inspector")
    pkg.__path__ = [str(PLUGIN)]
    sys.modules["code_inspector"] = pkg
    yield importlib.import_module("code_inspector.core.engine").__package__.split(".")[0]
    for name in [n for n in sys.modules if n == "code_inspector" or n.startswith("code_inspector.")]:
        del sys.modules[name]


def mod(name):
    return importlib.import_module("code_inspector." + name)


def write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


PY_PROJECT = {
    "app/__init__.py": "",
    "app/util.py": "def helper(x):\n    return x + 1\n\ndef unused_fn():\n    return 0\n",
    "app/models.py": "class Base:\n    def save(self):\n        return 1\n\nclass User(Base):\n    def rename(self, name):\n        self.name = name\n        return self.save()\n",
    "app/main.py": ("import os\nfrom app.util import helper\nfrom app.models import User\n\n"
                    "def run():\n    u = User()\n    u.rename('a')\n    return helper(2)\n\n"
                    "def dyn(name):\n    return getattr(os, name)()\n\n"
                    "if __name__ == '__main__':\n    run()\n"),
    "requirements.txt": "requests>=2.0\nflask==0.12\n",
}


def edge(a, src_suffix, dst_suffix, kind="calls"):
    for e in a.graph.edges:
        if e.kind == kind and e.src.endswith(src_suffix) and e.dst.endswith(dst_suffix):
            return e
    return None


def test_python_relations_and_certainty(ci, tmp_path):
    root = write(tmp_path / "p", PY_PROJECT)
    a = mod("core.engine").analyze(root)
    e = edge(a, "main.py::run", "util.py::helper")
    assert e and e.certainty == "certain"
    imp = edge(a, "app/main.py", "app/util.py", "imports")
    assert imp and imp.certainty == "certain"
    assert edge(a, "models.py::User", "models.py::Base", "inherits")
    # self.save() trouvé dans la classe parente : certain ; appel via variable typée (u = User()) : au mieux probable
    assert edge(a, "User.rename", "Base.save").certainty == "certain"
    ren = edge(a, "main.py::run", "User.rename")
    assert ren and ren.certainty in ("certain", "probable")
    # getattr dynamique : jamais présenté comme certain
    dyn = [x for x in a.graph.callees("app/main.py::dyn")]
    assert dyn and all(x.certainty == "inconnu" for x in dyn)
    # fonction jamais appelée détectée comme candidate
    assert any(d["name"] == "unused_fn" for d in a.report["dead_code"])
    assert any(e["kind"] == "main-guard" or "main" in e["kind"] for e in a.report["entry_points"])
    assert {d["name"] for d in a.dependencies} >= {"requests", "flask"}


def test_function_card_and_search(ci, tmp_path):
    a = mod("core.engine").analyze(write(tmp_path / "p", PY_PROJECT))
    card = a.graph.function_card("app/util.py::helper")
    assert card["signature"].startswith("def helper") and card["file"] == "app/util.py"
    assert any(c["id"].endswith("main.py::run") for c in card["callers"])
    assert a.graph.search("helper")[0].id == "app/util.py::helper"


RUST_PYO3 = {
    "Cargo.toml": '[package]\nname = "fastlib"\nversion = "0.1.0"\n[lib]\nname = "fastlib"\ncrate-type = ["cdylib"]\n[dependencies]\npyo3 = "0.22"\n',
    "pyproject.toml": '[build-system]\nrequires = ["maturin"]\nbuild-backend = "maturin"\n[tool.maturin]\nmodule-name = "fastlib"\n',
    "src/lib.rs": ('use pyo3::prelude::*;\n\n#[pyfunction]\nfn add(a: i64, b: i64) -> i64 {\n    helper(a) + b\n}\n\n'
                   'fn helper(a: i64) -> i64 { a * 2 }\n\n#[pymodule]\nfn fastlib(m: &Bound<PyModule>) -> PyResult<()> {\n'
                   '    m.add_function(wrap_pyfunction!(add, m)?)?;\n    Ok(())\n}\n\n'
                   'fn back(py: Python<\'_>) -> PyResult<()> {\n    let m = py.import("pycb")?;\n    m.getattr("on_done")?.call0()?;\n    Ok(())\n}\n'),
    "py/pycb.py": "def on_done():\n    return 1\n",
    "py/use.py": "import fastlib\n\ndef go():\n    return fastlib.add(1, 2)\n",
}


def test_rust_structure_and_pyo3_bridge(ci, tmp_path):
    a = mod("core.engine").analyze(write(tmp_path / "m", RUST_PYO3))
    assert edge(a, "lib.rs::add", "lib.rs::helper").certainty == "certain"
    bridge = edge(a, "use.py::go", "lib.rs::add", "ffi")
    assert bridge and bridge.certainty in ("certain", "probable")
    back = edge(a, "lib.rs::back", "pycb.py::on_done", "ffi")
    assert back, "appel Rust → Python via import/getattr/call0 attendu"
    assert "fastlib" in a.report["ffi"]["native_modules"]
    sp = mod("exporters.specific")
    assert sp.mixed_data(a)["bridges"]
    assert sp.rust_data(a)["crates"][0]["package"] == "fastlib"
    assert any(f["classes"] == [] for f in sp.python_data(a)["modules"])


def test_ctypes_subprocess_bridges(ci, tmp_path):
    root = write(tmp_path / "c", {
        "Cargo.toml": '[package]\nname = "core_ffi"\nversion = "0.1.0"\n[lib]\ncrate-type = ["cdylib"]\n',
        "src/lib.rs": '#[no_mangle]\npub extern "C" fn compute(x: i32) -> i32 { x }\n',
        "load.py": 'import ctypes\nlib = ctypes.CDLL("libcore_ffi.so")\n\ndef call():\n    return lib.compute(3)\n',
    })
    a = mod("core.engine").analyze(root)
    assert edge(a, "load.py", "lib.rs::compute", "ffi") or edge(a, "load.py::call", "lib.rs::compute", "ffi")


def test_javascript_and_cpp(ci, tmp_path):
    root = write(tmp_path / "j", {
        "a.js": "import { b } from './b.js';\nexport function a() { return b(); }\n",
        "b.js": "export function b() { return 1; }\n",
        "m.cpp": '#include "u.h"\nint main() { return twice(2); }\n',
        "u.h": "int twice(int x);\n",
        "u.cpp": '#include "u.h"\nint twice(int x) { return x * 2; }\n',
    })
    a = mod("core.engine").analyze(root)
    assert edge(a, "a.js::a", "b.js::b").certainty == "certain"
    assert edge(a, "m.cpp::main", "twice")


def test_incremental_cache(ci, tmp_path):
    eng, store_mod = mod("core.engine"), mod("storage.store")
    root = write(tmp_path / "p", PY_PROJECT)
    store = store_mod.Store(tmp_path / "cache")
    first = eng.analyze(root, store)
    assert first.stats["analyzed"] == first.stats["scanned"] > 0
    second = eng.analyze(root, store)
    assert second.stats["analyzed"] == 0 and second.stats["reused"] == first.stats["scanned"]
    (root / "app/util.py").write_text("def helper(x):\n    return x + 2\n")
    third = eng.analyze(root, store)
    assert third.stats["analyzed_files"] == ["app/util.py"]
    assert third.graph.to_dict()["nodes"]  # graphe reconstruit complet
    forced = eng.analyze(root, store, force=True)
    assert forced.stats["analyzed"] == forced.stats["scanned"]


def test_cancel(ci, tmp_path):
    import threading
    ev = threading.Event()
    ev.set()
    with pytest.raises(mod("core.engine").Cancelled):
        mod("core.engine").analyze(write(tmp_path / "p", PY_PROJECT), cancel=ev)


def test_quality_issues(ci, tmp_path):
    root = write(tmp_path / "q", {"bad.py": ("import json\n\ndef f(x=[]):\n    try:\n        eval(x)\n    except:\n        pass\n"
                                              "PASSWORD = 'supersecret123'\n"),
                                  "requirements.txt": "django==1.8\n"})
    a = mod("core.engine").analyze(root)
    codes = {i.code for i in a.issues}
    assert {"PY-MUTABLE-DEFAULT", "BARE-EXCEPT", "EVAL", "UNUSED-IMPORT"} <= codes
    assert any("SECRET" in c for c in codes)
    assert any(d["name"].lower() == "django" and d["problems"] for d in a.dependencies)


def test_ignore_rules(ci, tmp_path):
    root = write(tmp_path / "i", {"keep.py": "x = 1\n", "skip/dropped.py": "y = 2\n", ".gitignore": "skip/\n", "node_modules/z.js": "1"})
    a = mod("core.engine").analyze(root)
    assert "keep.py" in a.files and "skip/dropped.py" not in a.files and not any("node_modules" in p for p in a.files)


def test_views_and_layout(ci, tmp_path):
    a = mod("core.engine").analyze(write(tmp_path / "p", PY_PROJECT))
    v, lay = mod("services.views"), mod("services.layout")
    for build in (lambda: v.architecture(a.graph), lambda: v.files(a.graph), lambda: v.classes(a.graph), lambda: v.calls(a.graph),
                  lambda: v.ffi(a.graph)):
        view = build()
        lo = lay.layout(view)
        assert set(lo["pos"]) == {n["id"] for n in view["nodes"]} and lo["width"] >= 0
    ch = v.chains(a.graph, a.report["entry_points"])
    assert ch and any("run" in s for p in ch[0]["chains"] for s in p["steps"])


def test_exports(ci, tmp_path):
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    a = mod("core.engine").analyze(write(tmp_path / "m", {**PY_PROJECT, **RUST_PYO3}))
    exp = mod("exporters")
    out = {}
    for kind, ext in exp.FORMATS.items():
        p = tmp_path / f"o_{kind}{ext}"
        exp.export(a, kind, p)
        out[kind] = p
        assert p.stat().st_size > 20, kind
    json.loads(out["json"].read_text())
    import xml.dom.minidom as md
    md.parseString(out["svg"].read_text())
    assert "Code Inspector" in out["html"].read_text() and "<svg" in out["html"].read_text()
    assert "http://cdn" not in out["html"].read_text() and "https://cdn" not in out["html"].read_text()
    assert "```mermaid" in out["md"].read_text()
    assert out["pdf"].read_bytes().startswith(b"%PDF")
    assert "pont" in out["mixed"].read_text().lower() or "Direction" in out["mixed"].read_text()


def test_analysis_of_voktora_itself(ci):
    src = Path(__file__).resolve().parent.parent / "voktora"
    a = mod("core.engine").analyze(src)
    assert a.report["languages"][0]["name"] == "Python" and len(a.files) > 80
    e = edge(a, "ai_providers.py::generate", "_request")
    assert e and e.certainty == "certain"
    assert a.graph.stats()["certainties"]["certain"] > 100


def test_widget(ci, tmp_path):
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    wmod = mod("ui.widget")
    root = write(tmp_path / "p", PY_PROJECT)
    w = wmod.InspectorWidget(store=mod("storage.store").Store(tmp_path / "c"), run_async=lambda work, ok, err: ok(work()))
    w.set_project(root)
    w.analyze()
    assert "Terminé" in w.status.text() and w.tree.topLevelItemCount() > 0
    for i in range(w.view_combo.count()):
        w.view_combo.setCurrentIndex(i)
    w.select_node("app/util.py::helper")
    assert "helper" in w.card.toPlainText()
    w.search.setText("helper")
    assert w.results.count() >= 1
    w.export_kind.setCurrentIndex(w.export_kind.findData("md"))
    assert Path(w.do_export(str(tmp_path / "r.md"))).exists()
