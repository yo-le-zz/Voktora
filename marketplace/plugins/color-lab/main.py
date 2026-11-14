"""Color Lab — convertit une couleur (HEX / RGB / HSL), vérifie les contrastes WCAG, propose des palettes.

Montre : dialogue Qt non lié à un projet, add_menu_action + palette, presse-papiers, logique pure testée (core.py).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from . import core


def swatch(color, size=36):
    f = QFrame()
    f.setFixedSize(size, size)
    f.setFrameShape(QFrame.StyledPanel)
    f.setStyleSheet(f"background: {core.to_hex(color)}; border-radius: 6px;")
    f.setToolTip(core.to_hex(color).upper())
    return f


class ColorDialog(QDialog):
    def __init__(self, api, parent=None):
        super().__init__(parent)
        self._api, self._clip = api, api.set_clipboard_text
        self.setWindowTitle("Color Lab")
        self.resize(560, 560)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.base = QLineEdit("#3e63dd")
        self.bg = QLineEdit("#ffffff")
        self.base.setPlaceholderText("#3e63dd, rgb(62, 99, 221), hsl(228, 70%, 54%)")
        form.addRow("Couleur", self.base)
        form.addRow("Fond (pour le contraste)", self.bg)
        root.addLayout(form)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #e5484d;")
        root.addWidget(self.error)
        self.fmt_box = QVBoxLayout()
        root.addLayout(self.fmt_box)
        self.preview = QLabel("Exemple de texte lisible ?")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(54)
        root.addWidget(self.preview)
        self.report = QLabel()
        self.report.setWordWrap(True)
        root.addWidget(self.report)
        self.fix_btn = QPushButton("Corriger la couleur pour atteindre AA (4,5:1)")
        self.fix_btn.clicked.connect(self.fix)
        root.addWidget(self.fix_btn)
        self.pal_box = QGridLayout()
        root.addLayout(self.pal_box)
        root.addStretch(1)
        self.base.textChanged.connect(self.refresh)
        self.bg.textChanged.connect(self.refresh)
        self.refresh()

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def colors(self):
        return core.parse(self.base.text()), core.parse(self.bg.text())

    def refresh(self, *_):
        try:
            c, bg = self.colors()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.error.setText("")
        self._clear(self.fmt_box)
        for name, value in core.formats(c).items():
            row = QHBoxLayout()
            label = QLabel(f"{name}  {value}")
            btn = QPushButton("Copier")
            btn.clicked.connect(lambda _=False, v=value: self.copy(v))
            row.addWidget(label, 1)
            row.addWidget(btn)
            wrapper = QWidgetRow(row)
            self.fmt_box.addWidget(wrapper)
        ratio = core.contrast(c, bg)
        self.preview.setStyleSheet(f"background: {core.to_hex(bg)}; color: {core.to_hex(c)}; font-size: 16px; border-radius: 6px;")
        marks = "  ·  ".join(f"{k} {'✓' if ok else '✗'}" for k, ok in core.verdict(ratio).items())
        self.report.setText(f"Contraste : <b>{ratio:.2f}:1</b><br>{marks}")
        self.fix_btn.setEnabled(ratio < 4.5)
        self._clear(self.pal_box)
        for r, (name, colors) in enumerate(core.palettes(c).items()):
            self.pal_box.addWidget(QLabel(name), r, 0)
            for i, col in enumerate(colors):
                self.pal_box.addWidget(swatch(col), r, i + 1)

    def copy(self, text):
        self._clip(text)
        self._api.notify(f"{text} copié")

    def fix(self):
        c, bg = self.colors()
        self.base.setText(core.to_hex(core.fix_contrast(c, bg)))


def QWidgetRow(layout):  # noqa: N802 — petite fabrique : un QWidget qui porte une ligne
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    w.setLayout(layout)
    return w


def on_load(api):
    def open_dialog(*_):
        ColorDialog(api, api.main_window()).exec()

    api.add_menu_action("Outils", "Color Lab…", open_dialog, icon="mdi:palette-swatch-outline")
    api.add_palette_command("Color Lab (couleurs et contrastes)", open_dialog)
