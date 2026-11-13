"""Interface Project Knowledge : recherche, wiki, symboles, diagramme, historique, exports."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..core import exporters
from ..core.wiki import links
from ..services.knowledge import Knowledge


def _alive(fn):
    """Ignore le résultat d'une tâche asynchrone si le widget a déjà été détruit (fermeture, rechargement)."""
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except RuntimeError:
            return None
    return wrapper


class KnowledgeWidget(QWidget):
    def __init__(self, store, run_async=None, open_file=None, notify=None):
        super().__init__()
        self.store, self._async, self.open_file = store, run_async, open_file or (lambda path, line: None)
        self.notify = notify or (lambda m: None)
        self.k: Knowledge | None = None
        self.current_page = ""
        self._cancel = threading.Event()
        self._build()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.title = QLabel("Sélectionnez un projet")
        self.bar = QProgressBar()
        self.bar.setMaximumWidth(180)
        self.bar.setVisible(False)
        self.btn_refresh = QPushButton("Actualiser l'index")
        self.export_kind = QComboBox()
        self.export_kind.addItems(["Markdown", "HTML", "PDF", "Site statique"])
        self.btn_export = QPushButton("Exporter…")
        for w in (self.bar, self.btn_refresh, self.export_kind, self.btn_export):
            top.addWidget(w)
        top.insertWidget(0, self.title, 1)
        lay.addLayout(top)
        self.status = QLabel("")
        lay.addWidget(self.status)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        # recherche
        sw = QWidget()
        sl = QVBoxLayout(sw)
        row = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("Chercher dans tout le projet (fonction, concept, message d'erreur…)")
        self.mode = QComboBox()
        self.mode.addItem("Plein texte (BM25)", "lexical")
        self.mode.addItem("Similarité (TF-IDF, sans embeddings)", "similar")
        row.addWidget(self.q, 1)
        row.addWidget(self.mode)
        self.results = QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(["Fichier", "Ligne", "Rôle", "Extrait"])
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.setEditTriggers(QTableWidget.NoEditTriggers)
        sl.addLayout(row)
        sl.addWidget(self.results, 1)
        self.tabs.addTab(sw, "Recherche")
        # wiki
        ww = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        self.pages = QListWidget()
        self.btn_new, self.btn_del, self.btn_gen = QPushButton("Nouvelle page"), QPushButton("Supprimer"), QPushButton("Régénérer les pages automatiques")
        self.issues = QLabel("")
        self.issues.setWordWrap(True)
        for w in (self.pages, self.btn_new, self.btn_del, self.btn_gen, self.issues):
            ll.addWidget(w)
        mid = QWidget()
        ml = QVBoxLayout(mid)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Markdown. Liens : [[Autre page]] ou [[Autre page|texte]]. Citez des fichiers entre accents graves pour suivre leur péremption.")
        self.btn_save = QPushButton("Enregistrer la page")
        ml.addWidget(self.editor, 1)
        ml.addWidget(self.btn_save)
        self.preview = QTextBrowser()
        self.preview.setOpenLinks(False)
        self.preview.anchorClicked.connect(self._follow)
        ww.addWidget(left)
        ww.addWidget(mid)
        ww.addWidget(self.preview)
        ww.setSizes([220, 380, 380])
        self.tabs.addTab(ww, "Wiki")
        # symboles
        syw = QWidget()
        syl = QVBoxLayout(syw)
        self.sym_filter = QLineEdit()
        self.sym_filter.setPlaceholderText("Filtrer les symboles…")
        self.syms = QTableWidget(0, 5)
        self.syms.setHorizontalHeaderLabels(["Symbole", "Type", "Fichier", "Ligne", "Signature"])
        self.syms.horizontalHeader().setStretchLastSection(True)
        self.syms.setEditTriggers(QTableWidget.NoEditTriggers)
        syl.addWidget(self.sym_filter)
        syl.addWidget(self.syms)
        self.tabs.addTab(syw, "Symboles")
        # diagramme
        self.svg = QSvgWidget()
        self.tabs.addTab(self.svg, "Dépendances")
        # historique
        self.hist = QTextBrowser()
        self.tabs.addTab(self.hist, "Changements")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_export.clicked.connect(lambda: self.do_export())
        self.q.returnPressed.connect(self.search)
        self.mode.currentIndexChanged.connect(self.search)
        self.results.cellDoubleClicked.connect(self._open_hit)
        self.pages.currentTextChanged.connect(self.show_page)
        self.btn_new.clicked.connect(self.new_page)
        self.btn_del.clicked.connect(self.delete_page)
        self.btn_save.clicked.connect(self.save_page)
        self.btn_gen.clicked.connect(self.regenerate)
        self.sym_filter.textChanged.connect(self.fill_symbols)
        self.editor.textChanged.connect(self.render_preview)

    # ---------------------------------------------------------------- projet / actualisation
    def set_project(self, path) -> None:
        if not path:
            self.k = None
            self.title.setText("Sélectionnez un projet")
            return
        self.k = Knowledge(self.store, path)
        self.title.setText(f"Projet : {Path(path).name}")
        self.fill_all()
        if not self.k.index.files:
            self.status.setText("Premier lancement : cliquez sur « Actualiser l'index ».")

    def refresh(self) -> None:
        if not self.k:
            return
        self._cancel.clear()
        self.btn_refresh.setEnabled(False)
        self.bar.setVisible(True)
        state = {"p": (0, 1, "")}
        k = self.k

        def work():
            return k.refresh(lambda i, n, rel: state.update(p=(i, n, rel)), self._cancel)

        def done(rep):
            self.btn_refresh.setEnabled(True)
            self.bar.setVisible(False)
            self.status.setText(f"Index : +{len(rep['added'])} ~{len(rep['modified'])} −{len(rep['removed'])} fichiers ({rep['unchanged']} inchangés) · "
                                f"{len(rep['stale_pages'])} page(s) périmée(s)")
            if rep["stale_pages"]:
                self.notify(f"{len(rep['stale_pages'])} page(s) du wiki à relire (fichiers modifiés)")
            self.fill_all()

        def fail(exc):
            self.btn_refresh.setEnabled(True)
            self.bar.setVisible(False)
            self.status.setText(f"✗ {exc}")
        if self._async:
            self._async(work, _alive(done), _alive(fail))
        else:
            try:
                done(work())
            except Exception as exc:  # noqa: BLE001
                fail(exc)
        QTimer.singleShot(0, lambda: None)

    def fill_all(self) -> None:
        self.fill_pages()
        self.fill_symbols()
        self.fill_diagram()
        self.fill_history()
        self.search()

    # ---------------------------------------------------------------- recherche
    def search(self) -> None:
        self.results.setRowCount(0)
        if not self.k or not self.q.text().strip():
            return
        for h in self.k.index.search(self.q.text(), self.mode.currentData(), 40):
            r = self.results.rowCount()
            self.results.insertRow(r)
            for c, v in enumerate([h["path"], h["line"], h["role"], h["snippet"].replace("\n", " ⏎ ")]):
                self.results.setItem(r, c, QTableWidgetItem(str(v)))

    def _open_hit(self, row, _col) -> None:
        if self.k:
            self.open_file(str(Path(self.k.root) / self.results.item(row, 0).text()), int(self.results.item(row, 1).text()))

    # ---------------------------------------------------------------- wiki
    def fill_pages(self) -> None:
        self.pages.blockSignals(True)
        self.pages.clear()
        if self.k:
            stale = {s["page"] for s in self.k.wiki.stale(self.k.index)}
            for n in sorted(self.k.wiki.pages, key=lambda n: (n != "Vue d'ensemble", n)):
                self.pages.addItem(n + (" ⚠ périmée" if n in stale else ""))
            broken = self.k.wiki.broken_links()
            self.issues.setText((f"{len(broken)} lien(s) cassé(s) : " + ", ".join(f"{b['page']}→{b['target']}" for b in broken[:6]) if broken else "Aucun lien cassé.")
                                + (f"\nPages périmées : {', '.join(sorted(stale))}" if stale else ""))
        self.pages.blockSignals(False)

    def show_page(self, label: str) -> None:
        name = label.replace(" ⚠ périmée", "")
        if self.k and name in self.k.wiki.pages:
            self.current_page = name
            self.editor.setPlainText(self.k.wiki.pages[name]["text"])

    def render_preview(self) -> None:
        text = self.editor.toPlainText()
        for t in links(text):
            text = text.replace(f"[[{t}]]", f"[{t}](wiki:{t.replace(' ', '%20')})")
        self.preview.setMarkdown(text)

    def _follow(self, url) -> None:
        s = url.toString()
        if s.startswith("wiki:") and self.k:
            name = s[5:].replace("%20", " ")
            match = next((n for n in self.k.wiki.pages if n.lower() == name.lower()), None)
            if match:
                items = self.pages.findItems(match, Qt.MatchStartsWith)
                if items:
                    self.pages.setCurrentItem(items[0])
            else:
                self.status.setText(f"Page inexistante : {name} (« Nouvelle page » pour la créer)")

    def new_page(self, name: str | None = None) -> None:
        if not self.k:
            return
        name = name or f"Page {len(self.k.wiki.pages) + 1}"
        self.k.save_page(name, f"# {name}\n\n")
        self.fill_pages()

    def save_page(self) -> bool:
        if not self.k or not self.current_page:
            return False
        was_generated = self.k.wiki.pages[self.current_page].get("generated")
        self.k.save_page(self.current_page, self.editor.toPlainText())
        if was_generated:
            self.status.setText("Page automatique modifiée : elle devient manuelle (ne sera plus régénérée).")
        self.fill_pages()
        return True

    def delete_page(self) -> None:
        if self.k and self.current_page:
            self.k.delete_page(self.current_page)
            self.current_page = ""
            self.editor.clear()
            self.fill_pages()

    def regenerate(self) -> None:
        if self.k:
            updated = self.k.wiki.generate(self.k.index, self.k.root.name, self.k.index.changes)
            self.k.save()
            self.status.setText(f"Pages régénérées : {', '.join(updated) or 'aucune (déjà à jour)'}")
            self.fill_pages()

    # ---------------------------------------------------------------- autres onglets
    def fill_symbols(self) -> None:
        self.syms.setRowCount(0)
        if not self.k:
            return
        flt = self.sym_filter.text().lower()
        n = 0
        for s in self.k.index.all_symbols():
            if flt and flt not in s["name"].lower() and flt not in s["file"].lower():
                continue
            r = self.syms.rowCount()
            self.syms.insertRow(r)
            for c, v in enumerate([".".join(filter(None, [s["parent"], s["name"]])), s["kind"], s["file"], s["line"], s["signature"]]):
                self.syms.setItem(r, c, QTableWidgetItem(str(v)))
            n += 1
            if n >= 3000:
                break

    def fill_diagram(self) -> None:
        if self.k and self.k.index.files:
            self.svg.load(QByteArray(self.k.wiki.diagram_svg(self.k.index).encode()))

    def fill_history(self) -> None:
        import time
        if not self.k:
            return
        html = "".join(f"<h4>{time.strftime('%Y-%m-%d %H:%M', time.localtime(c['time']))}</h4><p>+{len(c['added'])} ~{len(c['modified'])} −{len(c['removed'])}</p>"
                       + "".join(f"<div>+ {s}</div>" for s in c["symbols_added"][:10]) + "".join(f"<div>− {s}</div>" for s in c["symbols_removed"][:10])
                       for c in self.k.index.changes)
        self.hist.setHtml(html or "Aucun changement enregistré.")

    # ---------------------------------------------------------------- exports
    def do_export(self, path: str | None = None, kind: str | None = None) -> str:
        if not self.k or not self.k.wiki.pages:
            self.status.setText("Actualisez l'index d'abord.")
            return ""
        kind = kind or self.export_kind.currentText()
        name = self.k.root.name
        svg = self.k.wiki.diagram_svg(self.k.index)
        try:
            if kind == "Site statique":
                path = path or QFileDialog.getExistingDirectory(self, "Dossier du site")
                if not path:
                    return ""
                exporters.to_site(self.k.wiki, name, path, svg)
            else:
                ext = {"Markdown": ".md", "HTML": ".html", "PDF": ".pdf"}[kind]
                path = path or QFileDialog.getSaveFileName(self, "Exporter", f"{name}{ext}")[0]
                if not path:
                    return ""
                if kind == "Markdown":
                    Path(path).write_text(exporters.to_markdown(self.k.wiki, name, self.k.index), encoding="utf-8")
                elif kind == "HTML":
                    Path(path).write_text(exporters.to_html(self.k.wiki, name, svg), encoding="utf-8")
                else:
                    exporters.to_pdf(self.k.wiki, name, path, svg)
        except OSError as exc:
            QMessageBox.warning(self, "Export impossible", str(exc))
            return ""
        self.status.setText(f"Exporté : {path}")
        return str(path)
