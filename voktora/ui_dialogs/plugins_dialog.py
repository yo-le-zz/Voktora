"""
Voktora — ui_dialogs.plugins_dialog
Gestionnaire de plugins : onglet « Installés » (activer, désactiver, désinstaller, erreurs) et
onglet « Marketplace » (parcourir, installer, mettre à jour depuis le dépôt GitHub).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import icons
import plugins
from plugins import market
from plugins.manifest import PERMISSIONS
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from task_worker import TaskWorker

CONTRIBUTE_URL = "https://github.com/yo-le-zz/Voktora/blob/main/marketplace/README.md"
WARNING = (
    "Un plugin est du code qui s'exécute avec VOS droits sur cet ordinateur. Les permissions ci-dessus "
    "sont déclarées par l'auteur et relues par le mainteneur, mais ce n'est pas un bac à sable : "
    "n'installez que des plugins dont vous avez confiance en l'auteur."
)


COMMUNITY_WARNING = (
    "PLUGIN COMMUNAUTAIRE : écrit et hébergé par un tiers, pas par le mainteneur de Voktora. Son code est figé "
    "sur le commit indiqué (relu à l'acceptation) ; toute modification ultérieure de son dépôt n'est PAS "
    "installée tant qu'une nouvelle version n'a pas été re-validée."
)


def _permission_lines(permissions: list[str]) -> str:
    if not permissions:
        return "• Aucune permission demandée"
    return "\n".join(f"• {PERMISSIONS.get(p, p)}  ({p})" for p in permissions)


def _details_html(title: str, version: str, author: str, description: str, permissions: list[str],
                  extra: str = "") -> str:
    perms = "".join(f"<li>{PERMISSIONS.get(p, p)} <code>{p}</code></li>" for p in permissions) \
        or "<li>Aucune permission demandée</li>"
    safe = lambda text: (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return (f"<h3 style='margin:0'>{safe(title)} <small>v{safe(version)}</small></h3>"
            f"<p style='margin:2px 0 8px 0'><i>par {safe(author)}</i></p>"
            f"<p>{safe(description) or '—'}</p><b>Permissions</b><ul>{perms}</ul>{extra}")


class PluginsDialog(QDialog):
    """Gestionnaire de plugins et marketplace."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plugins — Voktora")
        self.setMinimumSize(760, 520)
        self.resize(900, 640)
        self._market_entries: list[market.MarketEntry] = []
        self._worker: TaskWorker | None = None
        self._installing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        self._tabs = QTabWidget()
        root.addWidget(self._tabs, stretch=1)
        self._tabs.addTab(self._build_installed_tab(), icons.icon("mdi:puzzle-outline"), "Installés")
        self._tabs.addTab(self._build_market_tab(), icons.icon("mdi:storefront-outline"), "Marketplace")
        self._tabs.currentChanged.connect(self._on_tab)

        self._bar = QProgressBar()
        self._bar.setFixedHeight(8)
        self._bar.setTextVisible(False)
        self._bar.hide()
        root.addWidget(self._bar)
        footer = QHBoxLayout()
        self._status = QLabel("")
        self._status.setWordWrap(True)
        footer.addWidget(self._status, stretch=1)
        btn_close = QPushButton("Fermer")
        btn_close.setMinimumHeight(34)
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)
        root.addLayout(footer)

        self._refresh_installed()

    # ── Onglet Installés ──────────────────────────────────────────────────────────
    def _build_installed_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(4, 12, 4, 4)
        v.setSpacing(10)
        hint = QLabel(f"Dossier : <code>{plugins.plugins_dir()}</code>")
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet("font-size: 11px;")
        v.addWidget(hint)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Plugin", "Version", "Auteur", "Statut"])
        self._tree.setRootIsDecorated(False)
        self._tree.setColumnWidth(0, 220)
        self._tree.currentItemChanged.connect(self._on_installed_selected)
        v.addWidget(self._tree, stretch=2)

        self._installed_details = QTextBrowser()
        self._installed_details.setMinimumHeight(140)
        v.addWidget(self._installed_details, stretch=2)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._btn_toggle = QPushButton("Désactiver")
        self._btn_toggle.clicked.connect(self._toggle_selected)
        self._btn_remove = QPushButton("Désinstaller")
        self._btn_remove.clicked.connect(self._remove_selected)
        btn_reload = QPushButton("Recharger")
        btn_reload.clicked.connect(self._reload)
        btn_local = QPushButton("Installer depuis un fichier…")
        btn_local.clicked.connect(self._install_local)
        btn_open = QPushButton("Ouvrir le dossier")
        btn_open.clicked.connect(self._open_dir)
        for button in (self._btn_toggle, self._btn_remove, btn_reload, btn_local, btn_open):
            button.setMinimumHeight(34)
            row.addWidget(button)
        row.addStretch()
        v.addLayout(row)
        self._on_installed_selected(None, None)
        return page

    def _refresh_installed(self, select: str = "") -> None:
        self._tree.clear()
        for info in plugins.get_all():
            if info.error:
                status = "Erreur"
            elif not info.enabled:
                status = "Désactivé"
            else:
                status = "Actif" + (" (ancien format)" if info.legacy else "") \
                + (" · communauté" if info.tier == "community" else "")
            item = QTreeWidgetItem([info.name, info.version, info.author, status])
            item.setData(0, Qt.UserRole, info.id)
            if info.error:
                item.setIcon(0, icons.icon("mdi:alert-circle-outline", color="#f38ba8"))
            elif not info.enabled:
                item.setIcon(0, icons.icon("mdi:pause-circle-outline"))
            else:
                item.setIcon(0, icons.icon("mdi:puzzle-outline"))
            self._tree.addTopLevelItem(item)
            if select and info.id == select:
                self._tree.setCurrentItem(item)
        if not plugins.get_all():
            self._installed_details.setHtml(
                "<p>Aucun plugin installé. Ouvrez l'onglet <b>Marketplace</b> pour en découvrir.</p>")

    def _selected_info(self) -> plugins.PluginInfo | None:
        item = self._tree.currentItem()
        return plugins.find(item.data(0, Qt.UserRole)) if item else None

    def _on_installed_selected(self, _current, _previous) -> None:
        info = self._selected_info()
        self._btn_toggle.setEnabled(info is not None)
        self._btn_remove.setEnabled(info is not None)
        if info is None:
            return
        self._btn_toggle.setText("Activer" if not info.enabled else "Désactiver")
        extra = ""
        if info.legacy:
            extra += ("<p><b>Ancien format (fichier .py)</b> : toutes les permissions. "
                      "Préférez un dossier avec <code>plugin.json</code>.</p>")
        if info.origin == "market":
            where = f" — <a href='{info.repo}'>{info.repo}</a> @ <code>{info.commit[:7]}</code>" if info.repo else ""
            extra += ("<p><b>" + ("Communauté" if info.tier == "community" else "Officiel")
                      + f"</b> : fichiers verrouillés (SHA-256 vérifié à chaque démarrage){where}</p>")
        elif not info.legacy:
            extra += "<p><b>Installé localement</b> : non vérifié par le marketplace.</p>"
        if info.slow:
            extra += "<p><b>Lent :</b> " + ", ".join(info.slow) + "</p>"
        if info.error:
            extra += f"<p><b>Erreur de chargement :</b></p><pre>{info.error}</pre>"
        elif info.errors:
            extra += f"<p><b>Dernière erreur :</b></p><pre>{info.errors[-1][-900:]}</pre>"
        self._installed_details.setHtml(_details_html(
            info.name, info.version, info.author, info.description,
            ["ui", "projects.read", "files", "network", "shell"] if info.legacy else info.permissions, extra))

    def _toggle_selected(self) -> None:
        info = self._selected_info()
        if info is None:
            return
        plugins.set_enabled(info.id, not info.enabled)
        self._refresh_installed(select=info.id)
        self._status.setText(f"« {info.name} » {'activé' if info.enabled else 'désactivé'}.")

    def _remove_selected(self) -> None:
        info = self._selected_info()
        if info is None:
            return
        purge = QMessageBox.question(
            self, "Désinstaller",
            f"Désinstaller « {info.name} » ?\n\nSes données (réglages) seront supprimées aussi.")
        if purge != QMessageBox.Yes:
            return
        try:
            if info.legacy:
                plugins.unload(info)
                Path(info.path).unlink(missing_ok=True)
            else:
                market.uninstall(info.id, purge_data=True)
        except (OSError, market.MarketError) as exc:
            QMessageBox.warning(self, "Plugins", f"Impossible de désinstaller : {exc}")
            return
        self._reload()
        self._status.setText(f"« {info.name} » désinstallé.")

    def _reload(self) -> None:
        plugins.load_all()
        self._refresh_installed()
        self._refresh_market_states()

    def _install_local(self) -> None:
        choice = QMessageBox(self)
        choice.setWindowTitle("Installer un plugin")
        choice.setText("Que voulez-vous installer ?")
        btn_zip = choice.addButton("Archive .zip", QMessageBox.AcceptRole)
        btn_dir = choice.addButton("Dossier", QMessageBox.AcceptRole)
        choice.addButton("Annuler", QMessageBox.RejectRole)
        choice.exec()
        if choice.clickedButton() is btn_zip:
            name, _ = QFileDialog.getOpenFileName(self, "Archive de plugin", "", "Plugin (*.zip)")
        elif choice.clickedButton() is btn_dir:
            name = QFileDialog.getExistingDirectory(self, "Dossier du plugin")
        else:
            return
        if not name:
            return
        try:
            man = market.read_local_manifest(Path(name))
        except market.MarketError as exc:
            QMessageBox.warning(self, "Plugin invalide", str(exc))
            return
        if not self._confirm_install(man.name, man.version, man.author, man.permissions, local=True):
            return
        try:
            market.install_from_path(Path(name))
        except market.MarketError as exc:
            QMessageBox.warning(self, "Installation impossible", str(exc))
            return
        self._reload()
        self._refresh_installed(select=man.id)
        self._status.setText(f"« {man.name} » installé.")

    def _open_dir(self) -> None:
        plugins.plugins_dir().mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(plugins.plugins_dir())))

    # ── Onglet Marketplace ────────────────────────────────────────────────────────────
    def _build_market_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(4, 12, 4, 4)
        v.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Rechercher un plugin (nom, auteur, mot-clé)…")
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumHeight(34)
        self._search.textChanged.connect(self._fill_market)
        btn_refresh = QPushButton("Actualiser")
        btn_refresh.setMinimumHeight(34)
        btn_refresh.clicked.connect(self._load_market)
        btn_contrib = QPushButton("Proposer un plugin")
        btn_contrib.setMinimumHeight(34)
        btn_contrib.setToolTip("Ouvre le guide de contribution (fork → Pull Request) sur GitHub")
        btn_contrib.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(CONTRIBUTE_URL)))
        top.addWidget(self._search, stretch=1)
        top.addWidget(btn_refresh)
        top.addWidget(btn_contrib)
        v.addLayout(top)

        self._market_tree = QTreeWidget()
        self._market_tree.setHeaderLabels(["Plugin", "Version", "Auteur", "Origine", "État"])
        self._market_tree.setRootIsDecorated(False)
        self._market_tree.setColumnWidth(0, 220)
        self._market_tree.currentItemChanged.connect(self._on_market_selected)
        v.addWidget(self._market_tree, stretch=2)

        self._market_details = QTextBrowser()
        self._market_details.setMinimumHeight(140)
        v.addWidget(self._market_details, stretch=2)

        row = QHBoxLayout()
        self._btn_install = QPushButton("Installer")
        self._btn_install.setObjectName("primary")
        self._btn_install.setMinimumHeight(34)
        self._btn_install.setEnabled(False)
        self._btn_install.clicked.connect(self._install_selected)
        row.addStretch()
        row.addWidget(self._btn_install)
        v.addLayout(row)
        return page

    def _on_tab(self, index: int) -> None:
        if index == 1 and not self._market_entries and self._worker is None:
            self._load_market()

    def _busy(self, active: bool, message: str = "") -> None:
        self._bar.setRange(0, 0)
        self._bar.setVisible(active)
        if message:
            self._status.setText(message)

    def _load_market(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._busy(True, "Chargement du marketplace…")
        self._worker = TaskWorker(lambda _ctx: market.fetch_index())
        self._worker.succeeded.connect(self._on_market_loaded)
        self._worker.failed.connect(self._on_market_failed)
        self._worker.cancelled.connect(lambda: self._busy(False))
        self._worker.start()

    def _on_market_loaded(self, result) -> None:
        entries, cached = result
        self._market_entries = entries
        self._busy(False, f"{len(entries)} plugin(s) disponible(s)" + (" (copie hors ligne)." if cached else "."))
        self._fill_market()

    def _on_market_failed(self, message: str) -> None:
        self._busy(False, "")
        self._market_tree.clear()
        self._market_details.setHtml(
            f"<p><b>Marketplace indisponible.</b></p><p>{message}</p>"
            "<p>Vérifiez votre connexion, ou l'adresse du marketplace dans les réglages.</p>")
        self._status.setText("Marketplace indisponible.")

    _STATE_LABEL: ClassVar[dict[str, str]] = {"new": "", "update": "Mise à jour", "installed": "Installé"}

    def _fill_market(self) -> None:
        needle = self._search.text().strip().casefold()
        selected = self._selected_entry()
        self._market_tree.clear()
        for entry in self._market_entries:
            haystack = " ".join([entry.id, entry.name, entry.author, entry.description, *entry.tags]).casefold()
            if needle and needle not in haystack:
                continue
            state = market.status(entry)
            label = self._STATE_LABEL[state] if entry.compatible else "Incompatible"
            origin = "Communauté" if entry.community else "Officiel"
            item = QTreeWidgetItem([entry.name, entry.version, entry.author, origin, label])
            item.setData(0, Qt.UserRole, entry.id)
            item.setIcon(0, icons.icon("mdi:check-circle-outline", color="#a6e3a1") if state == "installed"
                         else icons.icon("mdi:puzzle-outline"))
            self._market_tree.addTopLevelItem(item)
            if selected is not None and selected.id == entry.id:
                self._market_tree.setCurrentItem(item)
        if self._market_tree.currentItem() is None and self._market_tree.topLevelItemCount():
            self._market_tree.setCurrentItem(self._market_tree.topLevelItem(0))
        self._on_market_selected(self._market_tree.currentItem(), None)

    def _refresh_market_states(self) -> None:
        if self._market_entries:
            self._fill_market()

    def _selected_entry(self) -> market.MarketEntry | None:
        item = self._market_tree.currentItem()
        if item is None:
            return None
        wanted = item.data(0, Qt.UserRole)
        return next((e for e in self._market_entries if e.id == wanted), None)

    def _on_market_selected(self, _current, _previous) -> None:
        entry = self._selected_entry()
        if entry is None:
            self._btn_install.setEnabled(False)
            return
        state = market.status(entry)
        extra = f"<p><a href='{entry.homepage}'>{entry.homepage}</a></p>" if entry.homepage else ""
        if entry.community:
            extra += (f"<p><b>Communauté</b> — dépôt <a href='{entry.repo}'>{entry.repo}</a><br>"
                      f"commit épinglé <code>{entry.short_commit}</code> (code figé, vérifié à chaque démarrage)</p>")
        else:
            extra += "<p><b>Officiel</b> — écrit par le mainteneur.</p>"
        added = market.permission_changes(market.installed_permissions(entry.id) or entry.permissions,
                                          entry.permissions) if state == "update" else []
        if added:
            extra += ("<p style='color:#f38ba8'><b>Cette mise à jour demande de NOUVELLES permissions : "
                      + ", ".join(added) + "</b></p>")
        if entry.tags:
            extra += "<p>Mots-clés : " + ", ".join(entry.tags) + "</p>"
        if not entry.compatible:
            extra += "<p><b>Ce plugin nécessite une version plus récente de Voktora.</b></p>"
        self._market_details.setHtml(_details_html(
            entry.name, entry.version, entry.author, entry.description, entry.permissions, extra))
        self._btn_install.setText({"new": "Installer", "update": "Mettre à jour", "installed": "Réinstaller"}[state])
        self._btn_install.setEnabled(entry.compatible and not self._installing)

    def _confirm_install(self, name: str, version: str, author: str, permissions: list[str],
                         local: bool = False, entry: market.MarketEntry | None = None) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Installer un plugin")
        box.setText(f"Installer « {name} » v{version} (par {author}) ?")
        box.setInformativeText(
            f"Ce plugin demande :\n{_permission_lines(permissions)}\n\n{WARNING}"
            + (f"\n\n{COMMUNITY_WARNING}\nDépôt : {entry.repo}\nCommit : {entry.commit}"
               if entry is not None and entry.community else "")
            + (self._new_permissions_text(entry) if entry is not None else "")
            + ("\n\nSource : fichier local (non vérifié par le marketplace)." if local else ""))
        box.addButton("Installer", QMessageBox.AcceptRole)
        cancel = box.addButton("Annuler", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is not cancel

    @staticmethod
    def _new_permissions_text(entry: market.MarketEntry) -> str:
        old = market.installed_permissions(entry.id)
        added = market.permission_changes(old, entry.permissions) if old is not None else []
        return f"\n\nATTENTION — nouvelles permissions par rapport à la version installée : {', '.join(added)}" if added else ""

    def _install_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None or (self._worker is not None and self._worker.isRunning()):
            return
        if not self._confirm_install(entry.name, entry.version, entry.author, entry.permissions, entry=entry):
            return
        self._busy(True, f"Installation de « {entry.name} »…")
        self._installing = True
        self._btn_install.setEnabled(False)
        self._worker = TaskWorker(lambda ctx: market.install(entry, on_progress=ctx.progress))
        self._worker.progress.connect(self._on_install_progress)
        self._worker.succeeded.connect(lambda _r, e=entry: self._on_installed(e))
        self._worker.failed.connect(self._on_install_failed)
        self._worker.cancelled.connect(lambda: (setattr(self, "_installing", False), self._busy(False)))
        self._worker.start()

    def _on_install_progress(self, done, total, name) -> None:
        if total:
            self._bar.setRange(0, int(total))
            self._bar.setValue(int(done))
        if name:
            self._status.setText(f"Téléchargement de {name}…")

    def _on_installed(self, entry: market.MarketEntry) -> None:
        self._installing = False
        self._busy(False)
        plugins.load_all()
        self._refresh_installed(select=entry.id)
        self._fill_market()
        info = plugins.find(entry.id)
        if info is not None and info.error:
            self._status.setText(f"« {entry.name} » installé mais n'a pas pu démarrer (voir l'onglet Installés).")
        else:
            self._status.setText(f"« {entry.name} » v{entry.version} installé et actif.")

    def _on_install_failed(self, message: str) -> None:
        self._installing = False
        self._busy(False)
        self._on_market_selected(self._market_tree.currentItem(), None)
        QMessageBox.warning(self, "Installation impossible", message)
        self._status.setText("Installation annulée.")
