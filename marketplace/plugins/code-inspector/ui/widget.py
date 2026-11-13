"""Interface du Code Inspector : vues graphiques, arborescence, recherche, fiche de fonction, qualité, dépendances, exports."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import exporters
from ..core import engine
from ..core.model import CALLABLE_KINDS
from ..services import views
from ..storage.store import Store
from .graph_view import GraphView

CERT_CHOICES = [("Tout (certain + probable + inconnu)", "inconnu"), ("Certain + probable", "probable"), ("Certain seulement", "certain")]
GRAPH_VIEWS = ["architecture", "files", "classes", "calls", "ffi"]


def _alive(fn):
    """Ignore le résultat d'une tâche asynchrone si le widget a déjà été détruit (fermeture, rechargement)."""
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except RuntimeError:
            return None
    return wrapper


class InspectorWidget(QWidget):
    """`run_async(work, on_done, on_error)` : fourni par l'API du plugin (testable avec une version synchrone)."""

    def __init__(self, api=None, store: Store | None = None, run_async=None, options=None):
        super().__init__()
        self.api, self.store, self._run_async, self.opts = api, store, run_async, options or {}
        self.root: Path | None = None
        self.analysis = None
        self._cancel = threading.Event()
        self._progress = (0, 1, "")
        self.focus_id = ""
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # ---------------------------------------------------------------- construction
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.title = QLabel("Sélectionnez un projet")
        self.btn_run = QPushButton("Analyser")
        self.btn_force = QPushButton("Tout réanalyser")
        self.btn_cancel = QPushButton("Annuler")
        self.btn_cancel.setEnabled(False)
        self.bar = QProgressBar()
        self.bar.setMaximumWidth(220)
        self.bar.setVisible(False)
        self.export_kind = QComboBox()
        for k, label in exporters.LABELS.items():
            self.export_kind.addItem(label, k)
        self.btn_export = QPushButton("Exporter…")
        for w in (self.title,):
            top.addWidget(w, 1)
        for w in (self.bar, self.btn_run, self.btn_force, self.btn_cancel, self.export_kind, self.btn_export):
            top.addWidget(w)
        lay.addLayout(top)
        self.status = QLabel("")
        lay.addWidget(self.status)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.btn_run.clicked.connect(lambda: self.analyze(False))
        self.btn_force.clicked.connect(lambda: self.analyze(True))
        self.btn_cancel.clicked.connect(self._cancel.set)
        self.btn_export.clicked.connect(self.do_export)

        # vues graphiques
        gw = QWidget()
        gl = QVBoxLayout(gw)
        bar = QHBoxLayout()
        self.view_combo = QComboBox()
        for k in GRAPH_VIEWS:
            self.view_combo.addItem(views.VIEWS[k], k)
        self.cert_combo = QComboBox()
        for label, v in CERT_CHOICES:
            self.cert_combo.addItem(label, v)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Surligner un nom…")
        self.depth = QSpinBox()
        self.depth.setRange(1, 6)
        self.depth.setValue(2)
        self.depth.setPrefix("profondeur ")
        for w in (QLabel("Vue :"), self.view_combo, self.cert_combo, self.depth, self.find):
            bar.addWidget(w)
        gl.addLayout(bar)
        self.graph = GraphView()
        gl.addWidget(self.graph, 1)
        self.view_notes = QLabel("")
        self.view_notes.setWordWrap(True)
        gl.addWidget(self.view_notes)
        self.tabs.addTab(gw, "Graphes")
        self.view_combo.currentIndexChanged.connect(self.refresh_view)
        self.cert_combo.currentIndexChanged.connect(self.refresh_view)
        self.depth.valueChanged.connect(self.refresh_view)
        self.find.textChanged.connect(lambda t: self.graph.highlight(t))
        self.graph.node_clicked.connect(self.select_node)
        self.graph.node_activated.connect(self.focus_calls)

        # arborescence
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Élément", "Type", "Détail"])
        self.tree.itemClicked.connect(lambda it, _c: self.select_node(it.data(0, Qt.UserRole)))
        self.tabs.addTab(self.tree, "Arborescence")

        # recherche + fiche
        sp = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Chercher une fonction, classe, fichier…")
        self.results = QListWidget()
        ll.addWidget(self.search)
        ll.addWidget(self.results)
        self.card = QTextBrowser()
        self.card.setOpenLinks(False)
        self.card.anchorClicked.connect(lambda url: self.select_node(url.toString()))
        sp.addWidget(left)
        sp.addWidget(self.card)
        sp.setSizes([320, 600])
        self.tabs.addTab(sp, "Recherche & fiche")
        self.search.textChanged.connect(self.do_search)
        self.results.itemClicked.connect(lambda it: self.select_node(it.data(Qt.UserRole)))

        # chaînes
        self.chains = QTreeWidget()
        self.chains.setHeaderLabels(["Chaîne d'exécution", "Maillon le plus faible"])
        self.tabs.addTab(self.chains, "Chaînes d'exécution")

        # qualité
        self.issues = QTableWidget(0, 5)
        self.issues.setHorizontalHeaderLabels(["Gravité", "Code", "Fichier:ligne", "Problème", "Piste"])
        self.tabs.addTab(self.issues, "Qualité")
        self.deps = QTableWidget(0, 5)
        self.deps.setHorizontalHeaderLabels(["Nom", "Écosystème", "Contrainte", "Utilisée ?", "Remarques"])
        self.tabs.addTab(self.deps, "Dépendances")
        self.summary = QTextBrowser()
        self.tabs.insertTab(0, self.summary, "Résumé")
        self.tabs.setCurrentIndex(0)

    # ---------------------------------------------------------------- projet / analyse
    def set_project(self, path) -> None:
        self.root = Path(path) if path else None
        self.analysis = None
        self.title.setText(f"Projet : {self.root.name}" if self.root else "Sélectionnez un projet")
        self.status.setText("Cliquez sur « Analyser ».")
        if self.root and self.store and self.opts.get("auto_analyze"):
            self.analyze(False)

    def analyze(self, force: bool = False) -> None:
        if not self.root:
            self.status.setText("Aucun projet sélectionné.")
            return
        self._cancel.clear()
        self.btn_run.setEnabled(False)
        self.btn_force.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.bar.setVisible(True)
        root, store = self.root, self.store
        ignore = [x.strip() for x in str(self.opts.get("ignore", "")).split(",") if x.strip()]

        def progress(i, n, rel):
            self._progress = (i, n, rel)

        def work():
            return engine.analyze(root, store, progress, self._cancel, force, ignore)
        if self._run_async is None:
            result, error = [], []
            t = threading.Thread(target=lambda: self._guard(work, result, error), daemon=True)
            t.start()
            self._poll_thread = (t, result, error)
            self._timer.start(100)
        else:
            self._run_async(work, _alive(self._done), _alive(self._failed))

    @staticmethod
    def _guard(work, result, error) -> None:
        try:
            result.append(work())
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    def _tick(self) -> None:
        i, n, rel = self._progress
        self.bar.setMaximum(max(n, 1))
        self.bar.setValue(i)
        self.status.setText(f"Analyse… {rel}")
        t, result, error = self._poll_thread
        if not t.is_alive():
            self._timer.stop()
            self._done(result[0]) if result else self._failed(error[0])

    def _reset_buttons(self) -> None:
        self.btn_run.setEnabled(True)
        self.btn_force.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.bar.setVisible(False)

    def _failed(self, exc) -> None:
        self._reset_buttons()
        self.status.setText("Analyse annulée." if isinstance(exc, engine.Cancelled) else f"Erreur d'analyse : {exc}")

    def _done(self, analysis) -> None:
        self._reset_buttons()
        self.analysis = analysis
        s = analysis.stats
        self.status.setText(f"Terminé : {s['scanned']} fichiers ({s['analyzed']} analysés, {s['reused']} réutilisés depuis le cache) "
                            f"en {analysis.report['duration']} s.")
        self.fill_all()

    # ---------------------------------------------------------------- remplissage
    def fill_all(self) -> None:
        a = self.analysis
        r = a.report
        c = r["graph"]["certainties"]
        rows = "".join(f"<tr><td>{x['name']}</td><td>{x['files']}</td><td>{x['loc']}</td><td>{x['share']} %</td></tr>" for x in r["languages"])
        eps = "".join(f"<li>{e['kind']} — <code>{e['file']}</code></li>" for e in r["entry_points"]) or "<li>aucun détecté</li>"
        self.summary.setHtml(
            f"<h2>{Path(a.root).name}</h2><p>{r['graph']['nodes']} éléments, {r['graph']['edges']} relations "
            f"(<b>{c['certain']}</b> certaines, <b>{c['probable']}</b> probables, <b>{c['inconnu']}</b> inconnues — rien n'est inventé).</p>"
            f"<table border=1 cellpadding=4><tr><th>Langage</th><th>Fichiers</th><th>Lignes</th><th>Part</th></tr>{rows}</table>"
            f"<p><b>Frameworks :</b> {', '.join(r['frameworks']) or '—'}</p><h3>Points d'entrée</h3><ul>{eps}</ul>"
            f"<p><b>Problèmes :</b> {r['issues']['total']}</p>")
        self.refresh_view()
        self.fill_tree()
        self.fill_chains()
        self.fill_tables()
        self.do_search(self.search.text())

    def refresh_view(self) -> None:
        if not self.analysis:
            return
        g, name, cert = self.analysis.graph, self.view_combo.currentData(), self.cert_combo.currentData()
        depth = self.depth.value()
        v = {"architecture": lambda: views.architecture(g, depth=depth, min_certainty=cert),
             "files": lambda: views.files(g, min_certainty=cert, depth=depth),
             "classes": lambda: views.classes(g, min_certainty=cert),
             "calls": lambda: views.calls(g, focus=self.focus_id, depth=depth, min_certainty=cert),
             "ffi": lambda: views.ffi(g)}[name]()
        self.graph.show_view(v, cert)
        self.view_notes.setText(v.get("notes", ""))

    def fill_tree(self) -> None:
        self.tree.clear()
        stack: list[QTreeWidgetItem] = []
        for row in views.tree(self.analysis.graph):
            item = QTreeWidgetItem([row["label"], row["kind"], row["info"]])
            item.setData(0, Qt.UserRole, row["id"])
            del stack[row["depth"]:]
            (stack[-1].addChild(item) if stack else self.tree.addTopLevelItem(item))
            stack.append(item)
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setExpanded(True)

    def fill_chains(self) -> None:
        self.chains.clear()
        for ch in views.chains(self.analysis.graph, self.analysis.report["entry_points"]):
            top = QTreeWidgetItem([f"{ch['entry'].split('::')[-1]} ({ch['kind']}) — {ch['reachable']} éléments atteignables", ""])
            for p in ch["chains"]:
                top.addChild(QTreeWidgetItem([" → ".join(s.split("::")[-1] for s in p["steps"]), p["weakest"]]))
            self.chains.addTopLevelItem(top)
            top.setExpanded(True)

    def fill_tables(self) -> None:
        a = self.analysis
        self.issues.setRowCount(0)
        for i in a.issues[:2000]:
            r = self.issues.rowCount()
            self.issues.insertRow(r)
            for c, v in enumerate([i.severity, i.code, f"{i.file}:{i.line}", i.title, i.hint]):
                self.issues.setItem(r, c, QTableWidgetItem(str(v)))
        self.deps.setRowCount(0)
        for d in a.dependencies:
            r = self.deps.rowCount()
            self.deps.insertRow(r)
            used = {True: "oui", False: "non trouvée", None: "?"}[d["used"]]
            for c, v in enumerate([d["name"], d["ecosystem"], d.get("spec", ""), used, ", ".join(d["problems"])]):
                self.deps.setItem(r, c, QTableWidgetItem(str(v)))

    # ---------------------------------------------------------------- recherche / fiche
    def do_search(self, text: str) -> None:
        self.results.clear()
        if not self.analysis:
            return
        for s in self.analysis.graph.search(text, limit=150):
            it = QListWidgetItem(f"{s.name}  —  {s.kind} · {s.file}:{s.line}")
            it.setData(Qt.UserRole, s.id)
            self.results.addItem(it)

    def select_node(self, nid: str) -> None:
        g = self.analysis.graph if self.analysis else None
        if not g or nid not in g.nodes:
            return
        s = g.nodes[nid]
        link = lambda i: f"<a href='{i}'>{g.nodes[i].name if i in g.nodes else i}</a>"  # noqa: E731
        if s.kind in CALLABLE_KINDS or s.kind in ("class", "struct", "trait", "enum", "file"):
            c = g.function_card(nid)
            rows = lambda lst, k: "".join(f"<li>{link(x['id'])} <i>({x['certainty']})</i> {x.get('note', '')}</li>" for x in lst) or "<li>—</li>"  # noqa: E731
            self.card.setHtml(
                f"<h2>{s.name}</h2><p><b>Type :</b> {s.kind} ({s.lang}) · <code>{s.file}:{s.line}</code></p>"
                f"<p><b>Signature :</b> <code>{c['signature']}</code></p><p>{c['doc'] or ''}</p>"
                f"<p><b>Paramètres :</b> {', '.join(map(str, c['params'])) or '—'} · <b>Retour :</b> {c['returns'] or '—'} · "
                f"<b>Complexité :</b> {c['complexity']}</p>"
                f"<h3>Appelée par</h3><ul>{rows(c['callers'], 'c')}</ul><h3>Appelle</h3><ul>{rows(c['callees'], 'c')}</ul>"
                f"<h3>Dépendances du fichier</h3><ul>{''.join(f'<li>{link(d)}</li>' for d in c['dependencies']) or '<li>—</li>'}</ul>")
            self.tabs.setCurrentWidget(self.card.parentWidget() if self.card.parentWidget() else self.card)
        else:
            self.card.setHtml(f"<h2>{s.name}</h2><p>{s.kind} — <code>{s.id}</code></p>")
        self.focus_id = nid if s.kind in CALLABLE_KINDS else self.focus_id

    def focus_calls(self, nid: str) -> None:
        self.focus_id = nid
        i = self.view_combo.findData("calls")
        self.view_combo.setCurrentIndex(i)
        self.refresh_view()

    # ---------------------------------------------------------------- exports
    def do_export(self, path: str | None = None) -> str | None:
        if not self.analysis:
            self.status.setText("Lancez d'abord une analyse.")
            return None
        kind = self.export_kind.currentData()
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Exporter", f"inspection{exporters.FORMATS[kind]}")
            if not path:
                return None
        try:
            exporters.export(self.analysis, kind, path, view=self.view_combo.currentData() if self.view_combo.currentData() != "ffi" else "ffi")
        except Exception as exc:  # noqa: BLE001 — montrer l'erreur à l'utilisateur
            QMessageBox.warning(self, "Export impossible", str(exc))
            return None
        self.status.setText(f"Exporté : {path}")
        return path



