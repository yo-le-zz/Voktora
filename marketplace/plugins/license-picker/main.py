"""License Picker — choisit une licence, la complète (année, titulaire) et écrit LICENSE ; copie l'en-tête SPDX d'un fichier source.

Montre : options, dialogue Qt, project_read_text / project_write_text, open_url, logique pure testée (core.py).
"""

from datetime import date

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from . import core


class LicenseDialog(QDialog):
    def __init__(self, api, project, holder, parent=None):
        super().__init__(parent)
        self._api, self._project = api, project
        self._read, self._write, self._clip, self._open = api.project_read_text, api.project_write_text, api.set_clipboard_text, api.open_url
        self.setWindowTitle(f"Licence — {project.name}")
        self.resize(760, 640)
        try:
            self._current = core.detect(self._read(project, "LICENSE"))
        except Exception:  # noqa: BLE001
            self._current = None
        root = QVBoxLayout(self)
        self._status = QLabel(f"Licence actuelle : {core.licenses()[self._current]['name']}" if self._current else "Aucun fichier LICENSE reconnu.")
        root.addWidget(self._status)
        form = QFormLayout()
        self.combo = QComboBox()
        for key, entry in core.licenses().items():
            self.combo.addItem(entry["name"] + ("" if "text" in entry else "  (lien officiel)"), key)
        self.holder = QLineEdit(holder)
        self.holder.setPlaceholderText("Nom ou organisation titulaire du copyright")
        self.year = QLineEdit(str(date.today().year))
        self.style = QComboBox()
        self.style.addItems(list(core.COMMENT_STYLES))
        form.addRow("Licence", self.combo)
        form.addRow("Titulaire", self.holder)
        form.addRow("Année", self.year)
        form.addRow("En-tête de fichier", self.style)
        root.addLayout(form)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: gray;")
        root.addWidget(self.summary)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        root.addWidget(self.preview, 1)
        row = QHBoxLayout()
        self.write_btn = QPushButton("Écrire LICENSE")
        self.write_btn.clicked.connect(self.write)
        self.header_btn = QPushButton("Copier l'en-tête SPDX")
        self.header_btn.clicked.connect(self.copy_header)
        self.link_btn = QPushButton("Ouvrir le texte officiel")
        self.link_btn.clicked.connect(self.open_official)
        for w in (self.write_btn, self.header_btn, self.link_btn):
            row.addWidget(w)
        row.addStretch(1)
        root.addLayout(row)
        for w in (self.holder, self.year):
            w.textChanged.connect(self.refresh)
        self.combo.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def key(self) -> str:
        return self.combo.currentData()

    def refresh(self, *_):
        key = self.key()
        entry = core.licenses()[key]
        self.summary.setText(entry["summary"])
        full = core.has_text(key)
        self.write_btn.setEnabled(full)
        self.link_btn.setVisible(not full)
        self.preview.setPlainText(core.render(key, self.holder.text(), self.year.text()) if full else
                                  f"Texte officiel : {entry['url']}\n\nEn-tête conseillé pour les fichiers source :\n"
                                  + core.spdx_header(key, self.style.currentText(), self.holder.text(), self.year.text()))

    def write(self):
        text = core.render(self.key(), self.holder.text(), self.year.text())
        self._write(self._project, "LICENSE", text)
        self._api.notify("LICENSE écrit")
        self._status.setText(f"Licence actuelle : {core.licenses()[self.key()]['name']}")

    def copy_header(self):
        self._clip(core.spdx_header(self.key(), self.style.currentText(), self.holder.text(), self.year.text()))
        self._api.notify("En-tête SPDX copié")

    def open_official(self):
        self._open(core.licenses()[self.key()]["url"])


def on_load(api):
    api.options.group("Valeurs par défaut")
    api.options.add_text("holder", "Titulaire du copyright", default="", help="Pré-rempli dans le dialogue.")

    def open_dialog(*_):
        project = api.current_project()
        if project is None:
            api.notify("Ouvrez d'abord un projet")
            return
        LicenseDialog(api, project, api.options.get("holder"), api.main_window()).exec()

    api.add_menu_action("Outils", "Choisir une licence…", open_dialog, icon="mdi:scale-balance")
    api.add_palette_command("Choisir une licence", open_dialog)
