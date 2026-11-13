"""Mode développeur : journal, tracebacks annotés, rechargement, synchronisation du manifeste, validation réelle."""

import json

import plugins
from plugins import devtools


def make(folder, files, lang="python", perms=("ui",), entry="main.py", **extra):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.json").write_text(json.dumps({"id": folder.name, "name": folder.name, "version": "1.0.0", "author": "t",
                                                    "api": 5, "lang": lang, "entry": entry,
                                                    "permissions": perms if perms == "auto" else list(perms), **extra}))
    for name, text in files.items():
        (folder / name).write_text(text)
    return folder


def test_record_entries_and_listeners():
    devtools.clear()
    seen = []
    stop = devtools.subscribe(seen.append)
    devtools.record("p", "boom")
    stop()
    devtools.record("q", "x")
    assert [e["source"] for e in devtools.entries()] == ["p", "q"] and len(seen) == 1
    assert devtools.entries("q")[0]["text"] == "x"


def test_split_traceback_marks_plugin_lines(tmp_path):
    text = f'Traceback:\n  File "{tmp_path}/main.py", line 3, in on_load\n  File "{devtools.HERE}/runtime.py", line 9, in x\nBoom'
    out = devtools.split_traceback(text, tmp_path)
    assert "▶ File" in out and "· Voktora" in out


def test_sync_manifest_adds_permissions_and_requires(tmp_path):
    folder = make(tmp_path / "p", {"main.py": "import fancylib_zz\ndef on_load(api):\n    api.http_get('https://x.org')\n"})
    added = devtools.sync_manifest(folder)
    data = json.loads((folder / "plugin.json").read_text())
    assert "network" in added["permissions"] and "fancylib_zz" in data["requires"] and "libs" in data["permissions"]


def test_validate_static_missing_permission(tmp_path):
    folder = make(tmp_path / "p", {"main.py": "def on_load(api):\n    api.http_get('https://x.org')\n"})
    res = devtools.validate(folder, run=False)
    assert not res["ok"] and any("network" in e for e in res["errors"])


def test_validate_runs_code_for_real(tmp_path):
    good = make(tmp_path / "good", {"main.py": "def on_load(api):\n    api.log('ok')\n    api.add_menu_action('Outils', 'x', lambda c: None)\n"},
                perms=("ui",))
    res = devtools.validate(good)
    assert res["ok"], res
    assert any("ok" in line for line in res["logs"])
    bad = make(tmp_path / "bad", {"main.py": "def on_load(api):\n    raise ValueError('cassé ici')\n"})
    res = devtools.validate(bad)
    assert not res["ok"] and any("cassé ici" in e and "▶" in e for e in res["errors"])


def test_validate_js_runs_for_real(tmp_path):
    folder = make(tmp_path / "jsp", {"main.js": "voktora.log('js ok');"}, lang="js", entry="main.js", perms="auto")
    res = devtools.validate(folder)
    assert res["ok"], res
    assert any("js ok" in line for line in res["logs"])


def test_changed_plugins_detects_edits(isolated_data_dir):
    d = plugins.plugins_dir()
    make(d / "devp", {"main.py": "def on_load(api):\n    pass\n"})
    plugins.load_all()
    info = plugins.find("devp")
    assert devtools.set_dev("devp", True) and info.dev
    seen = {}
    assert devtools.changed_plugins(seen) == []
    (d / "devp" / "main.py").write_text("def on_load(api):\n    api.log('v2')\n")
    import os
    os.utime(d / "devp" / "main.py", (1, 99999999))
    assert devtools.changed_plugins(seen) == ["devp"]
    devtools._reload("devp")
    assert plugins.find("devp").loaded and any("v2" in x for x in plugins.find("devp").logs)
    plugins.load_all()
