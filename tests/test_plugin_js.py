"""Plugins JavaScript 1.1.1 : API complète sans code de liaison, modules, isolation, erreurs, permissions détectées."""

import json

import plugins
import pytest
from plugins import js_host


@pytest.fixture
def pdir(isolated_data_dir):
    d = plugins.plugins_dir()
    d.mkdir(parents=True, exist_ok=True)
    yield d
    plugins.load_all()


def write(pdir, pid, files, perms="auto", **extra):
    folder = pdir / pid
    folder.mkdir(exist_ok=True)
    (folder / "plugin.json").write_text(json.dumps({"id": pid, "name": pid, "version": "1.0.0", "author": "t", "api": 5,
                                                    "lang": "js", "entry": "main.js", "permissions": perms, **extra}))
    for name, text in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)


def test_script_runs_with_global_voktora_and_logs(pdir):
    write(pdir, "hello", {"main.js": "voktora.log('salut ' + (1 + 2)); console.log('c', 4);"})
    plugins.load_all()
    info = plugins.find("hello")
    assert info.loaded and not info.error and "salut 3" in info.logs[0] and "c 4" in info.logs[1]


def test_callbacks_events_and_options(pdir):
    write(pdir, "evt", {"main.js": """
        voktora.options.addInt('n', 'N', 5, 1, 10);
        voktora.on('on_open', ctx => voktora.log('open ' + ctx.projectPath + ' n=' + voktora.options.get('n')));
        voktora.every(60, () => {});
        function onUnload() { voktora.log('bye'); }
    """})
    plugins.load_all()
    info = plugins.find("evt")
    assert info.loaded, info.error
    plugins.fire_hook("on_open", __import__("pathlib").Path("/tmp/proj"))
    assert any("open /tmp/proj n=5" in line for line in info.logs)
    info.options.set("n", 99)
    assert info.options.get("n") == 10
    plugins.set_enabled("evt", False)
    assert any("bye" in line for line in info.logs)


def test_multi_file_require_and_json(pdir):
    write(pdir, "multi", {
        "main.js": "const u = require('./lib/util.js'); const c = require('./data.json'); voktora.log(u.twice(c.n));",
        "lib/util.js": "const h = require('./helper.js'); exports.twice = n => h.id(n) * 2;",
        "lib/helper.js": "module.exports = { id: x => x };",
        "data.json": '{"n": 21}'})
    plugins.load_all()
    info = plugins.find("multi")
    assert info.loaded, info.error
    assert info.logs[0].endswith("42")


def test_require_cannot_escape_plugin_folder(pdir):
    write(pdir, "esc", {"main.js": "require('../../../etc/passwd');"})
    (pdir.parent / "secret.js").write_text("1")
    plugins.load_all()
    assert not plugins.find("esc").loaded and "refusé" in plugins.find("esc").error


def test_permissions_detected_and_enforced(pdir):
    write(pdir, "net", {"main.js": "voktora.systemInfo();"})
    write(pdir, "strict", {"main.js": "voktora.systemInfo();"}, perms=[])
    plugins.load_all()
    assert "system" in plugins.find("net").permissions
    strict = plugins.find("strict")
    assert not strict.loaded and "permission" in strict.error.lower()


def test_infinite_loop_is_interrupted(pdir, monkeypatch):
    monkeypatch.setattr(js_host, "JS_TIMEOUT", 0.5)
    monkeypatch.setattr(js_host, "LOAD_TIMEOUT", 3.0)
    write(pdir, "loop", {"main.js": "while (true) {}"})
    plugins.load_all()
    assert not plugins.find("loop").loaded and "ne répond plus" in plugins.find("loop").error


def test_error_reports_line_and_unknown_api(pdir):
    write(pdir, "bad", {"main.js": "\n\nvoktora.nExistePas();"})
    plugins.load_all()
    err = plugins.find("bad").error
    assert "n'existe pas" in err
    write(pdir, "syn", {"main.js": "let = ;"})
    plugins.load_all()
    assert plugins.find("syn").error and "main.js" in plugins.find("syn").error or "SyntaxError" in plugins.find("syn").error


def test_no_system_access_from_js(pdir):
    write(pdir, "sys", {"main.js": "voktora.log(typeof process + typeof require('./x.js') );"})
    write(pdir, "sys2", {"main.js": "voktora.log([typeof process, typeof fetch, typeof XMLHttpRequest, typeof Deno].join())"})
    plugins.load_all()
    assert "undefined,undefined,undefined,undefined" in plugins.find("sys2").logs[0]
    assert not plugins.find("sys").loaded                                # require('./x.js') : fichier inexistant
