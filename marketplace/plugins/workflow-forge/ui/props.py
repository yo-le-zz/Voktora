"""Panneau de propriétés généré depuis le schéma des blocs : un champ typé par paramètre, validation en direct, bouton Réinitialiser."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QCompleter,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWidgets import QComboBox as _QComboBox

from ..core import blocks, schema


class QComboBox(_QComboBox):
    """Menu qui ignore la molette tant qu'il n'a pas le focus (évite de modifier une valeur en faisant défiler le panneau)."""

    def __init__(self, *a):
        super().__init__(*a)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, ev):  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(ev)
        else:
            ev.ignore()


def browse_path(parent, q: blocks.Param, current: str, project: str = "") -> str:
    """Boîte de dialogue « Parcourir » ; renvoie un chemin relatif au projet si possible, ou "" si annulé. Remplaçable dans les tests."""
    start = current or project or ""
    if q.mode == "dir":
        p = QFileDialog.getExistingDirectory(parent, "Choisir un dossier", start)
    elif q.mode == "save":
        p = QFileDialog.getSaveFileName(parent, "Choisir un fichier", start)[0]
    else:
        p = QFileDialog.getOpenFileName(parent, "Choisir un fichier", start)[0]
    return relative_to(p, project)


def relative_to(path: str, project: str) -> str:
    if not path or not project:
        return path or ""
    try:
        from pathlib import Path
        return Path(path).resolve().relative_to(Path(project).resolve()).as_posix()
    except (ValueError, OSError):
        return path


class Row:
    """Une ligne du formulaire : étiquette, champ, message d'erreur, bouton Réinitialiser."""

    def __init__(self, q: blocks.Param, container: QWidget, editor: QWidget, err: QLabel, reset: QToolButton, set_value):
        self.q, self.container, self.editor, self.err, self.reset, self.set_value = q, container, editor, err, reset, set_value


class PropertiesPanel(QWidget):
    changed = Signal(str, str)     # (identifiant du bloc, clé : nom du paramètre, "label" ou "options.<nom>")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.node: dict | None = None
        self.wf: dict = {}
        self.project = ""
        self.rows: dict[str, Row] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: bold;")
        self.help = QLabel("")
        self.help.setWordWrap(True)
        self.help.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.title)
        lay.addWidget(self.help)
        self.form = QFormLayout()
        self.form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        lay.addLayout(self.form)
        lay.addStretch(1)

    # ------------------------------------------------------------------ construction
    def clear(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.rows = {}
        self.node = None
        self.title.setText("Sélectionnez un bloc pour modifier ses paramètres.")
        self.help.setText("")

    def set_node(self, node: dict | None, wf: dict | None = None, *, essential_only: bool = False, project: str = "") -> None:
        self.clear()
        if not node:
            return
        schema.upgrade_node(node)
        self.node, self.wf, self.project = node, wf or {}, project or self.project
        b = blocks.REGISTRY.get(node["type"])
        self.title.setText(f"{b.title if b else node['type']}  ({node['id']})")
        self.help.setText(schema.describe(node["type"]) if b else "Type de bloc inconnu.")
        params = list(b.params) if b else []
        if essential_only:
            params = [q for q in params if q.essential] or params[:3]
        label = QLineEdit(str(node.get("label", "")))
        label.setToolTip("Nom affiché sur le bloc dans l'éditeur.")
        label.textChanged.connect(lambda t: self._set_label(t))
        self.label_edit = label
        self.form.addRow("Nom affiché", label)
        for q in params:
            row = self._make_row(q)
            self.rows[q.name] = row
            lab = QLabel(schema.param_label(q) + (" *" if q.required else ""))
            lab.setToolTip(self._tooltip(q))
            self.form.addRow(lab, row.container)
            self._refresh(q.name)
        if not essential_only:
            self._options()

    def _set_label(self, text: str) -> None:
        if self.node is not None:
            self.node["label"] = text
            self.changed.emit(self.node["id"], "label")

    def _options(self) -> None:
        opts = self.node.setdefault("options", {})
        for key, text, kind in (("retries", "Tentatives supplémentaires", int), ("retry_delay", "Délai entre tentatives (s)", float), ("timeout", "Délai maximal (s, 0 = aucun)", float)):
            w = QDoubleSpinBox() if kind is float else QSpinBox()
            w.setMaximum(100000)
            w.setValue(opts.get(key, 0))
            w.valueChanged.connect(lambda v, k=key: self._set_option(k, v))
            self.form.addRow(text, w)
        c = QCheckBox("Continuer si ce bloc échoue")
        c.setChecked(bool(opts.get("continue_on_error")))
        c.toggled.connect(lambda v: self._set_option("continue_on_error", v))
        self.form.addRow(c)

    def _set_option(self, key: str, value) -> None:
        self.node.setdefault("options", {})[key] = value
        self.changed.emit(self.node["id"], "options." + key)

    @staticmethod
    def _tooltip(q: blocks.Param) -> str:
        t = [q.help or schema_kind(q)]
        if q.example:
            t.append("Exemple : " + q.example)
        if q.kind == "choice":
            t.append("Choix : " + ", ".join(label for _v, label in schema.choice_items(q)))
        if q.templated and q.kind in ("str", "text", "pairs"):
            t.append("{{ expression }} permis.")
        return "\n".join(t)

    # ------------------------------------------------------------------ champs
    def _make_row(self, q: blocks.Param) -> Row:
        node = self.node
        value = schema.get_value(node, q)
        err = QLabel("")
        err.setWordWrap(True)
        err.setStyleSheet("color: #d63031;")
        err.setVisible(False)
        reset = QToolButton()
        reset.setText("↺")
        reset.setToolTip("Réinitialiser (valeur par défaut)")
        container = QWidget()
        grid = QVBoxLayout(container)
        grid.setContentsMargins(0, 0, 0, 2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        editor, set_value = self._editor(q, value)
        editor.setToolTip(self._tooltip(q))
        top.addWidget(editor, 1)
        if q.kind in ("str", "text", "json", "expr") and isinstance(editor, (QLineEdit, QPlainTextEdit)):
            top.addWidget(self._data_button(q, editor))
        top.addWidget(reset)
        grid.addLayout(top)
        grid.addWidget(err)
        row = Row(q, container, editor, err, reset, set_value)
        reset.clicked.connect(lambda: self._reset(q))
        return row

    def data_refs(self) -> list[tuple[str, str]]:
        """(texte du menu, expression) des données utilisables par le bloc : sorties des blocs en amont, variables, boucle, déclencheur."""
        node_id = self.node["id"] if self.node else ""
        refs = [(f"{r[4:].replace('.', ' → ')}", r) for r in schema.upstream_outputs(self.wf, node_id)]
        refs += [(f"variable {v}", f"vars.{v}") for v in schema.known_vars(self.wf, node_id)]
        refs += [("élément courant de la boucle (item)", "item"), ("numéro dans la boucle (index)", "index"), ("dossier du projet (project)", "project"),
                 ("données du déclencheur (trigger)", "trigger")]
        return refs

    def _data_button(self, q: blocks.Param, editor) -> QToolButton:
        """Menu « ⤵ » : insère à l'endroit du curseur la donnée d'un bloc précédent (ex. le contenu d'un fichier lu plus haut)."""
        from PySide6.QtWidgets import QMenu
        button = QToolButton()
        button.setText("⤵")
        button.setToolTip("Insérer une donnée venant d'un bloc précédent (contenu d'un fichier, réponse HTTP, variable…)")
        button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        button.setMenu(menu)

        def fill():
            menu.clear()
            for text, ref in self.data_refs():
                menu.addAction(text, lambda r=ref: self.insert_data(q, editor, r))
        menu.aboutToShow.connect(fill)
        return button

    def insert_data(self, q: blocks.Param, editor, ref: str) -> None:
        """Insère `ref` : brut dans un champ « expression », sinon sous la forme {{ref}}."""
        snippet = ref if q.kind == "expr" else "{{" + ref + "}}"
        if isinstance(editor, QPlainTextEdit):
            editor.insertPlainText(snippet)
        else:
            editor.insert(snippet)

    def _commit(self, q: blocks.Param, value) -> None:
        schema.set_param(self.node, q.name, value)
        self._refresh(q.name)
        self.changed.emit(self.node["id"], q.name)

    def _refresh(self, name: str) -> None:
        row = self.rows.get(name)
        if not row:
            return
        issue = schema.validate_param(self.node["type"], row.q, schema.get_value(self.node, row.q))
        row.err.setText(("✗ " if issue.is_error else "⚠ ") + issue.message if issue else "")
        row.err.setVisible(bool(issue))
        row.err.setStyleSheet("color: #d63031;" if issue and issue.is_error else "color: #b9770e;")
        row.editor.setProperty("invalid", bool(issue and issue.is_error))
        row.editor.setStyleSheet("border: 1px solid #d63031;" if issue and issue.is_error and isinstance(row.editor, (QLineEdit, QPlainTextEdit)) else "")
        row.reset.setEnabled(not schema.is_default(self.node, row.q))

    def _reset(self, q: blocks.Param) -> None:
        schema.reset_param(self.node, q)
        row = self.rows[q.name]
        row.set_value(schema.get_value(self.node, q))
        self._refresh(q.name)
        self.changed.emit(self.node["id"], q.name)

    # -- accès pour les tests et l'édition programmatique
    def editor(self, name: str) -> QWidget:
        return self.rows[name].editor

    def error_text(self, name: str) -> str:
        return self.rows[name].err.text()

    def set_value(self, name: str, value) -> None:
        """Modifie un champ comme le ferait l'utilisateur : le champ affiche la valeur, le bloc est mis à jour et la validation relancée."""
        row = self.rows[name]
        if row.q.kind == "pairs" and not isinstance(value, str):
            value = schema.dump_pairs(schema.parse_pairs(value))
        row.set_value(value)
        self._commit(row.q, value)

    def _editor(self, q: blocks.Param, cur):
        k = q.kind
        if k == "bool":
            w = QCheckBox("Activé")
            w.setChecked(bool(cur))
            w.toggled.connect(lambda v: self._commit(q, bool(v)))
            return w, lambda v: self._quiet(w, lambda: w.setChecked(bool(v)))
        if k in schema.NUMERIC and _is_number(q, cur):
            return self._spin(q, cur)
        if k == "choice":
            return self._choice(q, cur)
        if k == "var":
            return self._var(q, cur)
        if k == "path":
            return self._path(q, cur)
        if k == "pairs":
            return self._pairs(q, cur)
        if k in ("text", "code", "json"):
            w = QPlainTextEdit(str(cur if cur is not None else ""))
            w.setMinimumHeight(70)
            w.setMaximumHeight(180 if k != "code" else 260)
            if k == "code":
                w.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
                w.setLineWrapMode(QPlainTextEdit.NoWrap)
            if q.placeholder:
                w.setPlaceholderText(q.placeholder)
            w.textChanged.connect(lambda: self._commit(q, w.toPlainText()))
            return w, lambda v: self._quiet(w, lambda: w.setPlainText("" if v is None else str(v)))
        w = QLineEdit("" if cur is None else str(cur))
        w.setPlaceholderText(q.placeholder or ("expression : vars.x > 1, out.bloc.champ" if k == "expr" else ""))
        if k == "expr":
            words = [*(f"vars.{v}" for v in schema.known_vars(self.wf, self.node["id"])), *schema.upstream_outputs(self.wf, self.node["id"])]
            if words:
                comp = QCompleter(words, w)
                comp.setCaseSensitivity(Qt.CaseInsensitive)
                w.setCompleter(comp)
        w.textChanged.connect(lambda t: self._commit(q, t))
        return w, lambda v: self._quiet(w, lambda: w.setText("" if v is None else str(v)))

    @staticmethod
    def _quiet(w: QWidget, fn) -> None:
        w.blockSignals(True)
        try:
            fn()
        finally:
            w.blockSignals(False)

    def _spin(self, q: blocks.Param, cur):
        if q.kind == "int":
            w = QSpinBox()
            w.setRange(int(q.minimum) if q.minimum is not None else -1_000_000_000, int(q.maximum) if q.maximum is not None else 1_000_000_000)
            w.setSingleStep(max(1, int(q.step)))
        else:
            w = QDoubleSpinBox()
            w.setDecimals(2)
            w.setRange(q.minimum if q.minimum is not None else -1e12, q.maximum if q.maximum is not None else 1e12)
            w.setSingleStep(q.step or 1)
        if q.unit:
            w.setSuffix(" " + q.unit)
        w.setFocusPolicy(Qt.StrongFocus)
        w.setValue(schema.to_number(q, cur))
        w.valueChanged.connect(lambda v: self._commit(q, int(v) if q.kind == "int" else float(v)))
        return w, lambda v: self._quiet(w, lambda: w.setValue(schema.to_number(q, v)))

    def _choice(self, q: blocks.Param, cur):
        w = QComboBox()
        for value, label in schema.choice_items(q):
            w.addItem(label, value)

        def select(v):
            i = w.findData(str(v))
            if i < 0:
                w.addItem(f"⚠ {v}", str(v))
                i = w.count() - 1
            w.setCurrentIndex(i)
        select(cur)
        w.currentIndexChanged.connect(lambda _i: self._commit(q, w.currentData()))
        return w, lambda v: self._quiet(w, lambda: select(v))

    def _var(self, q: blocks.Param, cur):
        w = QComboBox()
        w.setEditable(True)
        w.addItems(schema.known_vars(self.wf, self.node["id"]))
        w.setEditText("" if cur is None else str(cur))
        w.setToolTip(self._tooltip(q) + "\nVariables connues en amont : " + (", ".join(schema.known_vars(self.wf, self.node["id"])) or "aucune") + ".")
        w.editTextChanged.connect(lambda t: self._commit(q, t))
        return w, lambda v: self._quiet(w, lambda: w.setEditText("" if v is None else str(v)))

    def _path(self, q: blocks.Param, cur):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        line = QLineEdit("" if cur is None else str(cur))
        line.setPlaceholderText(q.placeholder or ("dossier" if q.mode == "dir" else "fichier"))
        btn = QPushButton("Parcourir…")
        h.addWidget(line, 1)
        h.addWidget(btn)

        def pick():
            p = browse_path(self, q, line.text(), self.project)
            if p:
                line.setText(p)
        btn.clicked.connect(pick)
        line.textChanged.connect(lambda t: self._commit(q, t))
        box.line, box.button = line, btn
        return box, lambda v: self._quiet(line, lambda: line.setText("" if v is None else str(v)))

    def _pairs(self, q: blocks.Param, cur):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        try:
            pairs = schema.parse_pairs(cur)
        except ValueError:
            pairs = []
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Nom", "Valeur"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(110)
        table.setMaximumHeight(200)
        bar = QHBoxLayout()
        add, rm, up, down = QPushButton("Ajouter"), QPushButton("Supprimer"), QToolButton(), QToolButton()
        up.setText("▲")
        down.setText("▼")
        up.setToolTip("Monter la ligne")
        down.setToolTip("Descendre la ligne")
        for b in (add, rm, up, down):
            bar.addWidget(b)
        bar.addStretch(1)
        v.addWidget(table)
        v.addLayout(bar)

        def fill(items):
            table.blockSignals(True)
            table.setRowCount(0)
            for key, val in items:
                i = table.rowCount()
                table.insertRow(i)
                table.setItem(i, 0, QTableWidgetItem(key))
                table.setItem(i, 1, QTableWidgetItem(val))
            table.blockSignals(False)

        def read():
            return [((table.item(i, 0).text() if table.item(i, 0) else ""), (table.item(i, 1).text() if table.item(i, 1) else "")) for i in range(table.rowCount())]

        def commit():
            self._commit(q, schema.dump_pairs(read()))

        def add_row():
            i = table.rowCount()
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(""))
            table.setItem(i, 1, QTableWidgetItem(""))
            table.setCurrentCell(i, 0)
            table.editItem(table.item(i, 0))

        def remove_row():
            r = table.currentRow()
            if r < 0 and table.rowCount():
                r = table.rowCount() - 1
            if r >= 0:
                table.removeRow(r)
                commit()

        def move(delta):
            r = table.currentRow()
            items = schema.move_pair(read(), r, delta)
            fill(items)
            if 0 <= r + delta < len(items):
                table.setCurrentCell(r + delta, 0)
            commit()
        fill(pairs)
        table.itemChanged.connect(lambda _i: commit())
        add.clicked.connect(add_row)
        rm.clicked.connect(remove_row)
        up.clicked.connect(lambda: move(-1))
        down.clicked.connect(lambda: move(1))
        box.table, box.add_button, box.remove_button = table, add, rm
        box.add_pair = lambda key="", val="": (add_row_with(table, key, val), commit())
        return box, lambda val: fill(_safe_pairs(val))


def add_row_with(table: QTableWidget, key: str, val: str) -> None:
    i = table.rowCount()
    table.insertRow(i)
    table.setItem(i, 0, QTableWidgetItem(key))
    table.setItem(i, 1, QTableWidgetItem(val))


def _safe_pairs(v):
    try:
        return schema.parse_pairs(v)
    except ValueError:
        return []


def _is_number(q: blocks.Param, v) -> bool:
    try:
        schema.to_number(q, v)
        return True
    except (TypeError, ValueError):
        return False


def schema_kind(q: blocks.Param) -> str:
    return schema.KIND_LABELS.get(q.kind, q.kind)
