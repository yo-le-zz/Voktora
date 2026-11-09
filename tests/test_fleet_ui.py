import fleet
from PySide6.QtWidgets import QApplication, QMainWindow, QMenuBar
from test_fleet import world  # noqa: F401  (fixture)
from ui_dialogs import FleetDialog, PaletteDialog, collect_actions
from ui_dialogs.palette_dialog import score


def test_palette_scoring_and_run():
    assert score("sync", "Outils › Synchronisation entre PC") > 0
    assert score("zzz", "Outils › Synchronisation") == 0
    assert score("sy", "Outils › Synchro") > score("sy", "Outils › Fonction asynchrone")      # début de mot favorisé
    app = QApplication.instance() or QApplication([])
    ran = []
    dlg = PaletteDialog(None, [("Outils › Synchronisation", lambda: ran.append("sync")), ("Fichier › Quitter", lambda: ran.append("q"))])
    dlg.edit.setText("quit")
    assert dlg.list.count() == 1
    dlg._run()
    assert ran == ["q"]
    window = QMainWindow()
    menu = window.menuBar().addMenu("Outils")
    menu.addAction("Synchro")
    sub = menu.addMenu("Plus")
    sub.addAction("Profond")
    assert [label for label, _a in collect_actions(window.menuBar())] == ["Outils › Synchro", "Outils › Plus › Profond"]
    assert isinstance(window.menuBar(), QMenuBar) and app


def test_fleet_dialog_scans_and_filters(world):  # noqa: F811
    import time
    app = QApplication.instance() or QApplication([])
    dlg = FleetDialog()
    dlg.scan()
    for _ in range(100):
        app.processEvents()
        if len(dlg._states) == 5 and "projets" in dlg.summary.text():
            break
        time.sleep(0.05)
    assert dlg.table.topLevelItemCount() == 5
    dlg.kind.setCurrentIndex(1)                         # « À traiter » : tout sauf le dépôt propre
    assert dlg.table.topLevelItemCount() == 4
    dlg.filter.setText("sal")
    assert dlg.table.topLevelItemCount() == 1 and fleet.summary(dlg._states)["clean"] == 1
