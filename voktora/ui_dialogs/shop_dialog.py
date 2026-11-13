"""
Voktora — ui_dialogs.shop_dialog (1.1.1)
Boutiques d'apparence : un onglet par boutique (Thèmes, Icônes, Styles), chacune avec ses propres sources.
"""

from __future__ import annotations

import threading
from pathlib import Path

import icons
import shops
import theme_manager
from plugins.manifest import is_newer
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

_newer = is_newer


def swatches(colors: list[str], width: int = 160, height: int = 22) -> QPixmap:
    pix = QPixmap(width, height)
    pix.fill(Qt.transparent)
    if not colors:
        return pix
    painter = QPainter(pix)
    step = width / len(colors)
    for i, color in enumerate(colors):
        painter.fillRect(int(i * step), 0, int(step) + 1, height, QColor(color))
    painter.end()
    return pix


class _Bridge(QObject):
    loaded = Signal(str, list, list)            # kind, items, errors
    done = Signal(str)                          # message
    failed = Signal(str)


class _ShopTab(QWidget):
    def __init__(self, kind: str, dialog: ShopDialog):
        super().__init__()
        self.kind, self.dialog = kind, dialog
        self._catalog: dict[str, shops.ShopItem] = {}
        v = QVBoxLayout(self)
        hint = QLabel(shops.KINDS[kind]["hint"])
        hint.setWordWrap(True)
        v.addWidget(hint)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setIconSize(QSize(160, 22))
        self.list.currentItemChanged.connect(self._select)
        self.detail = QTextBrowser()
        self.preview = QLabel()
        right = QVBoxLayout()
        right.addWidget(self.preview)
        right.addWidget(self.detail, 1)
        row.addWidget(self.list, 1)
        row.addLayout(right, 1)
        v.addLayout(row, 1)
        buttons = QHBoxLayout()
        self.btn_install = QPushButton("Installer")
        self.btn_apply = QPushButton("Appliquer")
        self.btn_remove = QPushButton("Désinstaller")
        self.btn_install.clicked.connect(self._install)
        self.btn_apply.clicked.connect(self._apply)
        self.btn_remove.clicked.connect(self._remove)
        sources = QPushButton("Sources…")
        sources.clicked.connect(self._sources)
        local = QPushButton("Depuis un dossier…")
        local.clicked.connect(self._local)
        refresh = QPushButton("Actualiser")
        refresh.clicked.connect(self.refresh)
        for b in (self.btn_install, self.btn_apply, self.btn_remove, sources, local, refresh):
            buttons.addWidget(b)
        buttons.addStretch()
        v.addLayout(buttons)
        self._select(None, None)

    # ── liste ──
    def refresh(self) -> None:
        self.dialog.status.setText("Chargement de la boutique…")
        kind = self.kind

        def work() -> None:
            try:
                items, errors = shops.fetch_catalog(kind)
            except Exception as exc:  # noqa: BLE001
                items, errors = [], [str(exc)]
            self.dialog.bridge.loaded.emit(kind, items, errors)

        threading.Thread(target=work, daemon=True, name=f"voktora-shop-{kind}").start()
        self.populate([])                                   # installés d'abord : utile hors ligne

    def populate(self, remote: list[shops.ShopItem]) -> None:
        self._catalog = {i.id: i for i in remote}
        current = self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None
        self.list.clear()
        local = {m["id"]: m for m in shops.installed(self.kind)}
        ids = list(dict.fromkeys([*local, *self._catalog]))
        for item_id in sorted(ids, key=lambda i: (local.get(i) or {}).get("name", self._catalog[i].name).lower()):
            meta = local.get(item_id)
            remote_item = self._catalog.get(item_id)
            name = (meta or {}).get("name") or remote_item.name
            colors = (meta or {}).get("colors") or (remote_item.colors if remote_item else [])
            state = ""
            if meta and remote_item and _newer(remote_item.version, str(meta.get("version", "0"))):
                state = "  ⟳ mise à jour"
            elif meta:
                state = "  ✓ installé"
            if self._is_active(item_id):
                state += "  ● actif"
            entry = QListWidgetItem(f"{name}{state}")
            entry.setData(Qt.UserRole, item_id)
            if self.kind == shops.KIND_THEMES and colors:
                entry.setIcon(QIcon(swatches(colors)))
            self.list.addItem(entry)
            if item_id == current:
                self.list.setCurrentItem(entry)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)

    def _is_active(self, item_id: str) -> bool:
        if self.kind == shops.KIND_THEMES:
            from core import get_app_config
            return get_app_config().get("theme") == item_id
        if self.kind == shops.KIND_ICONS:
            return shops.active_icon_pack() == item_id
        return item_id in shops.active_styles()

    def _current(self) -> tuple[str, dict | None, shops.ShopItem | None]:
        item = self.list.currentItem()
        if item is None:
            return "", None, None
        item_id = item.data(Qt.UserRole)
        meta = next((m for m in shops.installed(self.kind) if m["id"] == item_id), None)
        return item_id, meta, self._catalog.get(item_id)

    def _select(self, _a, _b) -> None:
        item_id, meta, remote = self._current()
        source = meta or (remote.__dict__ if remote else None)
        self.btn_install.setEnabled(remote is not None and (meta is None or _newer(remote.version, str(meta["version"]))))
        self.btn_install.setText("Mettre à jour" if meta else "Installer")
        self.btn_apply.setEnabled(meta is not None)
        self.btn_remove.setEnabled(meta is not None)
        if self.kind == shops.KIND_STYLES and meta is not None:
            self.btn_apply.setText("Désactiver" if item_id in shops.active_styles() else "Activer")
        elif self.kind == shops.KIND_ICONS and meta is not None and shops.active_icon_pack() == item_id:
            self.btn_apply.setText("Revenir aux icônes d'origine")
        else:
            self.btn_apply.setText("Appliquer")
        if not source:
            self.detail.setHtml("<p>Sélectionnez un objet.</p>")
            self.preview.clear()
            return
        esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
        self.detail.setHtml(f"<h3>{esc(source.get('name'))} <small>v{esc(source.get('version'))}</small></h3>"
                            f"<p><i>par {esc(source.get('author'))}</i></p><p>{esc(source.get('description'))}</p>"
                            f"<p style='color:#7f849c'>Source : {esc(source.get('source') or 'locale')}</p>")
        colors = source.get("colors") or []
        self.preview.setPixmap(swatches(colors, 320, 28) if colors else QPixmap())
        if self.kind == shops.KIND_ICONS and meta is not None:
            self._icon_grid(item_id)

    def _icon_grid(self, item_id: str) -> None:
        files = sorted(shops.item_dir(self.kind, item_id).rglob("*.svg"))[:24]
        pix = QPixmap(320, 40)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        for i, f in enumerate(files[:10]):
            QIcon(str(f)).paint(painter, i * 32, 4, 28, 28)
        painter.end()
        self.preview.setPixmap(pix)

    # ── actions ──
    def _run(self, work, ok: str) -> None:
        self.dialog.status.setText("Travail en cours…")

        def go() -> None:
            try:
                work()
                self.dialog.bridge.done.emit(ok)
            except Exception as exc:  # noqa: BLE001
                self.dialog.bridge.failed.emit(str(exc))

        threading.Thread(target=go, daemon=True).start()

    def _install(self) -> None:
        _id, _meta, remote = self._current()
        if remote is not None:
            self._run(lambda: shops.install(remote), f"« {remote.name} » installé.")

    def _apply(self) -> None:
        item_id, meta, _remote = self._current()
        if meta is None:
            return
        if self.kind == shops.KIND_THEMES:
            theme_manager.set_theme(item_id)
        elif self.kind == shops.KIND_ICONS:
            shops.set_icon_pack("" if shops.active_icon_pack() == item_id else item_id)
        else:
            shops.set_style_enabled(item_id, item_id not in shops.active_styles())
        theme_manager.apply_theme_to_app(QApplication.instance())
        self.dialog.status.setText("Appliqué. Les icônes déjà affichées changent à la réouverture des fenêtres.")
        self.populate(list(self._catalog.values()))

    def _remove(self) -> None:
        item_id, meta, _r = self._current()
        if meta is None:
            return
        if QMessageBox.question(self, "Désinstaller", f"Désinstaller « {meta['name']} » ?") == QMessageBox.Yes:
            shops.uninstall(self.kind, item_id)
            theme_manager.apply_theme_to_app(QApplication.instance())
            self.populate(list(self._catalog.values()))

    def _sources(self) -> None:
        current = "\n".join(f"• {n} — {u}" for n, u in shops.sources(self.kind))
        url, ok = QInputDialog.getText(self, "Sources de la boutique",
                                       f"Sources actuelles :\n{current}\n\nAjouter une source (https://…) :")
        if ok and url.strip():
            try:
                shops.add_source(self.kind, url.strip(), url.strip())
            except shops.ShopError as exc:
                QMessageBox.warning(self, "Source refusée", str(exc))
                return
            self.refresh()

    def _local(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Dossier de l'objet (contient item.json)")
        if folder:
            try:
                shops.install_local(self.kind, Path(folder))
            except shops.ShopError as exc:
                QMessageBox.warning(self, "Refusé", str(exc))
                return
            self.populate(list(self._catalog.values()))


class ShopDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Boutiques d'apparence")
        self.setMinimumSize(820, 560)
        self.bridge = _Bridge()
        self.bridge.loaded.connect(self._loaded)
        self.bridge.done.connect(self._done)
        self.bridge.failed.connect(lambda m: self.status.setText(f"Erreur : {m}"))
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.shop_tabs: dict[str, _ShopTab] = {}
        for kind, meta in shops.KINDS.items():
            tab = _ShopTab(kind, self)
            self.shop_tabs[kind] = tab
            self.tabs.addTab(tab, icons.icon(meta["icon"]), meta["label"])
        v.addWidget(self.tabs, 1)
        v.addWidget(self.status)
        for tab in self.shop_tabs.values():
            tab.refresh()

    def _loaded(self, kind: str, items: list, errors: list) -> None:
        self.shop_tabs[kind].populate(items)
        self.status.setText(" · ".join(errors) if errors else "")

    def _done(self, message: str) -> None:
        self.status.setText(message)
        for tab in self.shop_tabs.values():
            tab.populate(list(tab._catalog.values()))
