"""Quick Notes 1.1 : statistiques, sauvegarde par projet, copie Markdown, options."""

from pathlib import Path

import pytest
from plugin_stub import StubApi, load_plugin, submodule


@pytest.fixture(scope="module")
def plg():
    return load_plugin("quick-notes"), submodule("quick-notes", "notes")


def test_stats_and_markdown(plg):
    _m, n = plg
    assert n.stats("") == (0, 0, 0) and n.stats("a b\nc") == (3, 5, 2)
    assert n.describe("") == "Note vide" and n.describe("un") == "1 mot · 2 caractères · 1 ligne"
    assert n.to_markdown("demo", "texte\n\n") == "# Notes — demo\n\ntexte\n"


def test_tab_saves_per_project_and_copies(plg, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    mod, _n = plg
    api = StubApi(tmp_path)
    mod.on_load(api)
    assert api.options.get("font_size") == 11 and api.tabs[0][0] == "Notes"
    tab = api.tabs[0][1](None)
    a, b = Path("/p/alpha"), Path("/p/beta")
    tab.set_project(a)
    tab._edit.setPlainText("idée un\ndeux")
    assert "non enregistrée" in tab._saved.text() and tab._count.text().startswith("3 mots")
    tab.set_project(b)                                      # quitter un projet enregistre sa note
    assert api.settings.get("note:/p/alpha") == "idée un\ndeux" and tab._edit.toPlainText() == ""
    tab.set_project(a)
    assert tab._edit.toPlainText() == "idée un\ndeux" and tab._saved.text() == ""
    tab._copy()
    assert api.clipboard == "# Notes — alpha\n\nidée un\ndeux\n"
    tab.set_project(None)
    assert not tab._edit.isEnabled() and tab._title.text() == "Sélectionnez un projet"
