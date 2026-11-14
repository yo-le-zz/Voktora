"""Changelog Builder — génère un bloc de changelog (Conventional Commits) entre deux références Git, et l'insère dans CHANGELOG.md.

Montre : api.run (git sans shell), dialogue Qt, project_read_text / project_write_text, logique pure testée (core.py).
"""

from PySide6.QtWidgets import (
    QCheckBox,
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


class ChangelogDialog(QDialog):
    def __init__(self, api, project, skip_chore, parent=None):
        super().__init__(parent)
        self._api, self._project = api, project
        self._shell, self._read, self._write, self._clip = api.run, api.project_read_text, api.project_write_text, api.set_clipboard_text
        self.commits: list[core.Commit] = []
        self.setWindowTitle(f"Changelog — {project.name}")
        self.resize(820, 640)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.since = QComboBox()
        self.since.setEditable(True)
        self.since.addItem("")
        for tag in self._tags():
            self.since.addItem(tag)
        if self.since.count() > 1:
            self.since.setCurrentIndex(1)
        self.until = QLineEdit("HEAD")
        self.version = QLineEdit()
        self.chore = QCheckBox("Omettre « Divers », « CI » et « Style »")
        self.chore.setChecked(skip_chore)
        form.addRow("Depuis (étiquette ou commit)", self.since)
        form.addRow("Jusqu'à", self.until)
        form.addRow("Nom de la version", self.version)
        form.addRow("", self.chore)
        root.addLayout(form)
        self.info = QLabel("")
        root.addWidget(self.info)
        self.preview = QPlainTextEdit()
        root.addWidget(self.preview, 1)
        row = QHBoxLayout()
        for label, handler in (("Générer", self.generate), ("Copier", self.copy), ("Insérer dans CHANGELOG.md", self.write)):
            b = QPushButton(label)
            b.clicked.connect(handler)
            row.addWidget(b)
        row.addStretch(1)
        root.addLayout(row)
        self.generate()

    def _git(self, *args):
        code, out = self._shell(["git", *args], cwd=self._project, timeout=30)
        return out.strip() if code == 0 else ""

    def _tags(self) -> list[str]:
        return [t for t in self._git("tag", "--sort=-creatordate").splitlines() if t.strip()][:30]

    def generate(self, *_):
        since = self.since.currentText().strip() or None
        code, out = self._shell(core.log_args(since, self.until.text().strip() or "HEAD"), cwd=self._project, timeout=60)
        if code != 0:
            self.commits = []
            self.info.setText("Git a refusé cette plage : " + out.strip()[:200])
            self.preview.setPlainText("")
            return
        self.commits = core.parse_log(out)
        if not self.version.text().strip():
            self.version.setText(core.next_version(since or "", self.commits))
        self.info.setText(f"{len(self.commits)} commit(s) analysé(s).")
        self.render()

    def render(self):
        skip = ("chore", "ci", "style") if self.chore.isChecked() else ()
        self.preview.setPlainText(core.render(self.commits, self.version.text().strip() or "Non publié", skip=skip))

    def copy(self):
        self._clip(self.preview.toPlainText())
        self._api.notify("Changelog copié")

    def write(self):
        try:
            existing = self._read(self._project, "CHANGELOG.md")
        except Exception:  # noqa: BLE001
            existing = ""
        self._write(self._project, "CHANGELOG.md", core.insert(existing, self.preview.toPlainText()))
        self._api.notify("CHANGELOG.md mis à jour")


def on_load(api):
    api.options.group("Génération")
    api.options.add_bool("skip_chore", "Omettre par défaut les commits « chore », « ci » et « style »", default=True)

    def open_dialog(*_):
        project = api.current_project()
        if project is None:
            api.notify("Ouvrez d'abord un projet")
            return
        ChangelogDialog(api, project, api.options.get("skip_chore"), api.main_window()).exec()

    api.add_menu_action("Outils", "Générer un changelog…", open_dialog, icon="mdi:format-list-bulleted-type")
    api.add_palette_command("Générer un changelog", open_dialog)
