"""Git Insights 1.1 — tableau de bord Git du projet : état, auteurs, activité, fichiers chauds, derniers commits.

Montre : api.run (sans shell), run_async, add_project_tab, options, une logique pure (insights.py) testée sur un vrai dépôt.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import insights


def _table(headers, widths=()):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setStretchLastSection(True)
    for i, w in enumerate(widths):
        t.setColumnWidth(i, w)
    return t


def _fill(table, rows):
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            table.setItem(r, c, item)


class Card(QWidget):
    def __init__(self, title):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 6, 10, 6)
        self._title = QLabel(title)
        self._title.setStyleSheet("color: gray; font-size: 11px;")
        self.value = QLabel("—")
        self.value.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.value.setWordWrap(True)
        v.addWidget(self._title)
        v.addWidget(self.value)
        self.setStyleSheet("Card { border: 1px solid palette(mid); border-radius: 8px; }")


class InsightsTab(QWidget):
    def __init__(self, api):
        super().__init__()
        self._api, self._path, self._data = api, None, None
        self._run_clip = api.set_clipboard_text
        self._shell = api.run
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        head = QHBoxLayout()
        self._title = QLabel("Sélectionnez un projet")
        self._title.setStyleSheet("font-weight: 600; font-size: 14px;")
        refresh = QPushButton("Actualiser")
        refresh.clicked.connect(lambda: self.set_project(self._path))
        copy = QPushButton("Copier (Markdown)")
        copy.clicked.connect(self._copy)
        head.addWidget(self._title, 1)
        head.addWidget(refresh)
        head.addWidget(copy)
        layout.addLayout(head)
        self._message = QLabel("")
        self._message.setWordWrap(True)
        layout.addWidget(self._message)
        grid = QGridLayout()
        self._cards = {k: Card(t) for k, t in (("branch", "Branche"), ("commits", "Commits"), ("state", "Modifications"),
                                                ("sync", "Distant"))}
        for i, card in enumerate(self._cards.values()):
            grid.addWidget(card, 0, i)
        layout.addLayout(grid)
        tabs = QTabWidget()
        self._authors = _table(["Auteur", "Commits", ""], (220, 80))
        self._recent = _table(["Commit", "Date", "Auteur", "Message"], (70, 90, 140))
        self._hot = _table(["Fichier", "Modifs (90 j)"], (420,))
        self._activity = _table(["Semaine du", "Commits", ""], (100, 80))
        for table, name in ((self._recent, "Derniers commits"), (self._authors, "Auteurs"),
                            (self._hot, "Fichiers actifs"), (self._activity, "Activité")):
            tabs.addTab(table, name)
        layout.addWidget(tabs, 1)

    def set_project(self, path):
        self._path = path
        if path is None:
            self._title.setText("Sélectionnez un projet")
            self._message.setText("")
            return
        self._title.setText(f"Git — {path.name}")
        self._message.setText("Analyse en cours…")

        def run(args):
            return self._shell(args, cwd=path, timeout=20)

        self._api.run_async(lambda: insights.collect(run),
                            lambda d: self._show(path, d),
                            lambda exc: self._message.setText(f"Erreur : {exc}"))

    def _show(self, path, d):
        if path != self._path:
            return
        self._data = d
        if not d.get("repo"):
            self._message.setText("Ce dossier n'est pas un dépôt Git.")
            for c in self._cards.values():
                c.value.setText("—")
            for t in (self._authors, self._recent, self._hot, self._activity):
                t.setRowCount(0)
            return
        self._message.setText("")
        s = d["status"]
        self._cards["branch"].value.setText(d["branch"] + (f"  ·  {d['tag']}" if d["tag"] else ""))
        self._cards["commits"].value.setText(str(d["commits"]))
        clean = not any(s.values())
        self._cards["state"].value.setText("Propre" if clean else f"{s['staged']} indexé(s) · {s['modified']} modifié(s) · {s['untracked']} non suivi(s)")
        if d["ahead"] is None:
            self._cards["sync"].value.setText("Pas de suivi" if not d["remote"] else "Branche non suivie")
        else:
            self._cards["sync"].value.setText("À jour" if not (d["ahead"] or d["behind"]) else f"↑{d['ahead']} à pousser · ↓{d['behind']} à récupérer")
        top = max((c for _n, c in d["authors"]), default=0)
        _fill(self._authors, [(n, c, insights.bar(c, top)) for n, c in d["authors"]])
        _fill(self._recent, [(c["hash"], c["date"], c["author"], c["subject"]) for c in d["recent"]])
        _fill(self._hot, d["hot"])
        peak = max((c for _w, c in d["activity"]), default=0)
        _fill(self._activity, [(w, c, insights.bar(c, peak)) for w, c in d["activity"]])

    def _copy(self):
        if self._data:
            self._run_clip(insights.to_markdown(self._data, self._path.name if self._path else ""))
            self._api.notify("Résumé Git copié (Markdown)")


def on_load(api):
    api.add_project_tab("Git Insights", lambda ctx: InsightsTab(api), icon="mdi:source-branch")
