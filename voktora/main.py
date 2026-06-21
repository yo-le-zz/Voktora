"""
Voktora — main.py
Version : 1.0.1
Point d'entrée de l'application.
"""

from __future__ import annotations

import os
import sys

# Supprimer les messages Wayland parasites (textinput + grab)
os.environ.setdefault(
    "QT_LOGGING_RULES",
    "qt.qpa.wayland.textinput=false;"
    "qt.qpa.wayland=false;"
    "kf.wayland.client=false"
)

sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui     import QIcon
from PySide6.QtCore    import Qt

import core


def main() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Voktora")
    app.setApplicationVersion(core.APP_VERSION)
    app.setStyle("Fusion")

    # Icône
    assets = core.get_app_dir() / "assets"
    for name in ("Voktora.ico", "Voktora.png"):
        ico = assets / name
        if ico.is_file():
            app.setWindowIcon(QIcon(str(ico)))
            break

    # Initialisation : dossiers + config
    core.ensure_app_dirs()

    # Master password au premier lancement (ou si vault non initialisé)
    if not core.vault_is_initialized():
        from ui_dialogs import MasterPasswordSetupDialog
        dlg = MasterPasswordSetupDialog()
        if dlg.exec() != 1:  # QDialog.Accepted
            sys.exit(0)
        core.vault_init(dlg.get_password())

    # Thème
    import theme_manager
    theme_manager.apply_theme_to_app(app)

    # Fenêtre principale
    # Lire la version depuis version.txt si disponible
    ver_file = core.get_app_dir() / "version.txt"
    if ver_file.is_file():
        v = ver_file.read_text(encoding="utf-8").strip()
        if v:
            core.APP_VERSION = v
            app.setApplicationVersion(v)

    from ui_main import MainWindow
    win = MainWindow()
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
