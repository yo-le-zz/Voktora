"""Zen Mode 1.1 : éléments masqués selon les options, restauration, plein écran, raccourci unique."""

import pytest
from plugin_stub import StubApi, load_plugin


@pytest.fixture
def window():
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QSplitter
    QApplication.instance() or QApplication([])
    w = QMainWindow()
    w.menuBar().addMenu("Fichier")
    w.statusBar().showMessage("prêt")
    w._main_splitter = QSplitter()
    w._main_splitter.addWidget(QLabel("projets"))
    w._main_splitter.addWidget(QLabel("contenu"))
    w.setCentralWidget(w._main_splitter)
    w.show()
    return w


def make(window, tmp_path):
    mod = load_plugin("zen-mode")
    api = StubApi(tmp_path)
    api.main_window = lambda: window
    mod.on_load(api)
    return api, mod


def test_toggle_hides_then_restores(window, tmp_path):
    api, _ = make(window, tmp_path)
    toggle = api.menu[0][2]
    assert all(v for v in (window.menuBar().isVisible(), window.statusBar().isVisible(), window._main_splitter.widget(0).isVisible()))
    toggle()
    assert not window.menuBar().isVisible() and not window.statusBar().isVisible() and not window._main_splitter.widget(0).isVisible()
    assert window._main_splitter.widget(1).isVisible() and api.notices[-1].startswith("Mode zen activé")
    toggle()
    assert window.menuBar().isVisible() and window.statusBar().isVisible() and window._main_splitter.widget(0).isVisible()


def test_options_choose_what_is_hidden(window, tmp_path):
    api, _ = make(window, tmp_path)
    api.options.set("hide_menu", False)
    api.options.set("hide_sidebar", False)
    api.options.set("announce", False)
    api.menu[0][2]()
    assert window.menuBar().isVisible() and window._main_splitter.widget(0).isVisible() and not window.statusBar().isVisible()
    assert api.notices == []
    api.menu[0][2]()
    assert window.statusBar().isVisible()


def test_quit_restores_and_shortcut_is_single(window, tmp_path):
    api, _ = make(window, tmp_path)
    api.menu[0][2]()
    api.hooks["on_quit"][0](None)
    assert window.menuBar().isVisible()
    # un seul raccourci « Ctrl+Shift+Z » : deux actions identiques s'annuleraient (raccourci ambigu)
    assert [s for s, _h in api.shortcuts] == ["Ctrl+Shift+Z"] and "shortcut" not in api.menu[0][3]
