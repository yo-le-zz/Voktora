"""Project Counter 1.1 : libellés, répartition, résumé, commande cd, interface et actions."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from plugin_stub import StubApi, load_plugin, submodule

PROJECTS = [{"name": "Beta", "path": "/p/b", "category": "web", "status": "actif"},
            {"name": "alpha", "path": "/p/a", "category": "web", "status": ""},
            {"name": "Gamma", "path": "/p/g", "category": "", "status": "actif"}]


@pytest.fixture(scope="module")
def plg():
    return load_plugin("project-counter"), submodule("project-counter", "summary")


def test_label_formats(plg):
    _m, sm = plg
    assert sm.label([], "count") == "0 projet" and sm.label(PROJECTS) == "3 projets"
    assert sm.label(PROJECTS, "short") == "3" and sm.label(PROJECTS, "category") == "3 projets · 1 catégorie"


def test_breakdown_and_markdown(plg):
    _m, sm = plg
    assert sm.breakdown(PROJECTS, "category") == [("web", 2), ("—", 1)]
    md = sm.to_markdown(PROJECTS)
    assert "# Projets (3)" in md and "| web | 2 |" in md and "| actif | 2 |" in md
    assert md.index("**alpha**") < md.index("**Beta**")            # liste triée sans tenir compte de la casse
    assert sm.tooltip([]) == "Aucun projet" and "web : 2" in sm.tooltip(PROJECTS)


def test_cd_command_is_shell_safe(plg):
    _m, sm = plg
    assert sm.cd_command("/home/a b/c", "linux") == "cd '/home/a b/c'"
    assert sm.cd_command("/x; rm -rf ~", "linux") == "cd '/x; rm -rf ~'"
    assert sm.cd_command('C:\\Mes "docs"', "win32") == 'cd /d "C:\\Mes docs"'


def test_widget_updates_and_actions(plg, tmp_path):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    mod, _sm = plg
    api = StubApi(tmp_path)
    api.projects = lambda: list(PROJECTS)
    mod.on_load(api)
    label = api.status[0](None)
    assert label.text() == "3 projets" and "web : 2" in label.toolTip()
    api.options.set("format", "short")
    assert label.text() == "3"
    PROJECTS.append({"name": "D", "path": "/p/d"})
    api.hooks["on_refresh"][0](None)
    assert label.text() == "4"
    PROJECTS.pop()
    names = [c[1] for c in api.context]
    assert names == ["Copier le chemin", "Copier le nom", "Copier la commande cd"]
    ctx = SimpleNamespace(project_path=Path("/home/x/demo"))
    api.context[2][2](ctx)
    assert app.clipboard().text() == "cd /home/x/demo" and api.notices
    api.menu[0][2]()
    assert "# Projets (3)" in api.dialogs[0][1]
