"""
Voktora — main.py
Point d'entrée de l'application.
"""

from __future__ import annotations

import multiprocessing
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

if os.environ.get("VOKTORA_JS_WORKER") == "1":       # processus d'un plugin JavaScript (voir plugins/js_worker.py)
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("js_worker", os.path.join(os.path.dirname(__file__), "plugins", "js_worker.py"))
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.run()
    raise SystemExit(0)

if os.environ.get("VOKTORA_DEVMON_VIEWER"):          # seconde fenêtre du moniteur développeur (voir devmon/), processus détaché
    from devmon import viewer as _viewer
    raise SystemExit(_viewer.run(os.environ["VOKTORA_DEVMON_VIEWER"]))

import live

live.prepare_environment()                              # mode live : dossier de données temporaire (avant tout accès aux données)

import core  # noqa: E402
import linux_env  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main() -> None:
    # Indispensable pour les processus de calcul (core.parallel) dans la version compilée ; sans effet sinon.
    multiprocessing.freeze_support()
    from core import tls
    tls.install()                        # certificats HTTPS (version compilée : « CERTIFICATE_VERIFY_FAILED »)
    linux_env.prepare_environment()      # AVANT la création de QApplication (choix Wayland/X11, thème…)
    missing = linux_env.missing_system_libs()
    if missing:
        # Qt va probablement échouer à charger son plugin xcb : on dit quoi installer, au lieu de laisser
        # son message technique (« could not load the Qt platform plugin "xcb" ») sans explication.
        family = linux_env.detect_distro()["family"]
        print(f"Voktora : bibliothèques système manquantes ({', '.join(missing)}). "
              f"Installation : {linux_env.install_hint(family)}", file=sys.stderr)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Voktora")
    app.setApplicationVersion(core.APP_VERSION)
    app.setDesktopFileName("voktora")   # relie la fenêtre à voktora.desktop (icône sous Wayland : GNOME, KDE…)
    app.setStyle("Fusion")

    if live.active():
        live.main_cleanup_on_exit()
        live.configure_storage()

    # Moniteur développeur global (--dev[=mode], VOKTORA_DEV, ou préférence) : démarré tôt pour voir aussi les plantages du démarrage
    from devmon import core as _dm_core
    from devmon import launcher as _dm_launcher
    _dm_level = _dm_launcher.parse_dev_arg(sys.argv)
    if _dm_level is None and _dm_core.read_prefs().get("autostart"):
        _dm_level = _dm_core.valid_level(_dm_core.read_prefs().get("mode"))
    if _dm_level and not live.active():          # mode live : rien ne doit survivre à la fermeture
        import devmon
        devmon.open_monitor(_dm_level, app, open_window=_dm_core.read_prefs().get("window", True))

    # Icônes vectorielles à la place des emojis (absents de nombreux Linux)
    import icons
    icons.install(app)

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

    # Vault : propose le déverrouillage seulement s'il contient des secrets (« Plus tard » possible)
    from ui_dialogs import prompt_at_startup
    prompt_at_startup()

    # Thème
    import accessibility
    import theme_manager
    accessibility.apply_font(app)
    theme_manager.apply_theme_to_app(app)

    # Fenêtre principale
    # Lire la version depuis version.txt si disponible
    ver_file = core.get_app_dir() / "version.txt"
    if ver_file.is_file():
        v = ver_file.read_text(encoding="utf-8").strip()
        if v:
            core.constants.APP_VERSION = v
            app.setApplicationVersion(v)

    from ui_main import MainWindow
    win = MainWindow()
    win.show()

    code = app.exec()
    from devmon import emitter as _dm_emitter
    if _dm_emitter.current():
        _dm_emitter.current().stop(code)
    sys.exit(code)


if __name__ == "__main__":
    main()
