"""Interface de Workflow Forge : palette, éditeur visuel, paramètres, déclencheurs, exécution, journaux et historique."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import blocks, engine, triggers, validation
from ..core.proc import run as proc_run
from ..storage import store as store_mod
from .editor import FlowScene, FlowView


def _alive(fn):
    """Ignore le résultat d'une tâche asynchrone si le widget a déjà été détruit (fermeture, rechargement)."""
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except RuntimeError:
            return None
    return wrapper


class ForgeWidget(QWidget):
    def __init__(self, store, run_async=None, notify=None, options=None, runner=proc_run, http=None):
        super().__init__()
        self.store, self._async, self.notify, self.opts = store, run_async, notify or (lambda m: None), options or {}
        self.runner, self.http = runner, http
        self.project: str | None = None
        self.wf_id = ""
        self.wf: dict = validation.new_workflow()
        self.cancel = threading.Event()
        self.manager: triggers.Manager | None = None
        self.running = False
        self._build()

    # ------------------------------------------------------------------ construction
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.combo = QComboBox()
        self.btns = {}
        for key, text in (("new", "Nouveau"), ("save", "Enregistrer"), ("del", "Supprimer"), ("check", "Valider"), ("run", "Exécuter"), ("dry", "Test à blanc"),
                          ("stop", "Annuler"), ("imp", "Importer…"), ("exp", "Exporter…"), ("fit", "Ajuster")):
            b = QPushButton(text)
            self.btns[key] = b
            bar.addWidget(b)
        bar.insertWidget(0, self.combo, 1)
        self.btns["stop"].setEnabled(False)
        lay.addLayout(bar)
        self.status = QLabel("")
        lay.addWidget(self.status)
        split = QSplitter()
        # palette
        left = QWidget()
        ll = QVBoxLayout(left)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Chercher un bloc…")
        self.palette = QTreeWidget()
        self.palette.setHeaderHidden(True)
        ll.addWidget(self.search)
        ll.addWidget(self.palette, 1)
        ll.addWidget(QLabel("Double-clic : ajouter. Glisser depuis le rond de sortie vers un bloc : relier. Suppr : supprimer."))
        split.addWidget(left)
        # éditeur
        self.scene = FlowScene()
        self.view = FlowView(self.scene)
        split.addWidget(self.view)
        # droite : paramètres, déclencheurs
        right = QTabWidget()
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.form_host)
        right.addTab(sc, "Bloc")
        tw = QWidget()
        tl = QVBoxLayout(tw)
        self.trig = QPlainTextEdit()
        self.trig.setPlaceholderText('[{"kind":"cron","expr":"*/5 * * * *"}, {"kind":"interval","seconds":30}, {"kind":"file_change","pattern":"*.py"}, '
                                     '{"kind":"http_in","token":"(16 caractères minimum)","path":"/hook"}]')
        self.enabled = QCheckBox("Déclencheurs actifs")
        self.btn_trig = QPushButton("Appliquer les déclencheurs")
        for w in (QLabel("Types : manual, on_start, on_open, file_change, git_head, github_poll, http_in (127.0.0.1, jeton obligatoire), interval, cron"),
                  self.trig, self.enabled, self.btn_trig):
            tl.addWidget(w)
        right.addTab(tw, "Déclencheurs")
        split.addWidget(right)
        split.setSizes([230, 760, 330])
        # bas : journal / historique
        self.bottom = QTabWidget()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.runs = QTableWidget(0, 5)
        self.runs.setHorizontalHeaderLabels(["Heure", "Workflow", "Mode", "Résultat", "Détail"])
        self.runs.horizontalHeader().setStretchLastSection(True)
        self.runs.setEditTriggers(QTableWidget.NoEditTriggers)
        self.bottom.addTab(self.log, "Journal")
        self.bottom.addTab(self.runs, "Historique")
        v = QSplitter(Qt.Vertical)
        v.addWidget(split)
        v.addWidget(self.bottom)
        v.setSizes([600, 180])
        lay.addWidget(v, 1)
        self.btns["new"].clicked.connect(lambda: self.new_workflow())
        self.btns["save"].clicked.connect(self.save)
        self.btns["del"].clicked.connect(self.delete)
        self.btns["check"].clicked.connect(self.check)
        self.btns["run"].clicked.connect(lambda: self.execute(False))
        self.btns["dry"].clicked.connect(lambda: self.execute(True))
        self.btns["stop"].clicked.connect(self.cancel.set)
        self.btns["imp"].clicked.connect(lambda: self.import_file())
        self.btns["exp"].clicked.connect(lambda: self.export_file())
        self.btns["fit"].clicked.connect(self.view.fit)
        self.combo.activated.connect(lambda _i: self.open_workflow(self.combo.currentData()))
        self.search.textChanged.connect(self.fill_palette)
        self.palette.itemDoubleClicked.connect(self._palette_add)
        self.scene.node_selected.connect(self.show_form)
        self.btn_trig.clicked.connect(self.apply_triggers)
        self.runs.cellClicked.connect(self._show_run)
        self.fill_palette()

    def fill_palette(self) -> None:
        flt = self.search.text().lower().strip()
        self.palette.clear()
        cats: dict[str, QTreeWidgetItem] = {}
        for b in sorted(blocks.REGISTRY.values(), key=lambda b: (b.category, b.title)):
            if flt and flt not in b.title.lower() and flt not in b.type and flt not in b.category.lower():
                continue
            cat = cats.get(b.category) or QTreeWidgetItem([b.category])
            if b.category not in cats:
                cats[b.category] = cat
                self.palette.addTopLevelItem(cat)
            it = QTreeWidgetItem([b.title])
            it.setData(0, Qt.UserRole, b.type)
            it.setToolTip(0, b.doc)
            cat.addChild(it)
            cat.setExpanded(True)

    def _palette_add(self, item, _col) -> None:
        t = item.data(0, Qt.UserRole)
        if t:
            c = self.view.mapToScene(self.view.viewport().rect().center())
            self.scene.add_node(t, QPointF(c.x() - 88, c.y() - 29))

    # ------------------------------------------------------------------ workflows
    def set_project(self, path) -> None:
        self.project = str(path) if path else None
        self.refresh_list()
        items = self.store.workflows(self.project)
        if items:
            self.open_workflow(next(iter(items)))
        else:
            self.new_workflow()
        self.refresh_runs()
        self.setup_triggers()

    def refresh_list(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        for k, v in self.store.workflows(self.project).items():
            self.combo.addItem(v.get("name", k), k)
        i = self.combo.findData(self.wf_id)
        self.combo.setCurrentIndex(max(i, 0) if self.combo.count() else -1)
        self.combo.blockSignals(False)

    def new_workflow(self, name: str | None = None) -> None:
        name = name or (QInputDialog.getText(self, "Nouveau workflow", "Nom :")[0] if self.isVisible() else "Nouveau workflow") or "Nouveau workflow"
        self.wf = validation.new_workflow(name)
        self.wf_id = ""
        self.scene.load(self.wf)
        self.trig.setPlainText(json.dumps(self.wf["triggers"], indent=1))
        self.enabled.setChecked(True)

    def open_workflow(self, wf_id) -> None:
        wf = self.store.workflows(self.project).get(wf_id)
        if not wf:
            return
        self.wf_id, self.wf = wf_id, wf
        self.scene.load(self.wf)
        self.view.fit()
        self.trig.setPlainText(json.dumps(self.wf.get("triggers", []), indent=1))
        self.enabled.setChecked(self.wf.get("enabled", True))
        self.refresh_list()

    def save(self) -> str:
        self.wf_id = self.store.save_workflow(self.project, self.wf, self.wf_id or None)
        self.refresh_list()
        self.status.setText(f"Enregistré : {self.wf['name']}")
        self.setup_triggers()
        return self.wf_id

    def delete(self) -> None:
        if self.wf_id:
            self.store.delete_workflow(self.project, self.wf_id)
            self.wf_id = ""
            self.refresh_list()
            self.new_workflow("Nouveau workflow")
            self.setup_triggers()

    def check(self) -> dict:
        r = validation.validate(self.wf)
        self.status.setText("✓ valide" + (f" ({len(r['warnings'])} avertissement(s))" if r["warnings"] else "") if not r["errors"] else f"✗ {len(r['errors'])} erreur(s)")
        self.log.setPlainText("\n".join([*(f"✗ {e}" for e in r["errors"]), *(f"⚠ {w}" for w in r["warnings"])]) or "Aucun problème détecté.")
        return r

    # ------------------------------------------------------------------ formulaire de paramètres
    def show_form(self, node_id: str) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        it = self.scene.items_by_id.get(node_id)
        if not it:
            return
        d = it.data
        b = blocks.REGISTRY.get(d["type"])
        label = QLineEdit(str(d.get("label", "")))

        def set_label(t):
            d["label"] = t
            it.refresh_text()
        label.textChanged.connect(set_label)
        self.form.addRow("Nom affiché", label)
        for q in (b.params if b else []):
            self.form.addRow(q.name + (" *" if q.required else ""), self._editor(d, q))
        opts = d.setdefault("options", {})
        for key, text, kind in (("retries", "Tentatives supplémentaires", int), ("retry_delay", "Délai entre tentatives (s)", float), ("timeout", "Délai maximal (s, 0 = aucun)", float)):
            w = QDoubleSpinBox() if kind is float else QSpinBox()
            w.setMaximum(100000)
            w.setValue(opts.get(key, 0))
            w.valueChanged.connect(lambda v, k=key: opts.__setitem__(k, v))
            self.form.addRow(text, w)
        c = QCheckBox("Continuer si ce bloc échoue")
        c.setChecked(bool(opts.get("continue_on_error")))
        c.toggled.connect(lambda v: opts.__setitem__("continue_on_error", v))
        self.form.addRow(c)

    @staticmethod
    def _editor(d: dict, q: blocks.Param) -> QWidget:
        params = d.setdefault("params", {})
        cur = params.get(q.name, q.default)
        if q.kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(cur))
            w.toggled.connect(lambda v: params.__setitem__(q.name, v))
        elif q.kind == "int":
            w = QSpinBox()
            w.setRange(-1_000_000, 1_000_000)
            w.setValue(int(cur or 0))
            w.valueChanged.connect(lambda v: params.__setitem__(q.name, v))
        elif q.kind == "choice":
            w = QComboBox()
            w.addItems(list(q.choices))
            w.setCurrentText(str(cur))
            w.currentTextChanged.connect(lambda v: params.__setitem__(q.name, v))
        elif q.kind in ("code", "text", "json"):
            w = QPlainTextEdit(str(cur))
            w.setMaximumHeight(110)
            w.textChanged.connect(lambda: params.__setitem__(q.name, w.toPlainText()))
        else:
            w = QLineEdit(str(cur))
            w.textChanged.connect(lambda v: params.__setitem__(q.name, v))
        if q.kind == "expr":
            w.setPlaceholderText("expression : vars.x > 1, out.bloc.champ, upper(...)")
        return w

    # ------------------------------------------------------------------ exécution
    def execute(self, dry: bool, trigger: dict | None = None, wait: bool = True) -> dict | None:
        if self.running:
            self.status.setText("Une exécution est déjà en cours.")
            return None
        problems = self.check()
        if problems["errors"]:
            return None
        self.cancel = threading.Event()
        self.running = True
        self.btns["stop"].setEnabled(True)
        self.scene.clear_marks()
        self.log.clear()
        wf, project, cancel = json.loads(json.dumps(self.wf)), self.project or "", self.cancel
        lines: list = []
        marks: list = []

        def on_event(kind, payload):
            if kind == "log":
                lines.append(payload)
            elif kind == "node":
                marks.append((payload["id"], payload["status"]))

        def work():
            return engine.run_workflow(wf, project, trigger or {"kind": "manual"}, {}, dry, cancel, self.runner, self.http, self.notify, on_event)

        def done(rec):
            self.running = False
            self.btns["stop"].setEnabled(False)
            for nid, st in marks:
                self.scene.mark(nid, st)
            self.log.setPlainText(rec["log"] or rec.get("error", ""))
            ok = rec["ok"]
            word = "terminé" if ok else ("annulé" if rec["cancelled"] else "ÉCHEC")
            self.status.setText(f"{'Test à blanc' if dry else 'Exécution'} {word} — {rec.get('error', '')}".rstrip(" —"))
            self.store.add_run(self.project, self.wf_id or "?", {k: rec[k] for k in ("workflow", "started", "finished", "ok", "cancelled", "dry_run", "error", "log", "nodes")})
            self.refresh_runs()
            if not dry and self.opts.get("notify", True):
                self.notify(f"Workflow « {rec['workflow']} » : {word}")

        def fail(exc):
            self.running = False
            self.btns["stop"].setEnabled(False)
            self.status.setText(f"✗ {exc}")
        if self._async:
            self._async(work, _alive(done), _alive(fail))
            return None
        try:
            rec = work()
        except Exception as exc:  # noqa: BLE001
            fail(exc)
            return None
        done(rec)
        return rec

    def refresh_runs(self) -> None:
        self._runs = self.store.runs(self.project)
        self.runs.setRowCount(0)
        for r in self._runs:
            i = self.runs.rowCount()
            self.runs.insertRow(i)
            for c, v in enumerate([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.get("started", 0))), r.get("workflow", ""), "à blanc" if r.get("dry_run") else "réel",
                                   "✓" if r.get("ok") else "✗", r.get("error", "")]):
                self.runs.setItem(i, c, QTableWidgetItem(str(v)))

    def _show_run(self, row, _c) -> None:
        if 0 <= row < len(self._runs):
            self.log.setPlainText(self._runs[row].get("log", ""))
            self.bottom.setCurrentIndex(0)

    # ------------------------------------------------------------------ déclencheurs
    def apply_triggers(self) -> bool:
        try:
            t = json.loads(self.trig.toPlainText() or "[]")
            if not isinstance(t, list):
                raise ValueError("une liste est attendue")
        except ValueError as exc:
            self.status.setText(f"✗ Déclencheurs : {exc}")
            return False
        self.wf["triggers"], self.wf["enabled"] = t, self.enabled.isChecked()
        if validation.validate(self.wf)["errors"]:
            self.check()
            return False
        self.save()
        return True

    def setup_triggers(self) -> None:
        if self.manager:
            self.manager.clear()
        if not self.project or not self.opts.get("triggers", True):
            return
        mgr = triggers.Manager(self._fire, self.project, self._git_head)
        for wf_id, wf in self.store.workflows(self.project).items():
            if not wf.get("enabled", True):
                continue
            for t in wf.get("triggers", []):
                if t.get("kind") in ("manual",):
                    continue
                try:
                    mgr.register(wf_id, t)
                except (triggers.TriggerError, ValueError, OSError) as exc:
                    self.status.setText(f"Déclencheur ignoré ({wf.get('name')}) : {exc}")
        self.manager = mgr
        if self.opts.get("triggers", True):
            mgr.start()

    def _git_head(self, project: str) -> str:
        r = self.runner(["git", "rev-parse", "HEAD"], cwd=project, timeout=10)
        return r.out.strip() if r.ok else ""

    def _fire(self, wf_id: str, payload: dict) -> None:
        wf = self.store.workflows(self.project).get(wf_id)
        if not wf or self.running:
            return
        if wf_id != self.wf_id:
            self.wf_id, self.wf = wf_id, wf
        self.execute(False, payload)

    def open_event(self, kind: str) -> None:
        if self.manager:
            self.manager.event(kind, {"project": self.project})

    # ------------------------------------------------------------------ import / export
    def export_file(self, path: str | None = None) -> str:
        path = path or QFileDialog.getSaveFileName(self, "Exporter", f"{self.wf['name']}.json")[0]
        if not path:
            return ""
        Path(path).write_text(store_mod.export_text(self.wf), encoding="utf-8")
        self.status.setText(f"Exporté : {path} (les jetons HTTP ne sont pas exportés)")
        return path

    def import_file(self, path: str | None = None) -> bool:
        path = path or QFileDialog.getOpenFileName(self, "Importer", "", "Workflows (*.json)")[0]
        if not path:
            return False
        try:
            wf = store_mod.import_text(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import impossible", str(exc)) if self.isVisible() else None
            self.status.setText(f"✗ Import impossible : {exc}")
            return False
        self.wf, self.wf_id = wf, ""
        self.save()
        self.scene.load(self.wf)
        self.view.fit()
        return True

    def closeEvent(self, ev):  # noqa: N802
        if self.manager:
            self.manager.stop()
        super().closeEvent(ev)
