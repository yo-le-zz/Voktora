"""Plugins dans la vraie fenêtre : les 8 plugins du marketplace chargés, utilisés puis retirés proprement."""

import os
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voktora"))
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core  # noqa: E402
import plugins  # noqa: E402
from plugins import market  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from ui_main import MainWindow  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)
MARKET_DIR = Path(__file__).resolve().parent.parent / "marketplace"
ALL_IDS = sorted(p.name for p in (MARKET_DIR / "plugins").iterdir() if p.is_dir())


@pytest.fixture
def window(isolated_data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "_run_startup_health_check", lambda self: None)
    monkeypatch.setattr(MainWindow, "_show_migration_summary", lambda self: None)
    monkeypatch.setattr(MainWindow, "_run_update_check", lambda self: None)
    core.set_storage_config(str(tmp_path / "Projects"))
    w = MainWindow()
    _app.processEvents()
    yield w
    w.close()
    w.deleteLater()
    _app.processEvents()


def _install_all():
    for plugin_id in ALL_IDS:
        shutil.copytree(MARKET_DIR / "plugins" / plugin_id, plugins.plugins_dir() / plugin_id)


def _menu_titles(window):
    return [a.text() for a in window.menuBar().actions()]


def _wait_for(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        _app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


class TestRealPlugins:
    def test_every_marketplace_plugin_loads_without_error(self, window):
        _install_all()
        plugins.load_all()
        assert sorted(p.id for p in plugins.get_all()) == ALL_IDS
        broken = {p.id: p.error for p in plugins.get_all() if p.error or not p.loaded}
        assert broken == {}

    def test_ui_elements_appear_and_disappear(self, window):
        tabs = window._project_panel._tabs
        base_tabs, base_menus = tabs.count(), _menu_titles(window)
        base_status = window.statusBar().children().__len__()
        _install_all()
        plugins.load_all()
        _app.processEvents()

        titles = [tabs.tabText(i) for i in range(tabs.count())]
        assert {"Notes", "TODO", "Git Insights"} <= {t.strip() for t in titles}
        assert tabs.count() == base_tabs + 3
        menus = _menu_titles(window)
        assert "Plugins" in menus and menus.index("Plugins") < len(menus) - 1     # avant « Aide »
        plugins_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "Plugins")
        assert {a.text() for a in plugins_menu.actions()} == {"UI Tweaks", "Focus Timer", "Zen Mode"}
        assert window._ui_host._toolbar is not None and window._ui_host._toolbar.isVisibleTo(window)
        assert window._ui_host.context_actions(["/x"])[0][0] == "Copier le chemin"
        assert window.statusBar().children().__len__() > base_status

        for plugin_id in ALL_IDS:
            plugins.set_enabled(plugin_id, False)
        _app.processEvents()
        assert tabs.count() == base_tabs
        assert _menu_titles(window) == base_menus
        assert not window._ui_host._toolbar.actions() and not window._ui_host._toolbar.isVisibleTo(window)
        assert window._ui_host.context_actions(["/x"]) == [] and plugins.extra_themes() == {}

    def test_tabs_follow_the_selected_project(self, window, tmp_path):
        _install_all()
        plugins.load_all()
        project = core.create_project(str(tmp_path), "Alpha")
        (project / "code.py").write_text("x = 1\n# TODO: ranger\n# FIXME bug\n", encoding="utf-8")
        window._invalidate_cache()
        window._refresh_all()
        window._on_project_selected(str(project))

        notes = next(w for i, w in window._ui_host._tab_widgets if i.id == "quick-notes")
        assert "Alpha" in notes._title.text()
        notes._edit.setPlainText("ma note")
        notes._save()
        assert plugins.PluginSettings("quick-notes").get(f"note:{project}") == "ma note"

        todo = next(w for i, w in window._ui_host._tab_widgets if i.id == "todo-scanner")
        assert _wait_for(lambda: todo._tree.topLevelItemCount() == 2)

        git = next(w for i, w in window._ui_host._tab_widgets if i.id == "git-insights")
        assert _wait_for(lambda: "pas un dépôt Git" in git._text.toPlainText() or "Branche" in git._text.toPlainText())

        window._show_welcome()
        assert "Sélectionnez" in notes._title.text()

    def test_counter_and_zen_mode_and_style(self, window, tmp_path):
        _install_all()
        plugins.load_all()
        core.create_project(str(tmp_path), "One")
        core.create_project(str(tmp_path), "Two")
        window._invalidate_cache()
        window._refresh_all()
        counter = [c for c in window.statusBar().findChildren(type(window._status_lbl)) if "projet" in c.text()]
        assert counter and counter[0].text() == "2 projets"

        sidebar = window._main_splitter.widget(0)
        window.show()
        zen_action = next(a for a in window._ui_host._toolbar.actions() if a.text() == "Zen")
        zen_action.trigger()
        assert not sidebar.isVisible() and not window.menuBar().isVisible()
        zen_action.trigger()
        assert sidebar.isVisible() and window.menuBar().isVisible()

        plugins.set_enabled("ui-tweaks", False)
        assert "font-size: 14px" not in plugins.extra_stylesheet()
        plugins.PluginSettings("ui-tweaks").set("enabled", ["bigfont"])
        plugins.set_enabled("ui-tweaks", True)
        assert "font-size: 14px" in plugins.extra_stylesheet()
        assert "font-size: 14px" in QApplication.instance().styleSheet()

    def test_context_action_uses_clicked_project(self, window, tmp_path):
        _install_all()
        plugins.load_all()
        project = core.create_project(str(tmp_path), "Ctx")
        (_label, _icon, run) = window._ui_host.context_actions([str(project)])[0]
        run()
        assert QApplication.clipboard().text() == str(project)

    def test_crashing_ui_plugin_does_not_break_window(self, window):
        folder = plugins.plugins_dir() / "crashy"
        folder.mkdir(parents=True)
        (folder / "plugin.json").write_text(
            '{"id":"crashy","name":"Crashy","version":"1.0.0","author":"t","permissions":["ui"]}', encoding="utf-8")
        (folder / "main.py").write_text(
            "def on_load(api):\n    api.add_project_tab('X', lambda ctx: 1/0)\n"
            "    api.add_menu_action('Outils', 'Boom', lambda ctx: 1/0)\n", encoding="utf-8")
        plugins.load_all()
        info = plugins.find("crashy")
        assert info.loaded and info.errors          # l'onglet affiche une erreur au lieu de planter
        action = next(a for a in window.menuBar().findChildren(type(window.menuBar().actions()[0])) if a.text() == "Boom")
        action.trigger()
        assert any("division" in e for e in info.errors)

    def test_plugins_menu_entry_and_event_hooks(self, window, tmp_path):
        titles = [a.text() for m in window.menuBar().actions() if m.menu() for a in m.menu().actions()]
        assert any("Plugins et marketplace" in t for t in titles)
        folder = plugins.plugins_dir() / "spy"
        folder.mkdir(parents=True)
        (folder / "plugin.json").write_text(
            '{"id":"spy","name":"Spy","version":"1.0.0","author":"t","permissions":[]}', encoding="utf-8")
        events = []
        (folder / "main.py").write_text(
            "import builtins\n"
            "def on_load(api):\n"
            "    for e in ('on_open','on_close','on_create','on_delete','on_refresh'):\n"
            "        api.on(e, lambda ctx, e=e: builtins.__dict__.setdefault('SPY', []).append(e))\n", encoding="utf-8")
        plugins.load_all()
        import builtins
        builtins.SPY = events
        project = core.create_project(str(tmp_path), "Evt")
        window._after_project_added(project, "x")
        window._on_project_selected(str(project))
        window._show_welcome()
        assert {"on_create", "on_open", "on_close", "on_refresh"} <= set(events)
        del builtins.SPY


class TestPluginsDialog:
    @pytest.fixture
    def served(self, monkeypatch):
        def fake_fetch(url, timeout=0, limit=0):
            path = MARKET_DIR / url[len(market.DEFAULT_URL) + 1:]
            if not path.is_file():
                raise market.MarketError("404")
            return path.read_bytes()
        monkeypatch.setattr(market, "_fetch", fake_fetch)

    def test_marketplace_tab_lists_filters_and_installs(self, window, served, monkeypatch):
        from ui_dialogs import PluginsDialog
        dlg = PluginsDialog(window)
        dlg._tabs.setCurrentIndex(1)
        assert _wait_for(lambda: dlg._market_tree.topLevelItemCount() == len(ALL_IDS))
        dlg._search.setText("pomodoro")
        assert dlg._market_tree.topLevelItemCount() == 1
        assert dlg._btn_install.text() == "Installer" and dlg._btn_install.isEnabled()
        assert "Permissions" in dlg._market_details.toPlainText()

        monkeypatch.setattr(dlg, "_confirm_install", lambda *a, **k: True)
        dlg._install_selected()
        assert _wait_for(lambda: plugins.find("focus-timer") is not None and plugins.find("focus-timer").loaded)
        assert _wait_for(lambda: dlg._btn_install.text() == "Réinstaller")
        assert dlg._tree.topLevelItemCount() == 1
        dlg._tree.setCurrentItem(dlg._tree.topLevelItem(0))
        assert "Désactiver" in dlg._btn_toggle.text()
        dlg._toggle_selected()
        assert not plugins.find("focus-timer").enabled and dlg._btn_toggle.text() == "Activer"
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
        dlg._remove_selected()
        assert plugins.find("focus-timer") is None and dlg._tree.topLevelItemCount() == 0
        dlg.close()

    def test_offline_marketplace_shows_a_message(self, window, monkeypatch):
        monkeypatch.setattr(market, "_fetch", lambda *a, **k: (_ for _ in ()).throw(market.MarketError("Connexion impossible")))
        from ui_dialogs import PluginsDialog
        dlg = PluginsDialog(window)
        dlg._tabs.setCurrentIndex(1)
        assert _wait_for(lambda: "indisponible" in dlg._market_details.toPlainText())
        dlg.close()
