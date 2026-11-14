"""Plugins JavaScript du marketplace (Text Case, JSON Clipboard, Generators) : bibliothèques testées avec node ET dans le
moteur QJSEngine de Voktora (celui des utilisateurs), et chargement des vrais plugins."""

import json
import shutil
import subprocess
from pathlib import Path

import plugins
import pytest
from test_plugins_ui import window  # noqa: F401, F811 — fixture partagée

PLUGINS = Path(__file__).resolve().parent.parent / "marketplace" / "plugins"
NODE = shutil.which("node")


def run_node(plugin, lib, expr):
    script = f"const m = require({json.dumps(str(PLUGINS / plugin / 'lib' / lib))}); console.log(JSON.stringify({expr}));"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True)  # noqa: S603
    return json.loads(out.stdout)


def run_engine(pdir, plugin, lib, expr):
    """Exécute `expr` dans le moteur JavaScript de Voktora, via un plugin jetable qui `require` la vraie bibliothèque."""
    pid = "probe-" + plugin
    folder = pdir / pid
    (folder / "lib").mkdir(parents=True, exist_ok=True)
    shutil.copy(PLUGINS / plugin / "lib" / lib, folder / "lib" / lib)
    (folder / "plugin.json").write_text(json.dumps({"id": pid, "name": pid, "version": "1.0.0", "author": "t", "api": 5,
                                                    "lang": "js", "entry": "main.js", "permissions": []}))
    (folder / "main.js").write_text(f"const m = require('./lib/{lib}'); voktora.log('RESULT ' + JSON.stringify({expr}));")
    plugins.load_all()
    info = plugins.find(pid)
    assert info.loaded and not info.error, info.error
    line = next(entry for entry in info.logs if "RESULT " in entry)
    return json.loads(line.split("RESULT ", 1)[1])


@pytest.fixture
def pdir(isolated_data_dir):
    d = plugins.plugins_dir()
    d.mkdir(parents=True, exist_ok=True)
    yield d
    plugins.load_all()


CASES = [
    ("text-case-js", "cases.js", "m.convert('camel', 'ma_variable HTTPServer-2')", "maVariableHttpServer2"),
    ("text-case-js", "cases.js", "m.convert('snake', 'maCléHTTP')", "ma_clé_http"),
    ("text-case-js", "cases.js", "m.convert('kebab', 'Hello World Foo')", "hello-world-foo"),
    ("text-case-js", "cases.js", "m.convert('constant', 'maVariable')", "MA_VARIABLE"),
    ("text-case-js", "cases.js", "m.convert('pascal', 'un deux_trois')", "UnDeuxTrois"),
    ("text-case-js", "cases.js", "m.convert('title', 'le chat noir')", "Le Chat Noir"),
    ("text-case-js", "cases.js", "m.convert('slug', 'Élève été, déjà!')", "eleve-ete-deja"),
    ("text-case-js", "cases.js", "m.applyLines('sort', 'b\\na\\nc\\n')", "a\nb\nc\n"),
    ("text-case-js", "cases.js", "m.applyLines('unique', 'a\\nb\\na\\nb\\nc')", "a\nb\nc"),
    ("text-case-js", "cases.js", "m.applyLines('dropEmpty', 'a\\n\\n  \\nb')", "a\nb"),
    ("text-case-js", "cases.js", "m.applyLines('number', 'x\\ny')", "1. x\n2. y"),
    ("text-case-js", "cases.js", "m.stats('un deux\\ntrois')", {"chars": 13, "words": 3, "lines": 2}),
    ("json-clipboard-js", "jsonfmt.js", "m.format('{\"b\":1,\"a\":[1,2]}', 2)", '{\n  "b": 1,\n  "a": [\n    1,\n    2\n  ]\n}\n'),
    ("json-clipboard-js", "jsonfmt.js", "m.minify('{ \"a\" : [ 1 , 2 ] }')", '{"a":[1,2]}'),
    ("json-clipboard-js", "jsonfmt.js", "m.sorted('{\"b\":1,\"a\":{\"z\":0,\"c\":1}}', 'tab')", '{\n\t"a": {\n\t\t"c": 1,\n\t\t"z": 0\n\t},\n\t"b": 1\n}\n'),
    ("json-clipboard-js", "jsonfmt.js", "m.summary('[1,2,3]')", "Tableau de 3 élément(s)"),
    ("json-clipboard-js", "jsonfmt.js", "m.summary('{\"x\":1,\"y\":2}')", "Objet de 2 clé(s) : x, y"),
    ("json-clipboard-js", "jsonfmt.js", "m.parse('{\"a\":1}').ok", True),
    ("generators-js", "gen.js", "m.uuid4(m.rng(1)) === m.uuid4(m.rng(1))", True),
    ("generators-js", "gen.js", "/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(m.uuid4())", True),
    ("generators-js", "gen.js", "m.lorem(3, 7).split('\\n\\n').length", 3),
    ("generators-js", "gen.js", "m.lorem(2, 7) === m.lorem(2, 7) && m.lorem(2, 7) !== m.lorem(2, 8)", True),
    ("generators-js", "gen.js", "m.timestamps(new Date(Date.UTC(2026, 10, 14, 12, 0, 0))).iso", "2026-11-14T12:00:00.000Z"),
    ("generators-js", "gen.js", "m.timestamps(new Date(Date.UTC(2026, 10, 14, 12, 0, 0))).unix", 1794657600),
    ("generators-js", "gen.js", "/^#[0-9a-f]{6}$/.test(m.hexColor())", True),
]


@pytest.mark.skipif(NODE is None, reason="node absent")
@pytest.mark.parametrize(("plugin", "lib", "expr", "expected"), CASES)
def test_library_with_node(plugin, lib, expr, expected):
    assert run_node(plugin, lib, expr) == expected


@pytest.mark.parametrize(("plugin", "lib", "expr", "expected"), CASES)
def test_library_in_voktora_engine(pdir, plugin, lib, expr, expected):
    assert run_engine(pdir, plugin, lib, expr) == expected


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_invalid_json_reports_line_and_column():
    r = run_node("json-clipboard-js", "jsonfmt.js", "m.parse('{\"a\": 1,\\n  \"b\": }')")
    assert r["ok"] is False and r["line"] in (None, 2)


@pytest.mark.skipif(NODE is None, reason="node absent")
def test_unknown_conversion_is_an_error():
    script = f"try {{ require({json.dumps(str(PLUGINS / 'text-case-js/lib/cases.js'))}).convert('nope', 'x'); }} catch (e) {{ console.log(e.message); }}"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True)  # noqa: S603
    assert "inconnue" in out.stdout


def all_action_texts(menu_or_bar):
    out = []
    for action in menu_or_bar.actions():
        out.append(action.text())
        if action.menu() is not None:
            out += all_action_texts(action.menu())
    return out


@pytest.mark.parametrize(("pid", "expected"), [("text-case-js", {"camelCase", "snake_case", "Trier A→Z"}),
                                               ("json-clipboard-js", {"Formater", "Minifier", "Trier les clés"}),
                                               ("generators-js", {"UUID v4", "Lorem ipsum", "Couleur hexadécimale"})])
def test_real_plugin_loads_and_adds_menu_actions(window,  # noqa: F811
                                                  pid, expected):
    shutil.copytree(PLUGINS / pid, plugins.plugins_dir() / pid)
    plugins.load_all()
    info = plugins.find(pid)
    assert info.loaded and not info.error, info.error
    assert info.lang == "js" and "clipboard" in info.permissions
    texts = set(all_action_texts(window.menuBar()))
    assert expected <= texts, expected - texts
    plugins.set_enabled(pid, False)
    assert not (expected & set(all_action_texts(window.menuBar())))        # le menu disparaît avec le plugin
