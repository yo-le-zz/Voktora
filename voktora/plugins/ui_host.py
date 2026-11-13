"""
Voktora — plugins.ui_host
Pont entre l'API des plugins et la fenêtre principale : menus, barre d'outils, onglets de projet,
panneaux latéraux, widgets de barre d'état, menu contextuel, styles.

Tout ce qu'un plugin ajoute est enregistré dans `info.teardown` (par l'API) : désactiver ou
désinstaller un plugin retire proprement ses éléments, sans redémarrage.
"""

from __future__ import annotations

import contextlib
import re
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import icons
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .runtime import PluginContext, PluginInfo

_MENU_PREFIX = re.compile(r"^[^\w]+", re.UNICODE)


def _plain(title: str) -> str:
    """« 🛠️ Outils » / « &Outils » -> « outils » (comparaison de titres de menus)."""
    return _MENU_PREFIX.sub("", title.replace("&", "")).strip().casefold()


class _Poster(QObject):
    """Ramène l'exécution d'une fonction sur le thread de l'interface."""
    call = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.call.connect(lambda fn: fn())


class CollapsiblePanel(QWidget):
    """En-tête cliquable + contenu repliable (panneaux latéraux de plugins)."""

    def __init__(self, title: str, content: QWidget, icon: str = "", expanded: bool = True) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        self._header = QToolButton()
        self._header.setText(title)
        self._header.setCheckable(True)
        self._header.setChecked(expanded)
        self._header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._header.setStyleSheet("QToolButton { border: none; font-weight: 600; text-align: left; padding: 4px; }")
        if icon:
            self._header.setIcon(icons.icon(icon))
        self._header.toggled.connect(self._toggle)
        self.content = content
        content.setVisible(expanded)
        layout.addWidget(self._header)
        layout.addWidget(content)

    def _toggle(self, expanded: bool) -> None:
        self._header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)


class UIHost:
    """Implémente côté Qt ce que `PluginAPI` expose. Une instance par fenêtre principale."""

    def __init__(self, window: Any) -> None:
        self._w = window
        self._poster = _Poster()
        self._toolbar: QToolBar | None = None
        self._context_actions: list[tuple[PluginInfo, str, str, str, Callable]] = []
        self._tab_widgets: list[tuple[PluginInfo, QWidget]] = []
        self._context_override: Path | None = None
        self._owned_menus: set[QMenu] = set()        # menus créés par des plugins (donc à nettoyer)

    @property
    def window(self) -> Any:
        return self._w

    # -- utilitaires -------------------------------------------------------------
    def post(self, fn: Callable[[], None]) -> None:
        self._poster.call.emit(fn)

    def log(self, message: str) -> None:
        self._w._log(message)

    def current_project(self) -> Path | None:
        return self._context_override or self._w._sel_path

    def restyle(self) -> None:
        import theme_manager
        theme_manager.apply_theme_to_app(QApplication.instance())

    def _icon(self, icon_id: str):
        return icons.icon(icon_id) if icon_id else None

    @staticmethod
    def _guard(info: PluginInfo, what: str, build: Callable[[], QWidget]) -> QWidget:
        """Construit un widget de plugin ; en cas d'erreur, affiche le message à sa place."""
        try:
            return build()
        except Exception:
            info.note_error(f"{what} : {traceback.format_exc()}")
            label = QLabel(f"Le plugin « {info.name} » a rencontré une erreur.\n(Paramètres → Plugins)")
            label.setWordWrap(True)
            return label

    # -- menus ------------------------------------------------------------------------
    def _find_menu(self, parent: Any, title: str) -> QMenu | None:
        wanted = _plain(title)
        for action in parent.actions():
            menu = action.menu()
            if menu is not None and _plain(action.text()) == wanted:
                return menu
        return None

    def add_menu_action(self, info: PluginInfo, path: str, label: str, handler: Callable, icon: str,
                        shortcut: str, checkable: bool, checked: bool, tooltip: str) -> QAction:
        menubar = self._w.menuBar()
        chain: list[tuple[Any, QMenu]] = []            # (parent, menu) de chaque niveau du chemin
        parts = [p.strip() for p in path.split("/") if p.strip()] or ["Plugins"]
        parent: Any = menubar
        menu: QMenu | None = None
        for index, part in enumerate(parts):
            found = self._find_menu(parent, part)
            if found is None:
                if index == 0:
                    found = QMenu(part, menubar)
                    help_menu = self._find_menu(menubar, "Aide")
                    if help_menu is not None:
                        menubar.insertMenu(help_menu.menuAction(), found)
                    else:
                        menubar.addMenu(found)
                else:
                    found = parent.addMenu(part)
                self._owned_menus.add(found)
            chain.append((parent, found))
            menu = found
            parent = found
        assert menu is not None
        action = QAction(label, menu)
        if icon:
            action.setIcon(icons.icon(icon))
        if tooltip:
            action.setToolTip(tooltip)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ApplicationShortcut)
        action.setCheckable(checkable)
        if checkable:
            action.setChecked(checked)
            action.toggled.connect(handler)
        else:
            action.triggered.connect(handler)
        menu.addAction(action)

        def undo() -> None:
            menu.removeAction(action)
            action.deleteLater()
            for owner, level in reversed(chain):          # retire les menus créés par des plugins devenus vides
                if level in self._owned_menus and not level.actions():
                    owner.removeAction(level.menuAction())
                    self._owned_menus.discard(level)
                    level.deleteLater()
        info.teardown.append(undo)
        return action

    # -- barre d'outils -------------------------------------------------------------------
    def _ensure_toolbar(self) -> QToolBar:
        if self._toolbar is None:
            self._toolbar = QToolBar("Plugins", self._w)
            self._toolbar.setObjectName("pluginToolbar")
            self._toolbar.setMovable(False)
            self._toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self._w.addToolBar(Qt.TopToolBarArea, self._toolbar)
            self._toolbar.hide()
        return self._toolbar

    def add_toolbar_button(self, info: PluginInfo, label: str, handler: Callable, icon: str,
                           tooltip: str) -> QAction:
        bar = self._ensure_toolbar()
        action = QAction(label, bar)
        if icon:
            action.setIcon(icons.icon(icon))
        action.setToolTip(tooltip or label)
        action.triggered.connect(handler)
        bar.addAction(action)
        bar.show()

        def undo() -> None:
            bar.removeAction(action)
            action.deleteLater()
            if not bar.actions():
                bar.hide()
        info.teardown.append(undo)
        return action

    # -- onglets de projet ------------------------------------------------------------------------
    def add_project_tab(self, info: PluginInfo, title: str, factory: Callable, icon: str) -> None:
        tabs = self._w._project_panel._tabs
        ctx = PluginContext(project_path=self.current_project(), log_cb=self.log)
        widget = self._guard(info, f"onglet « {title} »", lambda: factory(ctx))
        tabs.addTab(widget, icons.icon(icon) if icon else icons.icon("mdi:puzzle-outline"), title)
        entry = (info, widget)
        self._tab_widgets.append(entry)
        self._push_project(widget)

        def undo() -> None:
            index = tabs.indexOf(widget)
            if index >= 0:
                tabs.removeTab(index)
            widget.deleteLater()
            with contextlib.suppress(ValueError):
                self._tab_widgets.remove(entry)
        info.teardown.append(undo)

    def _push_project(self, widget: QWidget) -> None:
        setter = getattr(widget, "set_project", None)
        if callable(setter):
            try:
                setter(self._w._sel_path)
            except Exception:
                pass          # un plugin défaillant ne doit pas bloquer l'ouverture d'un projet

    def project_changed(self) -> None:
        """Appelé par la fenêtre à chaque changement de projet affiché."""
        for info, widget in list(self._tab_widgets):
            setter = getattr(widget, "set_project", None)
            if callable(setter):
                try:
                    setter(self._w._sel_path)
                except Exception:
                    info.note_error(f"set_project : {traceback.format_exc()}")

    # -- barre latérale / barre d'état ------------------------------------------------------------
    def add_sidebar_panel(self, info: PluginInfo, title: str, factory: Callable, icon: str) -> None:
        layout = self._w._sidebar_layout
        ctx = PluginContext(project_path=self.current_project(), log_cb=self.log)
        content = self._guard(info, f"panneau « {title} »", lambda: factory(ctx))
        panel = CollapsiblePanel(title, content, icon)
        layout.addWidget(panel)
        self._tab_widgets.append((info, content))
        self._push_project(content)

        def undo() -> None:
            layout.removeWidget(panel)
            panel.deleteLater()
            self._tab_widgets[:] = [t for t in self._tab_widgets if t[1] is not content]
        info.teardown.append(undo)

    def add_status_widget(self, info: PluginInfo, factory: Callable) -> None:
        bar = self._w.statusBar()
        ctx = PluginContext(project_path=self.current_project(), log_cb=self.log)
        widget = self._guard(info, "widget de barre d'état", lambda: factory(ctx))
        bar.addPermanentWidget(widget)

        def undo() -> None:
            bar.removeWidget(widget)
            widget.deleteLater()
        info.teardown.append(undo)

    # -- menu contextuel ---------------------------------------------------------------------------
    def add_context_action(self, info: PluginInfo, target: str, label: str, handler: Callable, icon: str) -> None:
        if target != "project":
            raise ValueError("Seule la cible « project » est disponible.")
        entry = (info, target, label, icon, handler)
        self._context_actions.append(entry)
        info.teardown.append(lambda: self._context_actions.remove(entry) if entry in self._context_actions else None)

    def context_actions(self, paths: list[str]) -> list[tuple[str, str, Callable[[], None]]]:
        """[(libellé, icône, appel)] pour le menu contextuel d'un ou plusieurs projets."""
        result: list[tuple[str, str, Callable[[], None]]] = []
        for _info, _target, label, icon, handler in self._context_actions:
            def run(h: Callable = handler, p: str = paths[0] if paths else "") -> None:
                self._context_override = Path(p) if p else None
                try:
                    h()
                finally:
                    self._context_override = None
            result.append((label, icon, run))
        return result

    # -- API 5 : raccourcis, docks, sélecteurs, Markdown, presse-papiers ------------------------------
    def add_shortcut(self, info: PluginInfo, sequence: str, handler: Callable, description: str = "") -> None:
        from PySide6.QtGui import QShortcut
        key = QKeySequence(sequence)
        if key.isEmpty():
            raise ValueError(f"Raccourci invalide : « {sequence} ».")
        shortcut = QShortcut(key, self._w)
        shortcut.setContext(Qt.ApplicationShortcut)
        shortcut.activated.connect(lambda: handler())
        info.teardown.append(lambda: (shortcut.setEnabled(False), shortcut.deleteLater()))

    def add_dock(self, info: PluginInfo, title: str, factory: Callable, area: str, icon: str) -> None:
        from PySide6.QtWidgets import QDockWidget
        areas = {"left": Qt.LeftDockWidgetArea, "right": Qt.RightDockWidgetArea,
                 "top": Qt.TopDockWidgetArea, "bottom": Qt.BottomDockWidgetArea}
        content = self._guard(info, title, lambda: factory(PluginContext(project_path=self.current_project(), log_cb=self.log)))
        dock = QDockWidget(title, self._w)
        dock.setObjectName(f"plugin-dock-{info.id}-{title}")
        if icon:
            dock.setWindowIcon(icons.icon(icon))
        dock.setWidget(content)
        self._w.addDockWidget(areas[area], dock)
        self._tab_widgets.append((info, content))

        def undo() -> None:
            self._w.removeDockWidget(dock)
            dock.deleteLater()
            self._tab_widgets[:] = [t for t in self._tab_widgets if t[1] is not content]

        info.teardown.append(undo)

    def pick_path(self, kind: str, title: str, start: str, file_filter: str) -> str | None:
        from PySide6.QtWidgets import QFileDialog
        if kind == "dir":
            value = QFileDialog.getExistingDirectory(self._w, title, start)
        elif kind == "save":
            value = QFileDialog.getSaveFileName(self._w, title, start, file_filter)[0]
        else:
            value = QFileDialog.getOpenFileName(self._w, title, start, file_filter)[0]
        return value or None

    def ask_choice(self, title: str, label: str, choices: list[str], default: int) -> str | None:
        value, ok = QInputDialog.getItem(self._w, title, label, choices, max(0, min(default, len(choices) - 1)), False)
        return value if ok else None

    def ask_number(self, title: str, label: str, default: float, low: float, high: float, decimals: int):
        if decimals > 0:
            value, ok = QInputDialog.getDouble(self._w, title, label, float(default), float(low), float(high), decimals)
        else:
            value, ok = QInputDialog.getInt(self._w, title, label, int(default), int(low), int(high))
        return value if ok else None

    def show_markdown(self, title: str, markdown: str) -> None:
        import markdown_lite
        from PySide6.QtWidgets import QDialog, QTextBrowser
        dlg = QDialog(self._w)
        dlg.setWindowTitle(title)
        dlg.resize(680, 520)
        layout = QVBoxLayout(dlg)
        view = QTextBrowser()
        view.setOpenLinks(False)
        view.anchorClicked.connect(lambda url: self.open_url(url.toString()))
        view.setHtml(markdown_lite.render(markdown))
        layout.addWidget(view)
        dlg.exec()

    def open_url(self, url: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))

    def clipboard_get(self) -> str:
        return QApplication.clipboard().text()

    def clipboard_set(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    # -- dialogues ----------------------------------------------------------------------------------
    def notify(self, message: str, timeout_ms: int = 4000) -> None:
        self._w._set_status(message, timeout_ms)

    def message(self, title: str, text: str) -> None:
        QMessageBox.information(self._w, title, text)

    def confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self._w, title, text) == QMessageBox.Yes

    def ask_text(self, title: str, label: str, default: str = "") -> str | None:
        value, ok = QInputDialog.getText(self._w, title, label, text=default)
        return value if ok else None

    def open_project(self, path: Path) -> None:
        self._w._on_project_selected(str(path))

    def refresh(self) -> None:
        self._w._invalidate_cache()
        self._w._refresh_all()
