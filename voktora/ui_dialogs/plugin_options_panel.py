"""
Voktora — ui_dialogs.plugin_options_panel (1.1.1)
Panneau de réglages construit AUTOMATIQUEMENT à partir des options déclarées par un plugin (`api.options`).
Le plugin n'écrit aucun code d'interface : Voktora s'en charge, avec le même rendu pour tous.
"""

from __future__ import annotations

from collections import OrderedDict

from plugins.options import Option, PluginOptions
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class _ColorButton(QPushButton):
    def __init__(self, value: str, on_change):
        super().__init__()
        self._value, self._on_change = value, on_change
        self.setFixedWidth(110)
        self.clicked.connect(self._pick)
        self._paint()

    def _paint(self) -> None:
        color = QColor(self._value)
        text = "#000" if color.lightness() > 140 else "#fff"
        self.setText(self._value)
        self.setStyleSheet(f"background:{self._value};color:{text};border-radius:6px;padding:4px;")

    def _pick(self) -> None:
        color = QColorDialog.getColor(QColor(self._value), self, "Couleur")
        if color.isValid():
            self._value = color.name()
            self._paint()
            self._on_change(self._value)


class PluginOptionsPanel(QWidget):
    """Formulaire des options d'un plugin ; chaque modification est enregistrée aussitôt."""

    def __init__(self, options: PluginOptions, parent=None):
        super().__init__(parent)
        self._options = options
        self._rows: dict[str, tuple[QWidget, QWidget]] = {}          # clé → (étiquette, widget)
        self._building = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._form_root = QVBoxLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        self._build()
        self._form_root.addStretch(1)
        bottom = QHBoxLayout()
        reset = QPushButton("Valeurs par défaut")
        reset.clicked.connect(self._reset)
        bottom.addStretch(1)
        bottom.addWidget(reset)
        outer.addLayout(bottom)
        self._refresh_visibility()

    def _build(self) -> None:
        groups: OrderedDict[str, QFormLayout] = OrderedDict()

        def form_for(name: str) -> QFormLayout:
            if name not in groups:
                box = QGroupBox(name or "Général")
                layout = QFormLayout(box)
                layout.setLabelAlignment(Qt.AlignLeft)
                self._form_root.addWidget(box)
                groups[name] = layout
            return groups[name]

        self._building = True
        for option in self._options.schema():
            widget = self._make(option)
            label = QLabel(option.label)
            if option.help:
                label.setToolTip(option.help)
                widget.setToolTip(option.help)
            form_for(option.group).addRow(label, widget)
            self._rows[option.key] = (label, widget)
        for button in self._options.buttons:
            b = QPushButton(button.label)
            b.setToolTip(button.help)
            b.clicked.connect(lambda _=False, h=button.handler: self._call(h))
            form_for(button.group).addRow("", b)
        self._building = False

    def _call(self, handler) -> None:
        try:
            handler()
        except Exception as exc:  # noqa: BLE001
            self._options._on_error(f"bouton : {exc}")

    def _changed(self, key: str, value) -> None:
        if self._building:
            return
        try:
            self._options.set(key, value)
        except ValueError as exc:
            self._options._on_error(str(exc))
        self._refresh_visibility()

    def _make(self, o: Option) -> QWidget:
        value = self._options.get(o.key)
        key = o.key
        if o.type == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(lambda v, k=key: self._changed(k, v))
        elif o.type == "int":
            w = QSpinBox()
            w.setRange(int(o.min) if o.min is not None else -2_000_000_000, int(o.max) if o.max is not None else 2_000_000_000)
            w.setSingleStep(int(o.step or 1))
            w.setValue(int(value))
            w.valueChanged.connect(lambda v, k=key: self._changed(k, v))
        elif o.type == "float":
            w = QDoubleSpinBox()
            w.setDecimals(3)
            w.setRange(o.min if o.min is not None else -1e9, o.max if o.max is not None else 1e9)
            w.setSingleStep(o.step or 0.1)
            w.setValue(float(value))
            w.valueChanged.connect(lambda v, k=key: self._changed(k, v))
        elif o.type == "choice":
            w = QComboBox()
            w.addItems(o.choices)
            w.setCurrentText(str(value))
            w.currentTextChanged.connect(lambda v, k=key: self._changed(k, v))
        elif o.type == "color":
            w = _ColorButton(str(value), lambda v, k=key: self._changed(k, v))
        elif o.type == "multiline":
            w = QPlainTextEdit(str(value))
            w.setFixedHeight(90)
            w.textChanged.connect(lambda k=key, e=w: self._changed(k, e.toPlainText()))
        elif o.type == "shortcut":
            w = QKeySequenceEdit(QKeySequence(str(value)))
            w.keySequenceChanged.connect(lambda seq, k=key: self._changed(k, seq.toString()))
        elif o.type == "path":
            w = self._path_row(o, str(value))
        else:
            w = QLineEdit(str(value))
            w.textChanged.connect(lambda v, k=key: self._changed(k, v))
        return w

    def _path_row(self, o: Option, value: str) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(value)
        edit.textChanged.connect(lambda v, k=o.key: self._changed(k, v))
        browse = QPushButton("…")
        browse.setFixedWidth(34)

        def pick() -> None:
            if o.path_kind == "dir":
                chosen = QFileDialog.getExistingDirectory(self, o.label, edit.text())
            elif o.path_kind == "save":
                chosen = QFileDialog.getSaveFileName(self, o.label, edit.text())[0]
            else:
                chosen = QFileDialog.getOpenFileName(self, o.label, edit.text())[0]
            if chosen:
                edit.setText(chosen)

        browse.clicked.connect(pick)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        box._edit = edit                                   # type: ignore[attr-defined]
        return box

    def _refresh_visibility(self) -> None:
        for option in self._options.schema():
            label, widget = self._rows[option.key]
            visible = self._options.is_visible(option)
            label.setVisible(visible)
            widget.setVisible(visible)

    def _reset(self) -> None:
        self._options.reset()
        while self._form_root.count():
            item = self._form_root.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()
        self._build()
        self._form_root.addStretch(1)
        self._refresh_visibility()
