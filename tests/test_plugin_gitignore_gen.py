"""Gitignore Generator : modèles, détection, fusion sans doublons, dialogue."""

import pytest
from plugin_stub import StubApi, load_plugin, submodule


@pytest.fixture(scope="module")
def plg():
    return load_plugin("gitignore-gen"), submodule("gitignore-gen", "core")


def test_templates_are_sane(plg):
    _m, core = plg
    names = core.names()
    assert len(names) >= 20 and {"Python", "Node.js", "Rust", "VS Code", "Environnement"} <= set(names)
    for n in names:
        rules = core.data()["templates"][n]
        assert rules and all(r == r.strip() and r for r in rules), n
        assert len(rules) == len(set(rules)), f"doublon dans {n}"
    assert set(core.data()["detect"]) <= set(names)


def test_detection(plg):
    _m, core = plg
    assert core.detect(["Cargo.toml", "src/main.rs", "web/package.json"]) == ["Node.js", "Rust"] or \
        set(core.detect(["Cargo.toml", "web/package.json"])) == {"Node.js", "Rust"}
    assert core.detect(["app.csproj"]) == [".NET / C#"] and core.detect(["README.md"]) == []


def test_build_and_merge_never_duplicates_or_touches_existing(plg):
    _m, core = plg
    out = core.build(["Rust", "Python"])
    assert out.startswith(core.HEADER) and out.index("── Python") < out.index("── Rust")      # ordre du catalogue
    assert core.build([]) == ""
    existing = "# mes règles\n*.log\n\ntarget/\n"
    merged = core.merge(existing, ["Rust", "Journaux"])
    assert merged.startswith(existing.rstrip("\n"))
    assert merged.count("target/") == 1 and "**/*.rs.bk" in merged
    assert merged.count("*.log") == 1 and "logs/" in merged             # seule la règle manquante de « Journaux » est ajoutée
    assert core.merge(merged, ["Rust", "Journaux"]) == merged           # idempotent
    assert core.merge("", ["Go"]).startswith(core.HEADER)


def test_dialog_writes_gitignore(plg, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    mod, core = plg
    proj = tmp_path / "demo"
    proj.mkdir()
    (proj / "Cargo.toml").write_text("[package]")
    (proj / ".gitignore").write_text("*.tmp\n")
    api = StubApi(tmp_path / "d", proj)
    mod.on_load(api)
    assert api.menu[0][1].startswith("Générer un .gitignore")
    dlg = mod.GitignoreDialog(api, proj)
    assert dlg.selected() == ["Rust"] and dlg.write_btn.isEnabled() and "règle" in dlg.info.text()
    dlg.write()
    text = (proj / ".gitignore").read_text()
    assert text.startswith("*.tmp") and "target/" in text and api.notices
    assert not dlg.write_btn.isEnabled() and dlg.info.text() == "Rien à ajouter"
