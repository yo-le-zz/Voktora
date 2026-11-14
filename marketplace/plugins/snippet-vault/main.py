"""Snippet Vault — bibliothèque de morceaux de code, globale ou par projet : recherche, étiquettes, copie, export Markdown.

Montre : add_project_tab, add_palette_command, ask_choice, data_path, une logique pure testée (core.py).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import core


class SnippetTab(QWidget):
    def __init__(self, api, vault):
        super().__init__()
        self._api, self._vault, self._project, self._current = api, vault, None, None
        self._clip = api.set_clipboard_text
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher (titre, étiquette, code)…")
        self.search.setClearButtonEnabled(True)
        self.tag = QComboBox()
        self.scope = QComboBox()
        self.scope.addItems(["Globaux + ce projet", "Ce projet seulement"])
        new = QPushButton("Nouveau")
        new.clicked.connect(self.new)
        for w, s in ((self.search, 1), (self.tag, 0), (self.scope, 0), (new, 0)):
            top.addWidget(w, s)
        root.addLayout(top)
        split = QSplitter()
        self.list = QListWidget()
        split.addWidget(self.list)
        editor = QWidget()
        ev = QVBoxLayout(editor)
        ev.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("Titre")
        self.language = QComboBox()
        self.language.addItems(core.LANGUAGES)
        self.language.setEditable(True)
        row.addWidget(self.title, 1)
        row.addWidget(self.language)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("Étiquettes séparées par des virgules")
        self.code = QPlainTextEdit()
        self.code.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.code.setTabStopDistance(32)
        self.project_only = QPushButton("Réservé à ce projet")
        self.project_only.setCheckable(True)
        buttons = QHBoxLayout()
        self.save_btn, self.copy_btn, self.del_btn, self.export_btn = (QPushButton(t) for t in ("Enregistrer", "Copier le code", "Supprimer", "Exporter (Markdown)"))
        self.save_btn.clicked.connect(self.save)
        self.copy_btn.clicked.connect(self.copy)
        self.del_btn.clicked.connect(self.delete)
        self.export_btn.clicked.connect(self.export)
        for b in (self.save_btn, self.copy_btn, self.del_btn, self.export_btn):
            buttons.addWidget(b)
        self.state = QLabel("")
        self.state.setStyleSheet("color: gray;")
        for lay in (row,):
            ev.addLayout(lay)
        ev.addWidget(self.tags)
        ev.addWidget(self.project_only)
        ev.addWidget(self.code, 1)
        ev.addLayout(buttons)
        ev.addWidget(self.state)
        split.addWidget(editor)
        split.setSizes([280, 560])
        root.addWidget(split, 1)
        self.search.textChanged.connect(self.refresh)
        self.tag.currentIndexChanged.connect(self.refresh)
        self.scope.currentIndexChanged.connect(self.refresh)
        self.list.currentItemChanged.connect(self._select)
        self.refresh()

    def set_project(self, path):
        self._project = str(path) if path else ""
        self.project_only.setEnabled(bool(path))
        self.refresh()

    def visible(self):
        return self._vault.search(self.search.text(), self._project, self.tag.currentData() or "", self.scope.currentIndex() == 1)

    def refresh(self, *_):
        keep = self._current
        self.tag.blockSignals(True)
        current_tag = self.tag.currentData()
        self.tag.clear()
        self.tag.addItem("Toutes les étiquettes", "")
        for t in self._vault.all_tags():
            self.tag.addItem("#" + t, t)
        i = self.tag.findData(current_tag)
        self.tag.setCurrentIndex(max(0, i))
        self.tag.blockSignals(False)
        self.list.blockSignals(True)
        self.list.clear()
        for s in self.visible():
            item = QListWidgetItem(s.title + ("   (projet)" if s.project else ""))
            item.setData(Qt.UserRole, s.id)
            self.list.addItem(item)
            if s.id == keep:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if keep and self.list.currentItem() is None:
            self._clear()
        self.state.setText(f"{self.list.count()} snippet(s)")

    def _clear(self):
        self._current = None
        for w in (self.title, self.tags):
            w.setText("")
        self.code.setPlainText("")
        self.language.setCurrentIndex(0)
        self.project_only.setChecked(False)

    def _select(self, item, _prev=None):
        if item is None:
            return
        s = self._vault.items[item.data(Qt.UserRole)]
        self._current = s.id
        self.title.setText(s.title)
        self.tags.setText(", ".join(s.tags))
        self.code.setPlainText(s.code)
        self.language.setCurrentText(s.language)
        self.project_only.setChecked(bool(s.project))

    def new(self):
        self._clear()
        self.list.clearSelection()
        self.title.setFocus()

    def save(self):
        scope = self._project if (self.project_only.isChecked() and self._project) else ""
        fields = dict(title=self.title.text(), code=self.code.toPlainText(), language=self.language.currentText().strip(),
                      tags=core.parse_tags(self.tags.text()), project=scope)
        if self._current and self._current in self._vault.items:
            s = self._vault.update(self._current, **fields)
        else:
            s = self._vault.add(**fields)
        self._current = s.id
        self.refresh()
        self.state.setText("Enregistré")

    def copy(self):
        if self.code.toPlainText():
            self._clip(self.code.toPlainText())
            self._api.notify("Code copié")

    def delete(self):
        if self._current and self._vault.delete(self._current):
            self._clear()
            self.refresh()

    def export(self):
        self._clip(core.to_markdown(self.visible()))
        self._api.notify("Snippets copiés (Markdown)")


def on_load(api):
    vault = core.Vault(api.data_path("snippets.json"))
    tabs = []

    def factory(_ctx):
        tab = SnippetTab(api, vault)
        tabs.append(tab)
        return tab

    api.add_project_tab("Snippets", factory, icon="mdi:code-braces-box")

    def copy_one(*_):
        project = api.current_project()
        found = vault.search("", str(project) if project else "")
        if not found:
            api.notify("Aucun snippet : créez-en dans l'onglet « Snippets »")
            return
        labels = [s.title for s in found]
        choice = api.ask_choice("Snippet", "Copier quel snippet ?", labels)
        if choice:
            api.set_clipboard_text(found[labels.index(choice)].code)
            api.notify("Code copié")

    api.add_palette_command("Copier un snippet…", copy_one)
    api.add_menu_action("Outils", "Copier un snippet…", copy_one, icon="mdi:code-braces-box")
