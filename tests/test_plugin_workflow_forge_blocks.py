"""Workflow Forge : schémas typés des blocs, validation des champs, résumés, rétro-compatibilité, historique, modèles et panneau de propriétés (hors écran)."""

import json
import re

import pytest
from plugin_stub import load_plugin, submodule


@pytest.fixture(scope="module")
def forge():
    load_plugin("workflow-forge")
    return type("Mods", (), {n: submodule("workflow-forge", "core." + n) for n in ("blocks", "schema", "templates", "validation", "engine")})


def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def node(forge, type_, id_="n1", **params):
    return forge.schema.upgrade_node({"id": id_, "type": type_, "label": id_, "params": params, "options": {}, "x": 0, "y": 0})


def wf_of(*nodes, edges=()):
    return {"schema": 1, "name": "t", "triggers": [{"kind": "manual"}], "enabled": True,
            "nodes": [{"id": "start", "type": "start", "label": "start", "params": {}, "options": {}, "x": 0, "y": 0}, *nodes],
            "edges": [{"src": s, "port": p, "dst": d} for s, p, d in edges]}


# ------------------------------------------------------------------------------------------------ schémas de tous les blocs
def test_every_block_declares_a_typed_schema(forge):
    b = forge.blocks
    assert len(b.REGISTRY) >= 29
    kinds = set()
    for t, blk in b.REGISTRY.items():
        assert blk.doc and blk.example and blk.summary, t
        names = [q.name for q in blk.params]
        assert len(names) == len(set(names)), t
        for q in blk.params:
            kinds.add(q.kind)
            assert q.kind in b.KINDS, (t, q.name)
            assert q.label and q.help or q.kind in ("bool", "int") or q.label, (t, q.name)
            if q.kind == "choice":
                assert q.choices and q.default in q.choices, (t, q.name)
                assert not q.choice_labels or len(q.choice_labels) == len(q.choices), (t, q.name)
            if q.minimum is not None and q.maximum is not None:
                assert q.minimum <= q.default <= q.maximum, (t, q.name)
            issue = forge.schema.validate_param(t, q, q.default)
            assert issue is None or (issue.is_error and q.required and str(q.default) == ""), (t, q.name, issue)
        for ref in re.findall(r"\{(\w+)\}", blk.summary):
            assert ref in names, (t, ref)
    assert {"str", "text", "code", "int", "duration", "bool", "choice", "path", "var", "expr", "pairs"} <= kinds
    cat = b.catalog()
    assert {c["type"] for c in cat} == set(b.REGISTRY) and all("label" in p and "mode" in p for c in cat for p in c["params"])


def test_menus_list_their_choices(forge):
    http = forge.blocks.REGISTRY["http_request"]
    method = next(q for q in http.params if q.name == "method")
    assert [v for v, _ in forge.schema.choice_items(method)] == ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
    assert forge.schema.choice_label(method, "POST") == "POST (envoyer)"
    langs = {t for t in forge.blocks.REGISTRY if t.endswith("_script")}
    assert langs == {"python_script", "js_script", "rust_script"}


# ------------------------------------------------------------------------------------------------ validation des champs
def test_param_validation_messages(forge):
    s, reg = forge.schema, forge.blocks.REGISTRY
    p = lambda t, n: next(q for q in reg[t].params if q.name == n)  # noqa: E731
    assert s.validate_param("http_request", p("http_request", "url"), "").message == "Ce champ est obligatoire."
    assert "http" in s.validate_param("http_request", p("http_request", "url"), "ftp://x").message
    assert s.validate_param("http_request", p("http_request", "url"), "https://x/{{vars.a}}") is None
    assert "inconnu" in s.validate_param("http_request", p("http_request", "method"), "FETCH").message
    assert "Expression invalide" in s.validate_param("if", p("if", "condition"), "1 +").message
    assert s.validate_param("if", p("if", "condition"), "vars.x > 1") is None
    assert "modèle" in s.validate_param("log", p("log", "message"), "a {{ 1 + }} b").message
    d = p("delay", "seconds")
    assert s.validate_param("delay", d, "abc").message == "Nombre attendu."
    over = s.validate_param("delay", d, 99999)
    assert over.level == "warning" and "maximum 3600" in over.message
    assert s.validate_param("delay", d, 99999, strict_range=True).is_error
    assert s.validate_param("delay", d, "{{vars.n}}") is None
    assert "Entier" in s.validate_param("loop_for", p("loop_for", "max_items"), 2.5).message
    assert "Nom invalide" in s.validate_param("set_var", p("set_var", "name"), "1x").message
    assert "syntaxe" in s.validate_param("python_script", p("python_script", "code"), "def (:").message
    assert s.validate_param("python_script", p("python_script", "code"), "result = 1") is None
    assert "projet" in s.validate_param("read_file", p("read_file", "path"), "../secret").message
    assert "JSON" in s.validate_param("run_command", p("run_command", "env"), "{pas json").message
    assert "invalide" in s.validate_param("run_command", p("run_command", "command"), "echo 'a").message
    assert "régulière" in s.validate_param("project_search", p("project_search", "pattern"), "(").message
    assert s.validate_params("log", {"level": "debug"})["level"].is_error
    assert forge.schema.validate_params("log", {}) == {}


def test_workflow_validation_uses_schema(forge):
    bad = wf_of(node(forge, "http_request", "h", method="FETCH", url="ftp://x"), node(forge, "delay", "d", seconds=99999), edges=[("start", "out", "h"), ("h", "out", "d")])
    r = forge.validation.validate(bad)
    assert any("Méthode" in e for e in r["errors"]) and any("http" in e for e in r["errors"]) and any("maximum" in w for w in r["warnings"])
    good = wf_of(node(forge, "http_request", "h", method="GET", url="https://x.org"), edges=[("start", "out", "h")])
    assert forge.validation.validate(good)["errors"] == []


# ------------------------------------------------------------------------------------------------ résumés
def test_summaries(forge):
    s = forge.schema.summary
    assert s(node(forge, "http_request", method="GET", url="https://api.exemple.fr/x")) == "HTTP GET https://api.exemple.fr/x"
    assert s(node(forge, "set_var", name="n", value="vars.n + 1")) == "n = vars.n + 1"
    assert s(node(forge, "http_request")) == "HTTP GET …"
    assert s(node(forge, "delay", seconds=2.5)) == "Attendre 2.5 s"
    assert s(node(forge, "run_command", command="ls")) == "$ ls"
    long = s(node(forge, "log", message="x" * 300))
    assert len(long) < 80 and long.endswith("…")
    assert "\n" not in s(node(forge, "log", message="a\n\nb"))
    assert s({"type": "inconnu", "params": {}}) == "Bloc inconnu"
    assert s({"type": "start"}) == "Point d'entrée du workflow"
    for t in forge.blocks.REGISTRY:
        assert s(node(forge, t)) and not re.search(r"\{\w+\}", s(node(forge, t)).split("{")[0])
    assert "Exemple" in forge.schema.describe("http_request") and "out.<bloc>.status" in forge.schema.describe("http_request")


def test_palette_search(forge):
    s = forge.schema.search_blocks
    assert [b.type for b in s("parall")] == ["parallel"]
    assert {b.type for b in s("python")} >= {"python_script"}
    assert "http_request" in {b.type for b in s("requête")}
    assert {b.type for b in s("git")} >= {"git_status", "git_pull", "git_head"}
    assert "loop_for" in {b.type for b in s("boucle")} or "loop_for" in {b.type for b in s("chaque")}
    assert s("zzzzzz") == []


# ------------------------------------------------------------------------------------------------ rétro-compatibilité
def test_old_format_still_loads_and_runs(forge, tmp_path):
    old = wf_of(
        {"id": "w", "type": "write_file", "label": "w", "params": {"path": "a.txt", "content": "x", "append": True}, "x": 0, "y": 0},   # ancien format : pas de « mode », pas d'options
        {"id": "h", "type": "http_request", "params": {"method": "GET", "url": "https://x.org", "headers": {"Accept": "a/b"}, "body": "", "timeout": "15"}},
        edges=[("start", "out", "w"), ("w", "out", "h")])
    for n in old["nodes"]:
        n.pop("options", None)
    assert forge.validation.validate(old)["errors"] == []
    up = forge.schema.upgrade_workflow(json.loads(json.dumps(old)))
    w = next(n for n in up["nodes"] if n["id"] == "w")
    assert w["params"]["mode"] == "a" and "append" not in w["params"]
    h = next(n for n in up["nodes"] if n["id"] == "h")
    assert json.loads(h["params"]["headers"]) == {"Accept": "a/b"} and h["params"]["timeout"] == 15 and h["params"]["content_type"] == ""
    (tmp_path / "a.txt").write_text("1")
    only_write = wf_of(old["nodes"][1], edges=[("start", "out", "w")])
    rec = forge.engine.run_workflow(only_write, str(tmp_path))
    assert rec["ok"] and (tmp_path / "a.txt").read_text() == "1x"        # l'ancien « append » est compris par le moteur sans migration
    assert forge.engine.run_workflow(forge.schema.upgrade_workflow(only_write), str(tmp_path))["ok"]
    assert (tmp_path / "a.txt").read_text() == "1xx"


def test_pairs_roundtrip(forge):
    s = forge.schema
    assert s.parse_pairs('{"A": "1", "B": "2"}') == [("A", "1"), ("B", "2")]
    assert s.parse_pairs({"A": 1}) == [("A", "1")] and s.parse_pairs("") == [] and s.parse_pairs("{}") == []
    assert json.loads(s.dump_pairs([("A", "1"), ("", "x"), ("B", "{{vars.v}}")])) == {"A": "1", "B": "{{vars.v}}"}
    with pytest.raises(ValueError):
        s.parse_pairs("[1]")
    assert s.move_pair([1, 2, 3], 0, 1) == [2, 1, 3] and s.move_pair([1, 2], 0, -1) == [1, 2]


# ------------------------------------------------------------------------------------------------ variables, copier/coller, ordre, historique
def test_known_vars_and_outputs(forge):
    w = wf_of(node(forge, "set_var", "a", name="compteur", value="1"), node(forge, "set_var", "b", name="total", value="2"), node(forge, "log", "c"),
              node(forge, "set_var", "z", name="apres", value="3"), edges=[("start", "out", "a"), ("a", "out", "b"), ("b", "out", "c"), ("c", "out", "z")])
    assert forge.schema.known_vars(w, "c") == ["compteur", "total"] and "apres" in forge.schema.known_vars(w)
    assert "out.a.value" in forge.schema.upstream_outputs(w, "c")


def test_copy_paste_duplicate(forge):
    s = forge.schema
    w = wf_of(node(forge, "log", "log1", message="m"), node(forge, "notify", "notify1"), edges=[("start", "out", "log1"), ("log1", "out", "notify1")])
    payload = s.copy_nodes(w, ["start", "log1", "notify1"])
    assert [n["id"] for n in payload["nodes"]] == ["log1", "notify1"] and len(payload["edges"]) == 1       # pas de bloc Démarrage
    ids = s.paste_nodes(w, payload, 40, 40)
    assert ids == ["log2", "notify2"] and len(w["edges"]) == 3 and {"src": "log2", "port": "out", "dst": "notify2"} in w["edges"]
    assert w["nodes"][-1]["x"] == 40 and w["nodes"][-2]["params"]["message"] == "m"
    w["nodes"][-2]["params"]["message"] = "autre"
    assert next(n for n in w["nodes"] if n["id"] == "log1")["params"]["message"] == "m"          # copie profonde
    assert s.duplicate_nodes(w, ["log1"]) == ["log3"]
    assert s.paste_nodes(w, {"x": 1}) == [] and s.clip_parse("pas du json") is None and s.clip_parse(s.clip_text(payload))["nodes"]


def test_reorder_chain(forge):
    s = forge.schema
    w = wf_of(node(forge, "log", "a"), node(forge, "log", "b"), node(forge, "log", "c"), edges=[("start", "out", "a"), ("a", "out", "b"), ("b", "out", "c")])
    assert s.linear_chain(w) == ["a", "b", "c"]
    assert s.reorder_chain(w, ["c", "a", "b"]) and s.linear_chain(w) == ["c", "a", "b"]
    assert forge.validation.validate(w)["errors"] == []
    assert not s.reorder_chain(w, ["a", "b"])
    branching = wf_of(node(forge, "if", "i"), node(forge, "log", "t"), edges=[("start", "out", "i"), ("i", "true", "t")])
    assert s.linear_chain(branching) == [] and not s.reorder_chain(branching, ["i", "t"])


def test_history_undo_redo(forge):
    s = forge.schema
    w = wf_of(node(forge, "log", "a"))
    h = s.History()
    h.reset(w)
    assert not h.can_undo and not h.record(w)
    w["nodes"][1]["params"]["message"] = "1"
    assert h.record(w, "a:message")
    w["nodes"][1]["params"]["message"] = "12"
    h.record(w, "a:message")                                              # fusionné avec le précédent
    assert len(h.states) == 2
    w["nodes"].append(node(forge, "log", "b"))
    h.record(w)
    state = h.undo()
    s.restore(w, state)
    assert [n["id"] for n in w["nodes"]] == ["start", "a"] and w["nodes"][1]["params"]["message"] == "12"
    s.restore(w, h.undo())
    assert w["nodes"][1]["params"]["message"] == forge.blocks.defaults("log")["message"] and not h.can_undo and h.undo() is None
    s.restore(w, h.redo())
    s.restore(w, h.redo())
    assert len(w["nodes"]) == 3 and not h.can_redo
    s.restore(w, h.undo())
    w["nodes"][1]["params"]["message"] = "nouveau"
    h.record(w)
    assert not h.can_redo                                                 # une nouvelle modification efface le « rétablir »


# ------------------------------------------------------------------------------------------------ modèles d'exemple
def test_six_templates_are_valid_and_dry_run(forge, tmp_path):
    t = forge.templates
    assert len(t.template_list()) == 6
    (tmp_path / "a.md").write_text("# a TODO")
    for key, title in t.template_list():
        wf = t.build(key)
        assert wf["name"] == title or wf["name"]
        r = forge.validation.validate(wf)
        assert r["errors"] == [] and r["warnings"] == [], (key, r)
        assert all(forge.schema.validate_params(n["type"], n["params"]) == {} for n in wf["nodes"]), key
        rec = forge.engine.run_workflow(wf, str(tmp_path), dry_run=True)
        assert rec["ok"], (key, rec.get("error"), rec["log"])
    a, b = t.build("tests"), t.build("tests")
    a["nodes"][1]["params"]["command"] = "autre"
    assert b["nodes"][1]["params"]["command"] != "autre"


# ------------------------------------------------------------------------------------------------ panneau de propriétés (hors écran)
SAMPLE = {"str": "valeur", "text": "ligne 1\nligne 2", "code": "result = 2", "expr": "vars.a + 1", "var": "ma_var", "path": "dossier/f.txt", "int": 7, "duration": 3.5}


def make_panel(forge):
    qapp()
    ui = submodule("workflow-forge", "ui.props")
    return ui, ui.PropertiesPanel()


@pytest.mark.parametrize("type_", sorted(load_plugin("workflow-forge") and submodule("workflow-forge", "core.blocks").REGISTRY))
def test_panel_edits_every_block_type(forge, type_):
    from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QSpinBox
    ui, panel = make_panel(forge)
    n = node(forge, type_)
    seen = []
    panel.changed.connect(lambda i, k: seen.append(k))
    panel.set_node(n, wf_of(n))
    blk = forge.blocks.REGISTRY[type_]
    assert set(panel.rows) == {q.name for q in blk.params}
    assert panel.form.rowCount() >= len(blk.params) + 1
    for q in blk.params:
        w = panel.editor(q.name)
        if q.kind == "bool":
            assert isinstance(w, QCheckBox)
            panel.set_value(q.name, not q.default)
            assert n["params"][q.name] is (not q.default)
        elif q.kind == "choice":
            assert isinstance(w, QComboBox) and [w.itemData(i) for i in range(w.count())] == list(q.choices)
            for i, c in enumerate(q.choices):                        # l'utilisateur choisit dans le menu
                w.setCurrentIndex(i)
                assert n["params"][q.name] == c
        elif q.kind == "pairs":
            w.add_pair("CLE", "val")
            assert json.loads(n["params"][q.name]) == {"CLE": "val"} and w.table.rowCount() == 1
            w.table.setCurrentCell(0, 0)
            w.remove_button.click()
            assert json.loads(n["params"][q.name]) == {}
        elif q.kind in ("int", "duration"):
            assert isinstance(w, QSpinBox | QDoubleSpinBox)
            target = min(max(SAMPLE[q.kind], q.minimum if q.minimum is not None else -1e9), q.maximum if q.maximum is not None else 1e9)
            target = int(target) if q.kind == "int" else float(target)
            w.setValue(target)
            assert n["params"][q.name] == target
        elif q.kind == "var":
            assert isinstance(w, QComboBox) and w.isEditable()
            w.setEditText("ma_var")
            assert n["params"][q.name] == "ma_var"
        elif q.kind == "path":
            w.line.setText("dossier/f.txt")
            assert n["params"][q.name] == "dossier/f.txt" and w.button.text() == "Parcourir…"
        elif q.kind in ("text", "code"):
            assert isinstance(w, QPlainTextEdit)
            w.setPlainText(SAMPLE[q.kind])
            assert n["params"][q.name] == SAMPLE[q.kind]
        else:
            assert isinstance(w, QLineEdit)
            w.setText(SAMPLE[q.kind])
            assert n["params"][q.name] == SAMPLE[q.kind]
        assert panel.rows[q.name].reset.isEnabled() == (n["params"][q.name] != q.default)
    assert len(seen) >= len(blk.params)
    for q in blk.params:                                                    # Réinitialiser
        row = panel.rows[q.name]
        if row.reset.isEnabled():
            row.reset.click()
        assert n["params"][q.name] == q.default and not row.reset.isEnabled()
    panel.label_edit.setText("Mon bloc")
    assert n["label"] == "Mon bloc" and seen[-1] == "label"


def test_panel_live_validation_and_helpers(forge, monkeypatch):
    ui, panel = make_panel(forge)
    w = wf_of(node(forge, "set_var", "a", name="compteur", value="1"), node(forge, "set_var", "b", name="total", value="2"), node(forge, "http_request", "h"),
              edges=[("start", "out", "a"), ("a", "out", "b"), ("b", "out", "h")])
    h = w["nodes"][3]
    panel.set_node(h, w, project="/tmp")
    assert "obligatoire" in panel.error_text("url")
    panel.set_value("url", "ftp://x")
    assert "http" in panel.error_text("url")
    panel.set_value("url", "https://ok.fr")
    assert panel.error_text("url") == "" and h["params"]["url"] == "https://ok.fr"
    method = panel.editor("method")
    assert [method.itemText(i) for i in range(method.count())][:2] == ["GET (lire)", "POST (envoyer)"]
    assert "POST" in method.toolTip() and "Exemple" in panel.editor("url").toolTip() and "http" in panel.help.text().lower()
    panel.set_value("headers", {"Accept": "text/plain", "X-A": "{{vars.v}}"})
    assert json.loads(h["params"]["headers"])["Accept"] == "text/plain" and panel.editor("headers").table.rowCount() == 2
    # variable : liste déroulante éditable des variables connues en amont
    panel.set_node(w["nodes"][2], w)
    box = panel.editor("name")
    assert [box.itemText(i) for i in range(box.count())] == ["compteur"]
    panel.set_value("name", "9x")
    assert "Nom invalide" in panel.error_text("name")
    # nombres bornés, avertissement hors bornes impossible via la boîte (bornée) mais visible via la valeur
    panel.set_node(node(forge, "delay"), {})
    spin = panel.editor("seconds")
    assert spin.maximum() == 3600 and spin.singleStep() == 0.5 and spin.suffix() == " s"
    # Parcourir
    monkeypatch.setattr(ui, "browse_path", lambda parent, q, cur, project="": "src/main.py")
    panel.set_node(node(forge, "read_file"), {})
    panel.editor("path").button.click()
    assert panel.node["params"]["path"] == "src/main.py"
    # édition rapide : seulement les champs essentiels
    panel.set_node(node(forge, "http_request"), {}, essential_only=True)
    assert set(panel.rows) == {"method", "url"}
    # ancien format : en-têtes sous forme de dict
    legacy = node(forge, "http_request")
    legacy["params"]["headers"] = '{"A": "1"}'
    panel.set_node(legacy, {})
    assert panel.editor("headers").table.rowCount() == 1
    panel.clear()
    assert panel.rows == {}


def test_relative_path_helper(forge, tmp_path):
    ui = submodule("workflow-forge", "ui.props")
    (tmp_path / "x").mkdir()
    assert ui.relative_to(str(tmp_path / "x" / "f.py"), str(tmp_path)) == "x/f.py"
    assert ui.relative_to("/ailleurs/f.py", str(tmp_path)) == "/ailleurs/f.py" and ui.relative_to("", "p") == ""


# ------------------------------------------------------------------------------------------------ éditeur complet
def widget(tmp_path):
    qapp()
    w = submodule("workflow-forge", "ui.widget").ForgeWidget(submodule("workflow-forge", "storage.store").Store(tmp_path / "s"), options={"triggers": False})
    w.set_project(tmp_path)
    return w


def test_widget_edit_undo_copy_duplicate_template(forge, tmp_path):
    from PySide6.QtCore import QPointF
    w = widget(tmp_path)
    a = w.scene.add_node("http_request", QPointF(200, 0))
    w.scene.connect_nodes("start", "out", a.data["id"])
    a.setSelected(True)
    assert w.panel.node is a.data and "url" in w.panel.rows
    w.panel.set_value("method", "POST")
    w.panel.set_value("url", "https://x.org/api")
    assert a.sub.text() == "Requête HTTP" and a.summ.text() == "HTTP POST https://x.org/api" and "HTTP POST" in a.toolTip()
    assert w.flush_autosave() and w.store.workflows(str(tmp_path))[w.wf_id]["nodes"][1]["params"]["url"] == "https://x.org/api"
    # annuler / rétablir
    assert w.undo()
    assert w.wf["nodes"][1]["params"]["url"] == "" and w.wf["nodes"][1]["params"]["method"] == "POST"
    assert w.undo() and w.wf["nodes"][1]["params"]["method"] == "GET"
    assert w.redo() and w.redo() and w.wf["nodes"][1]["params"]["url"] == "https://x.org/api"
    assert not w.redo() and w.btns["undo"].isEnabled() and not w.btns["redo"].isEnabled()
    # dupliquer / copier-coller
    w.scene.select_ids([w.wf["nodes"][1]["id"]])
    dup = w.duplicate_selection()
    assert len(dup) == 1 and len(w.wf["nodes"]) == 3 and w.wf["nodes"][-1]["params"]["url"] == "https://x.org/api"
    w.scene.select_ids(dup)
    assert w.copy_selection() and len(w.paste()) == 1 and len(w.paste()) == 1 and len(w.wf["nodes"]) == 5
    assert w.undo() and len(w.wf["nodes"]) == 4
    w.scene.select_ids(["start"])
    assert not w.copy_selection()
    # double-clic : édition rapide
    a = w.scene.items_by_id[a.data["id"]]                                  # la scène a été reconstruite par annuler / coller
    dlg = w.quick_edit(a.data["id"], show=False)
    dlg.panel.set_value("url", "https://autre.fr")
    assert a.data["params"]["url"] == "https://autre.fr" and a.summ.text().endswith("https://autre.fr")
    assert set(dlg.panel.rows) == {"method", "url"}
    # palette : recherche et aide
    w.search.setText("requête")
    assert w.palette.topLevelItemCount() == 1
    w.palette.setCurrentItem(w.palette.topLevelItem(0).child(0))
    assert "Exemple" in w.block_help.text()
    w.search.setText("zzz")
    assert w.palette.topLevelItemCount() == 0 and "Aucun" in w.block_help.text()
    # modèles
    for key, title in forge.templates.template_list():
        wf = w.open_template(key)
        assert wf["name"] == title and len(w.scene.items_by_id) == len(wf["nodes"]) and not w.check()["errors"]
        assert not w.history.can_undo
    assert w.combo.count() >= 6


def test_widget_reorder_steps_and_old_workflows(forge, tmp_path):
    from PySide6.QtCore import QPointF
    w = widget(tmp_path)
    ids = []
    for t in ("log", "notify", "delay"):
        it = w.scene.add_node(t, QPointF(100 * (len(ids) + 1), 0))
        w.scene.connect_nodes(ids[-1] if ids else "start", "out", it.data["id"])
        ids.append(it.data["id"])
    w.refresh_order()
    assert w._list_order() == ids and w.order.isEnabled()
    assert w.reorder_steps([ids[2], ids[0], ids[1]]) and w._list_order() == [ids[2], ids[0], ids[1]]
    assert w.undo() and w._list_order() == ids
    assert not w.reorder_steps(ids[:2])
    # ancien workflow enregistré sans options ni paramètres récents
    legacy = {"schema": 1, "name": "ancien", "nodes": [{"id": "start", "type": "start", "params": {}}, {"id": "w", "type": "write_file", "params": {"path": "z.txt", "content": "c", "append": False}}],
              "edges": [{"src": "start", "dst": "w"}], "triggers": [{"kind": "manual"}]}
    wf_id = w.store.save_workflow(str(tmp_path), legacy)
    w.open_workflow(wf_id)
    assert w.wf["nodes"][1]["params"]["mode"] == "w" and w.scene.items_by_id["w"].summ.text() == "Écrire z.txt (w)"
    w.scene.items_by_id["w"].setSelected(True)
    assert w.panel.rows["mode"].editor.currentData() == "w"
    assert w.execute(False)["ok"] and (tmp_path / "z.txt").read_text() == "c"


def test_plugin_has_no_dynamic_code_literals():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "marketplace" / "plugins" / "workflow-forge"
    for f in root.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        for forbidden in ("eval(", "exec(", "__import__", "importlib"):
            for line in text.splitlines():
                if forbidden in line and not re.search(r"\.(eval|exec|execute)\(|def (eval|execute)\(|# .*" + re.escape(forbidden), line):
                    pytest.fail(f"{f.name}: {line.strip()}")
