"""
Voktora — ui_main.clone_dialog
Cloner un dépôt GitHub comme nouveau projet : depuis la liste de ses dépôts
(filtrée par organisation) ou en collant une URL.
"""

from __future__ import annotations

import core
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import task_dialog, workers
from .repo_picker import RepoPicker


class CloneDialog(QDialog):
    def __init__(self, drive: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._drive = drive
        self.cloned_path = None
        self.setWindowTitle("Cloner depuis GitHub — Voktora")
        self.setMinimumSize(640, 560)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)

        title = QLabel("📥  Cloner un dépôt GitHub")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.picker = RepoPicker()
        self.tabs.addTab(self.picker, "🐙  Mes dépôts")
        url_tab = QWidget()
        url_layout = QVBoxLayout(url_tab)
        url_layout.addWidget(QLabel("URL du dépôt :"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://github.com/organisation/depot.git")
        url_layout.addWidget(self.url_edit)
        url_layout.addStretch()
        self.tabs.addTab(url_tab, "🔗  Par URL")
        layout.addWidget(self.tabs, 1)

        layout.addWidget(workers._make_sep())
        form = QHBoxLayout()
        col_name = QVBoxLayout()
        col_name.addWidget(QLabel("Nom du projet :"))
        self.name_edit = QLineEdit()
        col_name.addWidget(self.name_edit)
        col_branch = QVBoxLayout()
        col_branch.addWidget(QLabel("Branche (facultatif) :"))
        self.branch_edit = QLineEdit()
        self.branch_edit.setPlaceholderText("défaut")
        col_branch.addWidget(self.branch_edit)
        col_cat = QVBoxLayout()
        col_cat.addWidget(QLabel("Catégorie :"))
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItem("")
        self.category_combo.addItem("🐙 Selon l'organisation GitHub", "__owner__")
        for cat in core.list_categories():
            self.category_combo.addItem(cat["name"], cat["name"])
        self.category_combo.lineEdit().setPlaceholderText("Aucune")
        col_cat.addWidget(self.category_combo)
        form.addLayout(col_name, 2)
        form.addLayout(col_branch, 2)
        form.addLayout(col_cat, 2)
        layout.addLayout(form)

        self.preview = QLabel("")
        self.preview.setObjectName("pathLabel")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        self.btn_clone = QPushButton("📥  Cloner")
        self.btn_clone.setObjectName("primary")
        self.btn_clone.clicked.connect(self._start_clone)
        btns.addWidget(btn_cancel)
        btns.addWidget(self.btn_clone)
        layout.addLayout(btns)

        self.picker.repo_selected.connect(self._on_repo_selected)
        self.picker.repo_activated.connect(lambda _repo: self._start_clone())
        self.url_edit.textChanged.connect(self._on_url_changed)
        self.name_edit.textChanged.connect(self._refresh_preview)

        # Pas de compte connecté → l'onglet URL est le plus utile (dépôts publics).
        if core.get_github_session():
            self.picker.reload()
        else:
            self.tabs.setCurrentIndex(1)
            self.picker.status.setText("Connectez-vous à GitHub pour lister vos dépôts et ceux de vos organisations.")

    # ── état ─────────────────────────────────────

    def _current_url(self) -> str:
        if self.tabs.currentIndex() == 0:
            repo = self.picker.selected_repo()
            return repo.clone_url if repo else ""
        return self.url_edit.text().strip()

    def _on_repo_selected(self, repo) -> None:
        if repo is not None:
            self.name_edit.setText(repo.name)
            self.branch_edit.setPlaceholderText(f"{repo.default_branch} (défaut)")

    def _on_url_changed(self, text: str) -> None:
        self.name_edit.setText(core.repo_name_from_url(text) if text.strip() else "")

    def _refresh_preview(self) -> None:
        name = self.name_edit.text().strip()
        if name:
            self.preview.setText(f"Emplacement : {core.get_projects_root(self._drive) / name}")
        else:
            self.preview.setText("")

    def _category(self, url: str) -> str | None:
        data = self.category_combo.currentData()
        if data == "__owner__":
            return core.github_owner(url)
        return self.category_combo.currentText().strip() or None

    # ── clone ────────────────────────────────────

    def _start_clone(self) -> None:
        url = self._current_url()
        name = self.name_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "Voktora", "Choisissez un dépôt dans la liste ou saisissez une URL.")
            return
        try:
            core.validate_clone_url(url)
            core.validate_name(name)
        except ValueError as exc:
            QMessageBox.warning(self, "Voktora", str(exc))
            return

        branch, drive, category = self.branch_edit.text().strip(), self._drive, self._category(url)

        def job(ctx):
            return core.clone_project(url, drive, name=name, branch=branch, category=category,
                                      on_output=ctx.log, cancel=ctx.is_cancelled)

        done = task_dialog.run_task(self, "Clonage du dépôt", job, show_log=True,
                                    headline=f"Clonage de {name}")
        if done.outcome == task_dialog.OUTCOME_OK:
            self.cloned_path = done.result
            self.accept()
        elif done.outcome == task_dialog.OUTCOME_ERROR:
            QMessageBox.critical(self, "Voktora — Clonage impossible", done.error)

    def done(self, result: int) -> None:
        self.picker.stop()
        super().done(result)
