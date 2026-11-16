"""Interface de Workflow Forge : palette, éditeur visuel, paramètres, déclencheurs, exécution, journaux et historique."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import blocks, engine, schema, templates, triggers, validation
from ..core.proc import run as proc_run
from ..storage import store as store_mod
from .editor import FlowScene, FlowView
from .props import PropertiesPanel


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
        self.history = schema.History()
        self._clip: dict | None = None
        self._paste_n = 0
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(700)
        self._autosave.timeout.connect(self.flush_autosave)
        self._build()
        self._loaded()

    # ------------------------------------------------------------------ construction
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.combo = QComboBox()
        self.btns = {}
        for key, text in (("new", "Nouveau"), ("save", "Enregistrer"), ("del", "Supprimer"), ("check", "Valider"), ("run", "Exécuter"), ("dry", "Test à blanc"),
                          ("stop", "Arrêter"), ("imp", "Importer…"), ("exp", "Exporter…"), ("fit", "Ajuster")):
            b = QPushButton(text)
            self.btns[key] = b
            bar.addWidget(b)
        bar.insertWidget(0, self.combo, 1)
        self.btns["stop"].setEnabled(False)
        lay.addLayout(bar)
        bar2 = QHBoxLayout()
        for key, text, tip in (("undo", "↶ Annuler", "Annuler la dernière modification (Ctrl+Z)"), ("redo", "↷ Rétablir", "Rétablir (Ctrl+Y)"),
                               ("dup", "Dupliquer", "Dupliquer les blocs sélectionnés (Ctrl+D)"), ("copy", "Copier", "Copier les blocs sélectionnés (Ctrl+C)"),
                               ("paste", "Coller", "Coller les blocs copiés (Ctrl+V)")):
            b = QPushButton(text)
            b.setToolTip(tip)
            self.btns[key] = b
            bar2.addWidget(b)
        self.btns["tpl"] = QPushButton("Modèles ▾")
        self.btns["tpl"].setToolTip("Ouvrir un workflow d'exemple")
        self.tpl_menu = QMenu(self)
        for key, title in templates.template_list():
            self.tpl_menu.addAction(title, lambda k=key: self.open_template(k))
        self.btns["tpl"].setMenu(self.tpl_menu)
        bar2.addWidget(self.btns["tpl"])
        bar2.addStretch(1)
        lay.addLayout(bar2)
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
        self.block_help = QLabel("Sélectionnez un bloc de la palette pour lire son aide.")
        self.block_help.setWordWrap(True)
        self.block_help.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ll.addWidget(self.block_help)
        ll.addWidget(QLabel("Double-clic : ajouter. Glisser depuis le rond de sortie vers un bloc : relier. Double-clic sur un bloc : modifier. Suppr : supprimer."))
        split.addWidget(left)
        # éditeur
        self.scene = FlowScene()
        self.view = FlowView(self.scene)
        split.addWidget(self.view)
        # droite : paramètres, déclencheurs
        right = QTabWidget()
        self.panel = PropertiesPanel()
        self.form = self.panel.form
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.panel)
        right.addTab(sc, "Bloc")
        ow = QWidget()
        ol = QVBoxLayout(ow)
        self.order_info = QLabel("")
        self.order_info.setWordWrap(True)
        self.order = QListWidget()
        self.order.setDragDropMode(QAbstractItemView.InternalMove)
        self.order.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, lambda: self.reorder_steps(self._list_order())))
        ol.addWidget(self.order_info)
        ol.addWidget(self.order, 1)
        right.addTab(ow, "Ordre")
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
        self.btns["undo"].clicked.connect(self.undo)
        self.btns["redo"].clicked.connect(self.redo)
        self.btns["dup"].clicked.connect(self.duplicate_selection)
        self.btns["copy"].clicked.connect(self.copy_selection)
        self.btns["paste"].clicked.connect(self.paste)
        self.combo.activated.connect(lambda _i: self.open_workflow(self.combo.currentData()))
        self.search.textChanged.connect(self.fill_palette)
        self.palette.itemDoubleClicked.connect(self._palette_add)
        self.scene.node_selected.connect(self.show_form)
        self.scene.node_activated.connect(lambda i: self.quick_edit(i))
        self.scene.changed_model.connect(lambda: self._model_changed())
        self.scene.node_moved.connect(lambda: self._model_changed())
        self.scene.action.connect(self._action)
        self.panel.changed.connect(self._panel_changed)
        self.palette.currentItemChanged.connect(self._palette_help)
        self.btn_trig.clicked.connect(self.apply_triggers)
        self.runs.cellClicked.connect(self._show_run)
        self.fill_palette()

    def fill_palette(self) -> None:
        flt = self.search.text().strip()
        self.palette.clear()
        cats: dict[str, QTreeWidgetItem] = {}
        found = schema.search_blocks(flt) if flt else sorted(blocks.REGISTRY.values(), key=lambda b: (b.category, b.title))
        for b in found:
            cat = cats.get(b.category) or QTreeWidgetItem([b.category])
            if b.category not in cats:
                cats[b.category] = cat
                self.palette.addTopLevelItem(cat)
            it = QTreeWidgetItem([b.title])
            it.setData(0, Qt.UserRole, b.type)
            it.setToolTip(0, schema.describe(b.type))
            cat.addChild(it)
            cat.setExpanded(True)
        if flt and not found:
            self.block_help.setText("Aucun bloc ne correspond à cette recherche.")

    def _palette_help(self, item, _prev=None) -> None:
        t = item.data(0, Qt.UserRole) if item else None
        b = blocks.REGISTRY.get(t) if t else None
        self.block_help.setText(f"{b.title}\n{schema.describe(t)}" if b else "Sélectionnez un bloc de la palette pour lire son aide.")

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
        self._loaded()

    def open_workflow(self, wf_id) -> None:
        wf = self.store.workflows(self.project).get(wf_id)
        if not wf:
            return
        self.wf_id, self.wf = wf_id, schema.upgrade_workflow(wf)
        self.scene.load(self.wf)
        self.view.fit()
        self.trig.setPlainText(json.dumps(self.wf.get("triggers", []), indent=1))
        self.enabled.setChecked(self.wf.get("enabled", True))
        self.refresh_list()
        self._loaded()

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
        it = self.scene.items_by_id.get(node_id)
        if not it:
            self.panel.clear()
            return
        self.panel.set_node(it.data, self.wf, project=self.project or "")

    def _show_selection(self) -> None:
        ids = self.scene.selected_ids()
        if len(ids) == 1:
            self.show_form(ids[0])
        else:
            self.panel.clear()

    def quick_edit(self, node_id: str, show: bool = True) -> QDialog | None:
        """Édition rapide (double-clic) : seulement les champs essentiels du bloc."""
        it = self.scene.items_by_id.get(node_id)
        if not it:
            return None
        dlg = QDialog(self)
        dlg.setWindowTitle("Modifier le bloc")
        dlg.resize(460, 380)
        lay = QVBoxLayout(dlg)
        panel = PropertiesPanel(dlg)
        panel.changed.connect(self._panel_changed)
        panel.set_node(it.data, self.wf, essential_only=True, project=self.project or "")
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(panel)
        lay.addWidget(sc, 1)
        close = QPushButton("Fermer")
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)
        dlg.panel = panel
        dlg.finished.connect(lambda _r: self.show_form(node_id) if self.scene.selected_ids() == [node_id] else None)
        if show:
            dlg.exec()
        return dlg

    def _panel_changed(self, node_id: str, key: str) -> None:
        self.scene.refresh_node(node_id)
        self._model_changed(f"{node_id}:{key}")

    # ------------------------------------------------------------------ modèle, historique, enregistrement automatique
    def _loaded(self) -> None:
        schema.upgrade_workflow(self.wf)
        self.history.reset(self.wf)
        self.panel.clear()
        self._paste_n = 0
        self.refresh_order()
        self._update_buttons()

    def _model_changed(self, key: str | None = None) -> None:
        if self.history.record(self.wf, key):
            self._autosave.start()
        if key is None:
            self.refresh_order()
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.btns["undo"].setEnabled(self.history.can_undo)
        self.btns["redo"].setEnabled(self.history.can_redo)

    def flush_autosave(self) -> bool:
        """Enregistre tout de suite les modifications en attente (sans relancer les déclencheurs)."""
        self._autosave.stop()
        if self.project is None or self.running:
            return False
        self.wf_id = self.store.save_workflow(self.project, self.wf, self.wf_id or None)
        self.refresh_list()
        self.status.setText(f"Enregistré automatiquement : {self.wf['name']}")
        return True

    def _apply_state(self, state: dict | None) -> bool:
        if state is None:
            return False
        sel = set(self.scene.selected_ids())
        schema.restore(self.wf, state)
        self.scene.reload([i for i in sel if i in {n["id"] for n in self.wf["nodes"]}])
        self._show_selection()
        self.refresh_order()
        self._update_buttons()
        self._autosave.start()
        return True

    def undo(self) -> bool:
        return self._apply_state(self.history.undo())

    def redo(self) -> bool:
        return self._apply_state(self.history.redo())

    def _action(self, name: str) -> None:
        {"copy": self.copy_selection, "paste": self.paste, "duplicate": self.duplicate_selection, "undo": self.undo, "redo": self.redo}[name]()

    # ------------------------------------------------------------------ copier / coller / dupliquer
    def copy_selection(self) -> bool:
        payload = schema.copy_nodes(self.wf, self.scene.selected_ids())
        if not payload["nodes"]:
            self.status.setText("Sélectionnez au moins un bloc (hors Démarrage) à copier.")
            return False
        self._clip, self._paste_n = payload, 0
        QApplication.clipboard().setText(schema.clip_text(payload))
        self.status.setText(f"{len(payload['nodes'])} bloc(s) copié(s).")
        return True

    def paste(self) -> list[str]:
        payload = schema.clip_parse(QApplication.clipboard().text()) or self._clip
        if not payload:
            self.status.setText("Rien à coller.")
            return []
        self._paste_n += 1
        ids = schema.paste_nodes(self.wf, payload, 40 * self._paste_n, 40 * self._paste_n)
        self._structure_changed(ids)
        return ids

    def duplicate_selection(self) -> list[str]:
        ids = schema.duplicate_nodes(self.wf, self.scene.selected_ids())
        self._structure_changed(ids)
        return ids

    def _structure_changed(self, select) -> None:
        self.scene.reload(select)
        self._model_changed()
        self._show_selection()

    # ------------------------------------------------------------------ ordre des étapes (glisser pour réordonner)
    def refresh_order(self) -> None:
        chain = schema.linear_chain(self.wf)
        nodes = {n["id"]: n for n in self.wf["nodes"]}
        self.order.blockSignals(True)
        self.order.clear()
        for i in chain:
            it = QListWidgetItem(f"{nodes[i].get('label') or i} — {schema.summary(nodes[i])}")
            it.setData(Qt.UserRole, i)
            self.order.addItem(it)
        self.order.blockSignals(False)
        self.order.setEnabled(bool(chain))
        self.order_info.setText("Glissez les lignes pour changer l'ordre d'exécution." if chain else
                                "Réordonnancement par glisser disponible pour une suite simple de blocs (Démarrage → a → b → c, sans branche). Ici, déplacez et reliez les blocs dans l'éditeur.")

    def _list_order(self) -> list[str]:
        return [self.order.item(i).data(Qt.UserRole) for i in range(self.order.count())]

    def reorder_steps(self, new_order: list[str]) -> bool:
        ok = schema.reorder_chain(self.wf, new_order)
        if ok:
            self.scene.reload(self.scene.selected_ids())
            self._model_changed()
        else:
            self.refresh_order()
        return ok

    # ------------------------------------------------------------------ modèles d'exemple
    def open_template(self, key: str) -> dict:
        self.wf, self.wf_id = templates.build(key), ""
        self.scene.load(self.wf)
        self.view.fit()
        self.trig.setPlainText(json.dumps(self.wf["triggers"], indent=1))
        self.enabled.setChecked(True)
        self._loaded()
        if self.project is not None:
            self.save()
        self.status.setText(f"Modèle ouvert : {self.wf['name']}")
        return self.wf

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
        schema.upgrade_workflow(self.wf)
        self.save()
        self.scene.load(self.wf)
        self.view.fit()
        self._loaded()
        return True

    def closeEvent(self, ev):  # noqa: N802
        if self.manager:
            self.manager.stop()
        super().closeEvent(ev)
