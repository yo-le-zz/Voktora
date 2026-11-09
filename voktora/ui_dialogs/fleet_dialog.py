"""
Voktora — ui_dialogs.fleet_dialog (1.1.0)
Vue d'ensemble : état Git de tous les projets, actions groupées (fetch / pull), recherche globale, projets orphelins,
tickets / demandes de fusion / CI d'un projet. Les calculs tournent dans des threads : l'interface ne se fige pas.
"""

from __future__ import annotations

import html
import threading

import fleet
import forges
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

FILTERS = (("Tous", lambda s: True), ("À traiter", lambda s: not s.clean),
           ("Modifications", lambda s: s.dirty or s.untracked), ("En retard", lambda s: s.behind),
           ("À pousser", lambda s: s.ahead), ("Sans distant", lambda s: s.is_git and not s.has_remote))
CI_ICON = {"success": "✅", "failure": "❌", "pending": "⏳", "none": "—"}


class _Signals(QObject):
    state = Signal(object, int, int)
    done = Signal(str)
    hits = Signal(list)
    activity = Signal(object)
    bulk = Signal(str, bool, str, int, int)


class FleetDialog(QDialog):
    open_project = Signal(str)

    def __init__(self, parent=None, workers: int = 4):
        super().__init__(parent)
        self.setWindowTitle("Vue d'ensemble des projets")
        self.setMinimumSize(860, 560)
        self._workers = workers
        self._states: list[fleet.RepoState] = []
        self._cancel = threading.Event()
        self._sig = _Signals()
        self._sig.state.connect(self._on_state)
        self._sig.done.connect(self._on_done)
        self._sig.hits.connect(self._show_hits)
        self._sig.activity.connect(self._show_activity)
        self._sig.bulk.connect(self._on_bulk)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_state(), "📊 État")
        tabs.addTab(self._build_search(), "🔎 Recherche")
        tabs.addTab(self._build_activity(), "🔀 Tickets & CI")
        tabs.addTab(self._build_orphans(), "👻 Orphelins")
        v.addWidget(tabs)

    # ── État ──
    def _build_state(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer par nom…")
        self.filter.textChanged.connect(self._fill)
        from PySide6.QtWidgets import QComboBox
        self.kind = QComboBox()
        for label, _fn in FILTERS:
            self.kind.addItem(label)
        self.kind.currentIndexChanged.connect(self._fill)
        scan = QPushButton("Analyser")
        scan.clicked.connect(self.scan)
        bar.addWidget(self.filter, 1)
        bar.addWidget(self.kind)
        bar.addWidget(scan)
        lay.addLayout(bar)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Projet", "Branche", "Modifs", "Retard", "Avance", "Problèmes"])
        self.table.setRootIsDecorated(False)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.itemDoubleClicked.connect(lambda it, _c: self.open_project.emit(it.data(0, Qt.UserRole)))
        lay.addWidget(self.table, 1)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.summary = QLabel("Cliquez sur « Analyser ».")
        lay.addWidget(self.progress)
        lay.addWidget(self.summary)
        acts = QHBoxLayout()
        self.btn_fetch = QPushButton("Fetch (sélection ou tout)")
        self.btn_fetch.clicked.connect(lambda: self._bulk("fetch"))
        self.btn_pull = QPushButton("Pull sans fusion (sélection ou tout)")
        self.btn_pull.setToolTip("git pull --ff-only : ignore les projets avec modifications locales ; jamais de push ni de commit")
        self.btn_pull.clicked.connect(lambda: self._bulk("pull"))
        stop = QPushButton("Arrêter")
        stop.clicked.connect(self._cancel.set)
        acts.addWidget(self.btn_fetch)
        acts.addWidget(self.btn_pull)
        acts.addStretch()
        acts.addWidget(stop)
        lay.addLayout(acts)
        return page

    def scan(self) -> None:
        self._cancel.clear()
        self._states = []
        self.table.clear()
        self.progress.setVisible(True)
        self.progress.setValue(0)
        threading.Thread(target=self._scan_thread, daemon=True, name="voktora-fleet-scan").start()

    def _scan_thread(self) -> None:
        fleet.scan_all(self._workers, self._cancel.is_set, lambda st, d, t: self._sig.state.emit(st, d, t))
        self._sig.done.emit("scan")

    def _on_state(self, state, done: int, total: int) -> None:
        self._states.append(state)
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        if done == total or done % 10 == 0:                  # pas de reconstruction du tableau à chaque projet
            self._fill()

    def _on_done(self, what: str) -> None:
        self.progress.setVisible(False)
        if what == "scan":
            self._fill()
            s = fleet.summary(self._states)
            self.summary.setText(f"{s['total']} projets — {s['clean']} propres, {s['dirty']} avec modifications, "
                                 f"{s['behind']} en retard, {s['ahead']} à pousser, {s['no_remote']} sans distant, "
                                 f"{s['not_git']} sans Git, {s['missing']} manquants")

    def _fill(self, *_a) -> None:
        text = self.filter.text().lower()
        keep = FILTERS[self.kind.currentIndex()][1]
        self.table.setUpdatesEnabled(False)
        self.table.clear()
        for st in self._states:
            if text and text not in st.name.lower() or not keep(st):
                continue
            item = QTreeWidgetItem([st.name, st.branch, str(st.dirty + st.untracked), str(st.behind), str(st.ahead),
                                    ", ".join(st.problems) or "✓ propre"])
            item.setData(0, Qt.UserRole, st.path)
            item.setData(1, Qt.UserRole, st.name)
            if st.problems:
                item.setForeground(5, QColor("#f9e2af"))
            self.table.addTopLevelItem(item)
        self.table.setUpdatesEnabled(True)
        for col in range(5):
            self.table.resizeColumnToContents(col)

    def _targets(self) -> list[tuple[str, str]]:
        chosen = self.table.selectedItems() or [self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount())]
        return [(it.data(1, Qt.UserRole), it.data(0, Qt.UserRole)) for it in chosen]

    def _bulk(self, op: str) -> None:
        targets = self._targets()
        if not targets:
            return
        self._cancel.clear()
        self.progress.setVisible(True)
        self.progress.setMaximum(len(targets))
        self.progress.setValue(0)
        self.summary.setText(f"{op} sur {len(targets)} projet(s)…")

        def work() -> None:
            res = fleet.bulk(op, targets, 3, self._cancel.is_set,
                             lambda n, ok, msg, d, t: self._sig.bulk.emit(n, ok, msg, d, t))
            failed = [r for r in res if not r["ok"] and not r["skipped"]]
            skipped = sum(1 for r in res if r["skipped"])
            self._sig.done.emit(f"bulk:{op}: {len(res) - len(failed) - skipped} ok, {skipped} ignoré(s), {len(failed)} en échec"
                                + ("".join(f"\n• {r['name']} : {r['message']}" for r in failed[:8])))

        threading.Thread(target=work, daemon=True, name="voktora-fleet-bulk").start()

    def _on_bulk(self, name: str, ok: bool, msg: str, done: int, total: int) -> None:
        self.progress.setValue(done)

    # ── Recherche ──
    def _build_search(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Nom de projet, de fichier ou texte (2 caractères minimum)…")
        self.query.returnPressed.connect(self._search)
        self.in_content = QCheckBox("Dans le contenu des fichiers")
        self.in_content.setChecked(True)
        go = QPushButton("Chercher")
        go.clicked.connect(self._search)
        bar.addWidget(self.query, 1)
        bar.addWidget(self.in_content)
        bar.addWidget(go)
        lay.addLayout(bar)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda it: self.open_project.emit(it.data(Qt.UserRole)))
        lay.addWidget(self.results, 1)
        return page

    def _search(self) -> None:
        q, content = self.query.text(), self.in_content.isChecked()
        self.results.clear()
        self.results.addItem("Recherche…")
        threading.Thread(target=lambda: self._sig.hits.emit(fleet.search(q, content=content)), daemon=True,
                         name="voktora-fleet-search").start()

    def _show_hits(self, hits: list) -> None:
        self.results.clear()
        paths = dict(fleet.projects_list())
        for h in hits:
            where = f"{h.project}/{h.path}" if h.path else h.project
            label = f"[{h.kind}] {where}" + (f":{h.line}  {h.text}" if h.kind == "contenu" else "")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, paths.get(h.project, ""))
            self.results.addItem(item)
        if not hits:
            self.results.addItem("Aucun résultat.")

    # ── Tickets / CI ──
    def _build_activity(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        bar = QHBoxLayout()
        from PySide6.QtWidgets import QComboBox
        self.act_project = QComboBox()
        for name, path in fleet.projects_list():
            self.act_project.addItem(name, path)
        load = QPushButton("Charger (lecture seule)")
        load.clicked.connect(self._load_activity)
        bar.addWidget(self.act_project, 1)
        bar.addWidget(load)
        lay.addLayout(bar)
        self.act_view = QTextBrowser()
        self.act_view.setOpenExternalLinks(True)
        lay.addWidget(self.act_view, 1)
        return page

    def _load_activity(self) -> None:
        path = self.act_project.currentData()
        if not path:
            return
        self.act_view.setHtml("Chargement…")

        def work() -> None:
            try:
                self._sig.activity.emit(forges.project_activity(path))
            except forges.ForgeError as exc:
                self._sig.activity.emit({"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._sig.activity.emit({"error": f"{type(exc).__name__}: {exc}"})

        threading.Thread(target=work, daemon=True, name="voktora-forge-activity").start()

    def _show_activity(self, data: dict) -> None:
        if data.get("error"):
            self.act_view.setHtml(f"<p style='color:#f38ba8'>⚠ {html.escape(data['error'])}</p>")
            return
        def block(title: str, items: list) -> str:
            rows = "".join(f"<li><a href='{html.escape(i.get('url', ''))}'>#{i.get('number')}</a> {html.escape(i.get('title', ''))}"
                           f" <span style='color:#7f849c'>— {html.escape(i.get('author', ''))} {i.get('updated', '')}"
                           f"{' (brouillon)' if i.get('draft') else ''}</span></li>" for i in items) or "<li>aucun</li>"
            return f"<h4>{title} ({len(items)})</h4><ul>{rows}</ul>"
        ci = data.get("ci", {})
        errs = "".join(f"<p style='color:#f9e2af'>⚠ {html.escape(e)}</p>" for e in data.get("errors", []))
        self.act_view.setHtml(f"<h3>{html.escape(data['repo'])} <small>({html.escape(data['host'])})</small></h3>"
                              f"<p>Intégration continue : {CI_ICON.get(ci.get('state'), '—')} {html.escape(ci.get('name', ''))}</p>"
                              + block("Demandes de fusion ouvertes", data.get("pulls", []))
                              + block("Tickets ouverts", data.get("issues", [])) + errs)

    # ── Orphelins ──
    def _build_orphans(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Dossiers de votre racine de projets qui ne sont pas enregistrés dans Voktora :"))
        self.orphans = QListWidget()
        lay.addWidget(self.orphans, 1)
        refresh = QPushButton("Rechercher")
        refresh.clicked.connect(lambda: (self.orphans.clear(), self.orphans.addItems(fleet.find_orphans() or ["Aucun."])))
        lay.addWidget(refresh)
        return page

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cancel.set()
        super().closeEvent(event)
