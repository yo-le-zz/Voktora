"""Workflow Forge : évaluateur sûr, cron, validation, moteur (conditions, boucles, parallèle, erreurs, tentatives, annulation, test à blanc), déclencheurs."""

import importlib
import json
import sys
import tempfile
import threading
import time
import types
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent / "marketplace" / "plugins" / "workflow-forge"


@pytest.fixture(scope="module")
def wf():
    pkg = types.ModuleType("workflow_forge")
    pkg.__path__ = [str(PLUGIN)]
    sys.modules["workflow_forge"] = pkg
    yield
    for n in [n for n in sys.modules if n == "workflow_forge" or n.startswith("workflow_forge.")]:
        del sys.modules[n]


def mod(n):
    return importlib.import_module("workflow_forge." + n)


def node(id_, type_, params=None, **opts):
    return {"id": id_, "type": type_, "label": id_, "params": params or {}, "options": opts, "x": 0, "y": 0}


def flow(nodes, edges, **kw):
    return {"schema": 1, "name": "t", "nodes": [node("start", "start"), *nodes], "edges": [{"src": s, "port": p, "dst": d} for s, p, d in edges], "triggers": [{"kind": "manual"}], **kw}


def run(w, **kw):
    kw.setdefault("runner", mod("core.proc").run)
    return mod("core.engine").run_workflow(w, **kw)


# ------------------------------------------------------------------------------------------ expressions
def test_expr_evaluates(wf):
    e = mod("core.expr")
    names = {"vars": {"n": 3, "s": "Ab", "l": [1, 2, 3], "d": {"k": {"z": 5}}}, "item": 7}
    cases = {"vars.n * 2 + 1": 7, "upper(vars.s) + 'x'": "ABx", "len(vars.l) == 3 and vars.n > 1": True, "vars.d.k.z": 5, "vars.l[1]": 2, "'a' in 'cat'": True,
             "1 if vars.n > 2 else 0": 1, "sum([1,2,3])": 6, "item + 1": 8, "not False": True, "1 < 2 < 3": True, "join('-', ['a','b'])": "a-b",
             "get(vars.d, 'nope', 9)": 9, "{'a': 1}['a']": 1, "default('', 'dflt')": "dflt", "round(2.567, 1)": 2.6, "regex_match('^a', 'abc')": True}
    for src, want in cases.items():
        assert e.evaluate(src, names) == want, src
    assert e.render("n={{vars.n}} s={{vars.s}}", names) == "n=3 s=Ab" and e.render("{{vars.l}}", names) == [1, 2, 3]
    assert e.render("pas de modèle", names) == "pas de modèle"


@pytest.mark.parametrize("bad", ["__import__('os').system('x')", "().__class__", "open('f')", "vars._x", "(lambda: 1)()", "[x for x in range(3)]", "a.b",
                                 "eval('1')", "'a'.upper()", "1/0", "2**1000", "'x'*10**9", "unknown_name", "1 +", "vars.l[99]", "print(1)", "getattr(vars,'x')"])
def test_expr_rejects(wf, bad):
    e = mod("core.expr")
    with pytest.raises(e.ExprError):
        e.evaluate(bad, {"vars": {"l": []}, "a": 1})


def test_expr_has_no_eval_in_source(wf):
    src = (PLUGIN / "core" / "expr.py").read_text()
    import ast as _ast
    calls = {n.func.id for n in _ast.walk(_ast.parse(src)) if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)}
    assert not ({"eval", "exec", "compile", "__import__"} & calls)


def test_cron(wf):
    c = mod("core.cron")
    assert c.matches("*/15 * * * *", datetime(2026, 11, 13, 10, 30)) and not c.matches("*/15 * * * *", datetime(2026, 11, 13, 10, 31))
    assert c.matches("0 9 * * 1-5", datetime(2026, 11, 13, 9, 0))              # vendredi
    assert not c.matches("0 9 * * 1-5", datetime(2026, 11, 14, 9, 0))           # samedi
    assert c.matches("30 8 1,15 * *", datetime(2026, 12, 15, 8, 30)) and c.matches("0 0 * * 0", datetime(2026, 11, 15, 0, 0))
    for bad in ("* * * *", "60 * * * *", "*/0 * * * *", "a b c d e", "5-1 * * * *"):
        with pytest.raises(ValueError):
            c.parse(bad)


# ------------------------------------------------------------------------------------------ validation
def test_validation(wf):
    v = mod("core.validation")
    assert v.validate(v.new_workflow())["errors"] == []
    bad = flow([node("a", "if", {"condition": "1 +"}), node("b", "inconnu"), node("c", "run_command", {"command": ""}), node("d", "log", {"message": "{{1 +}}"})],
               [("a", "out", "b"), ("start", "out", "a"), ("a", "true", "start"), ("c", "out", "c"), ("x", "out", "a")])
    errs = " | ".join(v.validate(bad)["errors"])
    for frag in ("invalide", "type inconnu", "requis", "n'existe pas", "relié à lui-même", "inexistant", "Démarrage", "cycle", "modèle"):
        assert frag in errs, frag
    two = flow([node("s2", "start")], [])
    assert "exactement un" in v.validate(two)["errors"][0]
    warn = v.validate(flow([node("orph", "log"), node("L", "loop_for", {"items": "[1]"}), node("p", "parallel")], [("start", "out", "L"), ("start", "out", "p")]))
    assert any("inaccessible" in w for w in warn["warnings"]) and any("body" in w for w in warn["warnings"]) and any("deux branches" in w for w in warn["warnings"])
    trig = v.validate({**v.new_workflow(), "triggers": [{"kind": "cron", "expr": "x"}, {"kind": "http_in", "token": "court"}, {"kind": "interval", "seconds": 0}, {"kind": "zzz"},
                                                         {"kind": "file_change"}]})
    assert len(trig["errors"]) == 5


def test_catalog_complete(wf):
    b = mod("core.blocks")
    cat = b.catalog()
    assert len(cat) >= 28 and {c["category"] for c in cat} >= {"Flux", "Données", "Système", "Scripts", "Réseau", "Projet"}
    for c in cat:
        assert c["title"] and isinstance(c["ports"], list)
        assert set(b.defaults(c["type"])) == {p["name"] for p in c["params"]}


# ------------------------------------------------------------------------------------------ moteur
def test_linear_variables_and_outputs(wf):
    w = flow([node("a", "set_var", {"name": "x", "value": "20 + 1"}), node("b", "transform", {"expression": "vars.x * 2"}),
              node("c", "log", {"message": "total={{out.b.value}} x={{x}}"})], [("start", "out", "a"), ("a", "out", "b"), ("b", "out", "c")])
    r = run(w)
    assert r["ok"] and "total=42 x=21" in r["log"] and [n["status"] for n in r["nodes"]] == ["ok"] * 4


def test_if_and_loops(wf):
    w = flow([node("i", "if", {"condition": "vars.n > 5"}), node("hi", "set_var", {"name": "r", "value": "'grand'"}), node("lo", "set_var", {"name": "r", "value": "'petit'"})],
             [("start", "out", "i"), ("i", "true", "hi"), ("i", "false", "lo")])
    assert run(w, variables={"n": 9})["ok"]
    out = {}
    for n, want in ((9, "grand"), (1, "petit")):
        ctxr = mod("core.blocks").Ctx("", {"n": n})
        mod("core.engine").Run(w, ctxr).execute()
        out[n] = ctxr.vars["r"]
        assert ctxr.vars["r"] == want
    loop = flow([node("L", "loop_for", {"items": "[1, 2, 3, 4]"}), node("acc", "set_var", {"name": "total", "value": "default(vars.total, 0) + item"}),
                 node("after", "log", {"message": "fini {{vars.total}}"})], [("start", "out", "L"), ("L", "body", "acc"), ("L", "done", "after")])
    c2 = mod("core.blocks").Ctx("", {"total": 0})
    r = mod("core.engine").Run(loop, c2).execute()
    assert r["ok"] and c2.vars["total"] == 10 and "fini 10" in r["log"]
    wl = flow([node("W", "loop_while", {"condition": "vars.k < 3", "max_iterations": 50}), node("inc", "set_var", {"name": "k", "value": "vars.k + 1"})],
              [("start", "out", "W"), ("W", "body", "inc")])
    c3 = mod("core.blocks").Ctx("", {"k": 0})
    assert mod("core.engine").Run(wl, c3).execute()["ok"] and c3.vars["k"] == 3
    inf = flow([node("W", "loop_while", {"condition": "true", "max_iterations": 5}), node("n", "set_var", {"name": "q", "value": "1"})], [("start", "out", "W"), ("W", "body", "n")])
    assert run(inf)["ok"]


def test_parallel_runs_concurrently(wf):
    py = sys.executable
    sl = f"{py} -c \"import time;time.sleep(0.6)\""
    w = flow([node("P", "parallel"), node("a", "run_command", {"command": sl}), node("b", "run_command", {"command": sl}), node("c", "run_command", {"command": sl}),
              node("J", "join"), node("end", "log", {"message": "joint"})],
             [("start", "out", "P"), ("P", "out", "a"), ("P", "out", "b"), ("P", "out", "c"), ("a", "out", "J"), ("b", "out", "J"), ("c", "out", "J"), ("J", "out", "end")])
    t = time.monotonic()
    r = run(w)
    assert r["ok"] and "joint" in r["log"] and time.monotonic() - t < 1.5          # 3 × 0,6 s en séquence = 1,8 s
    failing = flow([node("P", "parallel"), node("a", "run_command", {"command": f"{py} -c \"import sys;print('boum');sys.exit(2)\""}), node("b", "delay", {"seconds": 1}), node("J", "join")],
                   [("start", "out", "P"), ("P", "out", "a"), ("P", "out", "b"), ("a", "out", "J"), ("b", "out", "J")])
    r = run(failing)
    assert not r["ok"] and "boum" in r["error"]


def test_errors_ports_continue_retries(wf):
    py = sys.executable
    bad = f"{py} -c \"import sys;sys.exit(2)\""
    w = flow([node("c", "run_command", {"command": bad}), node("ok", "log", {"message": "suite"}), node("rescue", "set_var", {"name": "r", "value": "out.c.error"})],
             [("start", "out", "c"), ("c", "out", "ok"), ("c", "error", "rescue")])
    r = run(w)
    assert r["ok"] and "suite" not in r["log"] and r["nodes"][1]["status"] == "error-handled"
    w2 = flow([node("c", "run_command", {"command": bad, "fail_on_error": False}), node("rescue", "log", {"message": "récupéré code={{out.c.code}}"})],
              [("start", "out", "c"), ("c", "error", "rescue")])
    r2 = run(w2)
    assert r2["ok"] and "récupéré code=2" in r2["log"]
    w3 = flow([node("c", "run_command", {"command": bad}, continue_on_error=True), node("n", "log", {"message": "après"})], [("start", "out", "c"), ("c", "out", "n")])
    r3 = run(w3)
    assert r3["ok"] and "après" in r3["log"] and r3["nodes"][1]["status"] == "error-ignored"
    flag = Path(tempfile.mkdtemp()) / "n"
    flaky = f"{py} -c \"import pathlib,sys;p=pathlib.Path(r'{flag}');n=int(p.read_text()) if p.exists() else 0;p.write_text(str(n+1));sys.exit(0 if n>=2 else 1)\""
    w4 = flow([node("f", "run_command", {"command": flaky}, retries=3, retry_delay=0)], [("start", "out", "f")])
    r4 = run(w4, sleep=lambda s: None)
    assert r4["ok"] and r4["nodes"][1]["attempts"] == 3
    w5 = flow([node("f", "run_command", {"command": bad}, retries=1, retry_delay=0)], [("start", "out", "f")])
    r5 = run(w5, sleep=lambda s: None)
    assert not r5["ok"] and "Code 2" in r5["error"] and r5["nodes"][-1]["status"] == "failed"


def test_timeout_and_cancel(wf):
    w = flow([node("d", "delay", {"seconds": 5}, timeout=0.3)], [("start", "out", "d")])
    t = time.monotonic()
    r = run(w)
    assert not r["ok"] and "Délai" in r["error"] and time.monotonic() - t < 2
    ev = threading.Event()
    w2 = flow([node("d", "delay", {"seconds": 10})], [("start", "out", "d")])
    threading.Timer(0.3, ev.set).start()
    r2 = run(w2, cancel=ev)
    assert r2["cancelled"] and not r2["ok"]
    py = sys.executable
    ev2 = threading.Event()
    threading.Timer(0.3, ev2.set).start()
    r3 = run(flow([node("c", "run_command", {"command": f"{py} -c \"import time;time.sleep(10)\""})], [("start", "out", "c")]), cancel=ev2)
    assert not r3["ok"]


def test_dry_run_has_no_side_effects(wf, tmp_path):
    target = tmp_path / "out.txt"
    marker = tmp_path / "m"
    py = sys.executable
    w = flow([node("w", "write_file", {"path": "out.txt", "content": "x"}), node("c", "run_command", {"command": f"{py} -c \"open(r'{marker}', 'w')\""}),
              node("h", "http_request", {"url": "http://127.0.0.1:1/"}), node("n", "notify", {"message": "x"}), node("s", "set_var", {"name": "ok", "value": "1"})],
             [("start", "out", "w"), ("w", "out", "c"), ("c", "out", "h"), ("h", "out", "n"), ("n", "out", "s")])
    notes = []
    r = run(w, project=str(tmp_path), dry_run=True, notify=notes.append)
    assert r["ok"] and r["dry_run"] and not target.exists() and not marker.exists() and not notes and r["log"].count("test à blanc") == 4
    r2 = run(w, project=str(tmp_path), http=lambda *a: (200, [], b"{}"), notify=notes.append)
    assert r2["ok"] and target.exists() and marker.exists() and notes == ["x"]


def test_file_blocks_and_path_confinement(wf, tmp_path):
    (tmp_path / "a.txt").write_text("TODO: x\nrien\n")
    w = flow([node("r", "read_file", {"path": "a.txt"}), node("e", "file_exists", {"path": "a.txt"}), node("s", "project_search", {"pattern": "TODO"}),
              node("l", "list_files", {"pattern": "*.txt"}), node("t", "log", {"message": "{{out.s.count}} {{out.l.files}} {{len(out.r.text)}}"})],
             [("start", "out", "r"), ("r", "out", "e"), ("e", "true", "s"), ("s", "out", "l"), ("l", "out", "t")])
    r = run(w, project=str(tmp_path))
    assert r["ok"] and "1 ['a.txt'] 13" in r["log"]
    esc = run(flow([node("r", "read_file", {"path": "../../etc/passwd"})], [("start", "out", "r")]), project=str(tmp_path))
    assert not esc["ok"] and "hors du projet" in esc["error"]


def test_python_and_js_scripts(wf):
    w = flow([node("p", "python_script", {"code": "print('salut')\nresult = {'n': vars['x'] * 2}"}), node("l", "log", {"message": "{{out.p.result.n}}"})],
             [("start", "out", "p"), ("p", "out", "l")])
    r = run(w, variables={"x": 4})
    assert r["ok"] and "8" in r["log"] and "salut" in r["log"]
    boom = run(flow([node("p", "python_script", {"code": "raise ValueError('zut')"})], [("start", "out", "p")]))
    assert not boom["ok"] and "zut" in boom["error"]
    slow = run(flow([node("p", "python_script", {"code": "while True: pass", "timeout": 1})], [("start", "out", "p")]))
    assert not slow["ok"] and "délai" in slow["error"]
    import shutil
    if shutil.which("node"):
        js = run(flow([node("j", "js_script", {"code": "result = vars.x + 1"}), node("l", "log", {"message": "{{out.j.result}}"})], [("start", "out", "j"), ("j", "out", "l")]), variables={"x": 1})
        assert js["ok"] and "2" in js["log"]
    if shutil.which("rustc"):
        rs = run(flow([node("r", "rust_script", {"code": 'fn main(){println!("hello-rust");}'})], [("start", "out", "r")]))
        assert rs["ok"] and "hello-rust" in rs["log"]


def test_http_block_and_json(wf):
    calls = []

    def fake(method, url, headers, body, timeout):
        calls.append((method, url, body))
        return 200, [("Content-Type", "application/json")], b'{"items": [1, 2, 3]}'
    w = flow([node("h", "http_request", {"method": "POST", "url": "http://x/api", "body": "{{vars.q}}"}), node("c", "set_var", {"name": "n", "value": "len(out.h.json.items)"})],
             [("start", "out", "h"), ("h", "out", "c")])
    ctxr = mod("core.blocks").Ctx("", {"q": "payload"}, http=fake)
    r = mod("core.engine").Run(w, ctxr).execute()
    assert r["ok"] and ctxr.vars["n"] == 3 and calls == [("POST", "http://x/api", b"payload")]
    err = run(flow([node("h", "http_request", {"url": "http://x"}), node("e", "log", {"message": "erreur {{out.h.status}}"})], [("start", "out", "h"), ("h", "error", "e")]),
              http=lambda *a: (500, [], b"no"))
    assert err["ok"] and "erreur 500" in err["log"]
    assert not run(flow([node("h", "http_request", {"url": "ftp://x"})], [("start", "out", "h")]))["ok"]


def test_git_blocks(wf, tmp_path):
    import subprocess
    for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "T"]):
        subprocess.run(["git", *a], cwd=tmp_path, check=True)
    (tmp_path / "f").write_text("1")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "c"], cwd=tmp_path, check=True)
    r = run(flow([node("g", "git_status"), node("h", "git_head"), node("l", "log", {"message": "{{out.g.branch}} {{out.g.clean}} {{len(out.h.sha)}}"})],
                 [("start", "out", "g"), ("g", "out", "h"), ("h", "out", "l")]), project=str(tmp_path))
    assert r["ok"] and "main True 40" in r["log"]
    assert "git_push" not in mod("core.blocks").REGISTRY


def test_invalid_workflow_refuses_to_run(wf):
    r = run({"name": "x", "nodes": [], "edges": []})
    assert not r["ok"] and "invalide" in r["error"]
    cyc = flow([node("a", "log"), node("b", "log")], [("start", "out", "a"), ("a", "out", "b"), ("b", "out", "a")])
    assert not run(cyc)["ok"]


# ------------------------------------------------------------------------------------------ déclencheurs
def test_triggers_interval_cron_files_git(wf, tmp_path):
    T = mod("core.triggers")
    fired = []
    heads = ["a1"]
    m = T.Manager(lambda wid, payload: fired.append((wid, payload["kind"], payload)), str(tmp_path), git_head=lambda p: heads[0], github_latest=lambda r: "c1", clock=lambda: 1000.0)
    m.register("w1", {"kind": "interval", "seconds": 10})
    m.register("w2", {"kind": "cron", "expr": "*/5 * * * *"})
    m.register("w3", {"kind": "file_change", "pattern": "*.py", "every": 1})
    m.register("w4", {"kind": "git_head", "every": 1})
    m.register("w5", {"kind": "github_poll", "repo": "o/r", "every": 1})
    m.register("w6", {"kind": "on_start"})
    assert m.tick(1005.0) == 0
    assert m.tick(1011.0) == 1 and fired[-1][:2] == ("w1", "interval")                   # intervalle écoulé
    assert m.tick(1012.0) == 0
    t0 = datetime(2026, 11, 13, 10, 5).timestamp()
    n = m.tick(t0)
    assert any(f[1] == "cron" for f in fired) and n >= 1
    before = len(fired)
    m.tick(t0 + 20)
    assert not any(f[1] == "cron" for f in fired[before:])                                  # une seule fois par minute
    (tmp_path / "x.py").write_text("1")
    m.tick(t0 + 30)
    fp = [f for f in fired if f[1] == "file_change"]
    assert fp and fp[-1][2]["added"] == ["x.py"]
    heads[0] = "b2"
    m.tick(t0 + 40)
    assert any(f[1] == "git_head" and f[2]["new"] == "b2" for f in fired)
    assert m.event("on_start") == 1 and fired[-1][0] == "w6"
    for bad in ({"kind": "cron", "expr": "x"}, {"kind": "interval", "seconds": 0}, {"kind": "zzz"}, {"kind": "file_change"}, {"kind": "http_in", "token": "court"}):
        with pytest.raises(Exception):  # noqa: B017, PT011
            m.register("x", bad)


def post(url, token=None, body=b"{}"):
    req = urllib.request.Request(url, data=body, method="POST", headers={"X-Voktora-Token": token} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_http_trigger_requires_token_and_localhost(wf):
    T = mod("core.triggers")
    got = []
    m = T.Manager(lambda wid, p: got.append((wid, p)))
    tok = "a" * 24
    m.register("w", {"kind": "http_in", "token": tok, "path": "/go"})
    port = next(iter(m.servers))
    assert m.servers[port].server_address[0] == "127.0.0.1"
    base = f"http://127.0.0.1:{port}"
    assert post(base + "/go")[0] == 401 and post(base + "/go", "mauvais")[0] == 401 and post(base + "/go", "a" * 23)[0] == 401
    assert post(base + "/autre", tok)[0] == 404
    code, _ = post(base + "/go", tok, b'{"x": 1}')
    assert code == 202 and got == [("w", {"kind": "http_in", "body": {"x": 1}})]
    assert post(base + "/go", tok, b"pas json")[0] == 202 and got[-1][1]["body"] == {"raw": "pas json"}
    with pytest.raises(T.TriggerError):
        m.register("w", {"kind": "http_in", "token": ""})
    m.stop()
    with pytest.raises(OSError):
        post(base + "/go", tok)


def test_import_export_roundtrip_and_token_stripped(wf):
    s, v = mod("storage.store"), mod("core.validation")
    w = {**v.new_workflow("Mon flux"), "triggers": [{"kind": "http_in", "token": "secret" * 4}, {"kind": "interval", "seconds": 5}]}
    text = s.export_text(w)
    assert "secretsecret" not in text
    back = s.import_text(text)
    assert back["name"] == "Mon flux" and all("token" not in t for t in back["triggers"])
    for bad in ("pas json", "[]", '{"nodes": []}', json.dumps({"voktora_workflow": 1, "name": "x", "nodes": [{"id": "a", "type": "zzz"}], "edges": []})):
        with pytest.raises(ValueError):
            s.import_text(bad)


def test_store(wf, tmp_path):
    s = mod("storage.store").Store(tmp_path)
    a = s.save_workflow("/p", {"name": "Même nom"})
    b = s.save_workflow("/p", {"name": "Même nom"})
    assert b == a + "-2" and set(s.workflows("/p")) == {a, b}
    s.delete_workflow("/p", a)
    assert set(s.workflows("/p")) == {b}
    for i in range(mod("storage.store").HISTORY_MAX + 4):
        s.add_run("/p", b, {"i": i})
    assert len(s.runs("/p")) == mod("storage.store").HISTORY_MAX and s.runs("/p")[0]["i"] == mod("storage.store").HISTORY_MAX + 3 and s.runs("/q") == []


# ------------------------------------------------------------------------------------------ interface
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_editor_scene_connect_delete(wf):
    qapp()
    from PySide6.QtCore import QPointF
    ed = mod("ui.editor")
    sc = ed.FlowScene()
    w = mod("core.validation").new_workflow()
    sc.load(w)
    a = sc.add_node("log", QPointF(300, 0))
    i = sc.add_node("if", QPointF(300, 100))
    assert sc.connect_nodes("start", "out", a.data["id"]) and not sc.connect_nodes("start", "out", a.data["id"])     # doublon refusé
    assert not sc.connect_nodes(a.data["id"], "out", "start") and not sc.connect_nodes(a.data["id"], "out", a.data["id"])
    assert sc.connect_nodes(i.data["id"], "true", a.data["id"]) and len(w["edges"]) == 2
    a.setPos(500, 50)
    assert (a.data["x"], a.data["y"]) == (500, 50)                                   # le modèle suit l'éditeur
    a.setSelected(True)
    sc.remove_selected()
    assert [n["id"] for n in w["nodes"]] == ["start", i.data["id"]] and w["edges"] == []
    sc.items_by_id["start"].setSelected(True)
    sc.remove_selected()
    assert "start" in sc.items_by_id                                                 # le démarrage ne se supprime pas
    assert mod("core.validation").validate(w)["errors"] == []


def test_editor_handles_250_blocks_fast(wf):
    qapp()
    ed = mod("ui.editor")
    nodes = [node("start", "start")] + [node(f"n{i}", "log", {"message": str(i)}) for i in range(250)]
    for i, n in enumerate(nodes):
        n["x"], n["y"] = (i % 20) * 200, (i // 20) * 90
    edges = [{"src": nodes[i]["id"], "port": "out", "dst": nodes[i + 1]["id"]} for i in range(250)]
    w = {"schema": 1, "name": "gros", "nodes": nodes, "edges": edges, "triggers": []}
    sc = ed.FlowScene()
    t = time.monotonic()
    sc.load(w)
    load = time.monotonic() - t
    view = ed.FlowView(sc)
    view.resize(1200, 800)
    view.show()
    t = time.monotonic()
    for k in range(40):                                                              # glisser un bloc relié met à jour ses liens
        sc.items_by_id["n100"].setPos(k * 3, k * 2)
    drag = (time.monotonic() - t) / 40
    view.fit()
    assert len(sc.items_by_id) == 251 and len(sc.items()) > 750
    assert load < 4.0 and drag < 0.05, (load, drag)
    assert mod("core.validation").validate(w)["errors"] == []


def test_widget_end_to_end(wf, tmp_path):
    qapp()
    from PySide6.QtCore import QPointF
    w = mod("ui.widget").ForgeWidget(mod("storage.store").Store(tmp_path / "s"), options={"triggers": False})
    w.set_project(tmp_path)
    assert w.wf["name"] and w.palette.topLevelItemCount() >= 6
    w.search.setText("parallèle")
    assert w.palette.topLevelItemCount() == 1
    w.search.setText("")
    a = w.scene.add_node("set_var", QPointF(200, 0))
    b = w.scene.add_node("log", QPointF(400, 0))
    w.scene.connect_nodes("start", "out", a.data["id"])
    w.scene.connect_nodes(a.data["id"], "out", b.data["id"])
    a.setSelected(True)
    w.show_form(a.data["id"])
    assert w.form.rowCount() >= 5
    a.data["params"].update(name="v", value="40 + 2")
    b.data["params"]["message"] = "v={{vars.v}}"
    assert "valide" in (w.check() and w.status.text())
    rec = w.execute(False)
    assert rec["ok"] and "v=42" in rec["log"] and w.runs.rowCount() == 1
    dry = w.execute(True)
    assert dry["dry_run"] and w.runs.rowCount() == 2
    a.data["params"]["value"] = "1 +"
    assert w.execute(False) is None and "erreur" in w.status.text()
    a.data["params"]["value"] = "1"
    out = tmp_path / "w.json"
    assert w.save() and w.export_file(str(out)) and w.import_file(str(out)) and w.combo.count() == 2
    assert not w.import_file(str(tmp_path / "absent.json"))
    w.trig.setPlainText('[{"kind": "http_in", "token": "court"}]')
    assert not w.apply_triggers() and "erreur" in w.status.text()
    w.trig.setPlainText('[{"kind": "interval", "seconds": 60}]')
    assert w.apply_triggers()
    w.delete()
    assert w.combo.count() == 1


def test_widget_trigger_runs_workflow(wf, tmp_path):
    qapp()
    from PySide6.QtCore import QPointF
    w = mod("ui.widget").ForgeWidget(mod("storage.store").Store(tmp_path / "s"), options={"triggers": False})
    w.set_project(tmp_path)
    n = w.scene.add_node("write_file", QPointF(200, 0))
    n.data["params"].update(path="declenche.txt", content="{{trigger.kind}}")
    w.scene.connect_nodes("start", "out", n.data["id"])
    w.save()
    w.manager = mod("core.triggers").Manager(w._fire, str(tmp_path))
    w.manager.register(w.wf_id, {"kind": "on_open"})
    w.open_event("on_open")
    assert (tmp_path / "declenche.txt").read_text() == "on_open"
