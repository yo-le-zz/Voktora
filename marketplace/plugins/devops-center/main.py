"""Voktora DevOps Center — Git, Docker, serveurs SSH, déploiements et pipelines dans un seul onglet."""

from PySide6.QtWidgets import QDialog, QVBoxLayout

from .core.proc import run as proc_run
from .storage.store import Store
from .ui.widget import DevOpsWidget


def on_load(api):
    o = api.options
    o.group("Général")
    o.add_bool("auto_refresh", "Actualiser Git à l'ouverture du projet", default=True)
    o.add_bool("notify", "Notifier la fin des pipelines et déploiements", default=True)
    o.add_bool("prefer_gh_cli", "Préférer la CLI `gh` à l'API HTTPS pour GitHub", default=False)
    store = Store(api.data_path("devops"))

    def http(method, url, headers):
        code, body, _h = api.http_request(method, url, headers=headers, timeout=20)
        return code, body

    def token():
        try:
            return api.vault_secret_get("github_token")
        except Exception:  # noqa: BLE001 — coffre verrouillé ou jeton absent : accès anonyme
            return ""

    def make(ctx=None):
        return DevOpsWidget(store, proc_run, api.run_async, http, token, api.notify, lambda t, x: api.confirm(t, x),
                            {"auto_refresh": o.get("auto_refresh"), "notify": o.get("notify"), "prefer_gh_cli": o.get("prefer_gh_cli")})

    api.add_project_tab("DevOps", lambda ctx: make(ctx), icon="mdi:rocket-launch-outline")

    def open_dialog(*_):
        dlg = QDialog(api.main_window())
        dlg.setWindowTitle("DevOps Center")
        dlg.resize(1100, 760)
        w = make()
        QVBoxLayout(dlg).addWidget(w)
        w.set_project(api.current_project())
        dlg.exec()

    api.add_menu_action("Outils", "DevOps Center…", open_dialog, icon="mdi:rocket-launch-outline", shortcut="Ctrl+Alt+D")
    api.add_palette_command("DevOps Center", open_dialog)
