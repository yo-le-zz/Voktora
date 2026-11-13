"""Fenêtre : sélecteurs de couleurs à gauche, aperçu en direct à droite."""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QTextEdit, QVBoxLayout)

from . import themes


def preview_qss(c: dict) -> str:
    return (f"QFrame#prev{{background:{c['base']};border:1px solid {c['primary']};border-radius:8px}}"
            f"QFrame#prev QLabel{{color:{c['text']}}}"
            f"QFrame#prev QPushButton{{background:{c['primary']};color:{c['base']};border:none;border-radius:6px;padding:6px 12px}}"
            f"QFrame#prev QLineEdit{{background:{c['base']};color:{c['text']};border:1px solid {c['blue']};padding:4px}}")


class StudioDialog(QDialog):
    def __init__(self, api, saved):
        super().__init__()
        self.api, self.saved = api, saved
        o = api.options
        start = o.get("start_from")
        self.colors = dict(themes.DEFAULT_COLORS["light" if start == "clair" else "dark"])
        if start == "dernier thème" and saved:
            self.colors = dict(list(saved.values())[-1]["colors"])
        self.setWindowTitle("Theme Studio")
        self.resize(820, 520)
        self.name = QLineEdit("Mon thème")
        form = QFormLayout()
        form.addRow("Nom", self.name)
        self.buttons = {}
        for key, label in themes.KEYS.items():
            button = QPushButton(self.colors[key])
            button.clicked.connect(lambda _=False, k=key: self.pick(k))
            self.buttons[key] = button
            form.addRow(label, button)
        left = QVBoxLayout()
        left.addLayout(form)
        for text, fn in (("Appliquer", self.apply), ("Enregistrer", self.save), ("Copier en JSON", self.copy),
                         ("Importer depuis le presse-papiers", self.paste)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            left.addWidget(b)
        self.frame = QFrame()
        self.frame.setObjectName("prev")
        inner = QVBoxLayout(self.frame)
        inner.addWidget(QLabel("Aperçu du thème"))
        inner.addWidget(QLineEdit("Champ de saisie"))
        inner.addWidget(QPushButton("Bouton principal"))
        self.sample = QTextEdit()
        self.sample.setReadOnly(True)
        inner.addWidget(self.sample)
        row = QHBoxLayout(self)
        row.addLayout(left, 1)
        row.addWidget(self.frame, 2)
        self.refresh()

    def refresh(self):
        for key, button in self.buttons.items():
            button.setText(self.colors[key])
            button.setStyleSheet(f"background:{self.colors[key]};color:{'#000' if QColor(self.colors[key]).lightness() > 128 else '#fff'}")
        if self.api.options.get("live_preview"):
            self.frame.setStyleSheet(preview_qss(self.colors))
            c = self.colors
            self.sample.setHtml("".join(f"<span style='color:{c[k]}'>■ {k}</span> " for k in ("blue", "mauve", "green", "red", "yellow")))

    def pick(self, key):
        color = QColorDialog.getColor(QColor(self.colors[key]), self, themes.KEYS[key])
        if color.isValid():
            self.colors[key] = color.name()
            self.refresh()

    def _id(self):
        return themes.slug(self.name.text())

    def save(self):
        self.saved[self._id()] = {"name": self.name.text(), "description": f"Créé avec Theme Studio",
                                  "colors": themes.clean(self.colors)}
        themes.save(self.api, self.saved)
        if self.api.options.get("auto_register"):
            self.api.register_theme(self._id(), self.name.text(), self.colors)
        self.api.notify(f"Thème « {self.name.text()} » enregistré")

    def apply(self):
        self.save()
        self.api.set_theme(f"theme-studio-{self._id()}")

    def copy(self):
        self.api.set_clipboard_text(themes.export(self.name.text(), self.colors, author=self.api.options.get("author")))
        self.api.notify("Thème copié")

    def paste(self):
        try:
            data = themes.parse_import(self.api.clipboard_text())
        except (ValueError, KeyError) as exc:
            self.api.message("Import impossible", str(exc))
            return
        self.name.setText(data["name"])
        self.colors.update(data["colors"])
        self.refresh()
