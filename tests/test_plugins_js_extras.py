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
]


@pytest.mark.skipif(NODE is None, reason="node absent")
@pytest.mark.parametrize(("plugin", "lib", "expr", "expected"), CASES)
def test_library_with_node(plugin, lib, expr, expected):
    assert run_node(plugin, lib, expr) == expected


@pytest.mark.parametrize(("plugin", "lib", "expr", "expected"), CASES)
def test_library_in_voktora_engine(pdir, plugin, lib, expr, expected):
    assert run_engine(pdir, plugin, lib, expr) == expected


def all_action_texts(widget):
    """Textes de toutes les actions, sous-menus compris."""
    out = []
    for action in widget.actions():
        out.append(action.text().replace("&", ""))
        if action.menu() is not None:
            out.extend(all_action_texts(action.menu()))
    return out


@pytest.mark.parametrize(("pid", "expected"), [("text-case-js", {"camelCase", "snake_case", "Trier A→Z"})])
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
