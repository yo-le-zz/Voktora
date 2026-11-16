"""Barre de recherche intelligente commune aux marketplaces (voir catalog_search.py pour la syntaxe)."""

from __future__ import annotations

import catalog_search as cs
from PySide6.QtCore import QStringListModel, Qt, QTimer, Signal
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

STATE_CHIPS = (("Installés", "is:installed"), ("Nouveaux", "is:new"), ("Mises à jour", "is:update"))
HELP = ("Syntaxe : mot · \"expression exacte\" · -exclure · tag:sombre ou #sombre · lang:rust · auteur:nom · perm:network · "
        "is:installed / new / update / active · sort:name / recent · limit:50")


class CatalogSearchBar(QWidget):
    changed = Signal(str)

    def __init__(self, placeholder: str = "Rechercher… (ex. sombre -bleu tag:clair)", parent=None):
        super().__init__(parent)
        self.index = cs.Index()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)
        self.edit.setMinimumHeight(34)
        self.edit.setToolTip(HELP)
        self.count = QLabel("")
        row.addWidget(self.edit, 1)
        row.addWidget(self.count)
        lay.addLayout(row)
        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self.edit)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self.edit.setCompleter(self._completer)
        self._chips_host = QWidget()
        self._chips = QHBoxLayout(self._chips_host)
        self._chips.setContentsMargins(0, 0, 0, 0)
        self._chips.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidget(self._chips_host)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(40)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(scroll)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)                  # frappe rapide + milliers d'éléments : on regroupe les recherches
        self._debounce.timeout.connect(lambda: self.changed.emit(self.edit.text()))
        self.edit.textChanged.connect(self._on_text)

    def text(self) -> str:
        return self.edit.text()

    def set_index(self, index: cs.Index) -> None:
        self.index = index
        while self._chips.count():
            item = self._chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for label, token in STATE_CHIPS:
            self._add_chip(label, token)
        for tag, n in index.facets("tags", 12):
            self._add_chip(f"#{tag} ({n})", f"tag:{tag}")
        for lang, n in index.facets("lang", 4):
            if len(index.facets("lang", 4)) > 1:
                self._add_chip(f"{lang} ({n})", f"lang:{lang}")
        self._chips.addStretch()

    def _add_chip(self, label: str, token: str) -> None:
        b = QPushButton(label)
        b.setCheckable(True)
        b.setFlat(False)
        b.setProperty("token", token)
        b.setChecked(token in self.edit.text().split())
        b.toggled.connect(lambda on, t=token: self._toggle(t, on))
        self._chips.addWidget(b)

    def _toggle(self, token: str, on: bool) -> None:
        words = [w for w in self.edit.text().split() if w != token]
        if on:
            words.append(token)
        self.edit.setText(" ".join(words))

    def _on_text(self, text: str) -> None:
        last = text.rsplit(" ", 1)[-1]
        head = text[: len(text) - len(last)]
        self._model.setStringList([head + s for s in self.index.suggest(last)])
        for i in range(self._chips.count()):
            w = self._chips.itemAt(i).widget()
            if w is not None and w.property("token"):
                w.blockSignals(True)
                w.setChecked(w.property("token") in text.split())
                w.blockSignals(False)
        self._debounce.start()

    def show_count(self, shown: int, total: int) -> None:
        self.count.setText(f"{shown} / {total}")
