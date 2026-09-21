"""
Voktora — ui_main.github_dialog
Compte GitHub et organisations : vue d'ensemble des propriétaires (compte
personnel, organisations) de vos dépôts et de vos projets Voktora, avec
classement automatique des projets par organisation.
"""

from __future__ import annotations

import webbrowser

import core
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import workers
from .repo_picker import load_repos_job
from .workers import TaskWorker


def local_owner_counts() -> dict[str, int]:
    """Nombre de projets Voktora par propriétaire GitHub (d'après l'URL du dépôt)."""
    counts: dict[str, int] = {}
    for entry in core.list_projects():
        owner = core.github_owner(entry.get("github_repo"))
        if owner:
            counts[owner] = counts.get(owner, 0) + 1
    return counts


class GitHubDialog(QDialog):
    projects_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("🐙  Compte & organisations GitHub — Voktora")
        self.setMinimumSize(620, 520)
        self.setModal(True)
        self._remote_owners: list = []
        self._worker: TaskWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)

        title = QLabel("🐙  Compte & organisations")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.account_label = QLabel("")
        self.account_label.setWordWrap(True)
        layout.addWidget(self.account_label)
        layout.addWidget(workers._make_sep())

        hint = QLabel(
            "Chaque projet lié à un dépôt GitHub est rattaché à son propriétaire (compte ou "
            "organisation). Chargez vos dépôts pour voir toutes vos organisations, puis "
            "classez vos projets d'un clic : une catégorie est créée par organisation."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Propriétaire", "Type", "Dépôts GitHub", "Projets Voktora"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #a6adc8; font-size: 12px;")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        row = QHBoxLayout()
        self.btn_load = QPushButton("⟳  Charger depuis GitHub")
        self.btn_load.clicked.connect(self._load_remote)
        self.btn_open = QPushButton("🌐  Ouvrir sur GitHub")
        self.btn_open.clicked.connect(self._open_selected)
        row.addWidget(self.btn_load)
        row.addWidget(self.btn_open)
        row.addStretch()
        layout.addLayout(row)

        self.chk_reclassify = QCheckBox("Reclasser aussi les projets déjà rangés dans une catégorie")
        layout.addWidget(self.chk_reclassify)
        self.btn_classify = QPushButton("🗂  Classer mes projets par organisation")
        self.btn_classify.setObjectName("primary")
        self.btn_classify.clicked.connect(self._classify)
        layout.addWidget(self.btn_classify)

        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

        self._refresh_account()
        self._render()

    # ── affichage ────────────────────────────────

    def _refresh_account(self) -> None:
        info = core.get_github_account_info()
        if info["connected"]:
            method = "GitHub App" if core.is_using_github_app() else "OAuth"
            who = f"{info['name']} (@{info['login']})" if info["name"] else f"@{info['login']}"
            self.account_label.setText(f"✅  Connecté : <b>{who}</b> — méthode : {method}")
        else:
            self.account_label.setText("⚪  Aucun compte connecté. Les propriétaires ci-dessous "
                                       "viennent uniquement de vos projets locaux.")
        self.account_label.setTextFormat(Qt.RichText)

    def _render(self) -> None:
        local = local_owner_counts()
        rows: dict[str, list] = {}
        for owner in self._remote_owners:
            rows[owner.login.lower()] = [owner.login, owner.owner_type, owner.repo_count, 0]
        for login, count in local.items():
            slot = rows.setdefault(login.lower(), [login, "—", 0, 0])
            slot[3] = count
        ordered = sorted(rows.values(), key=lambda r: r[0].lower())
        self.table.setRowCount(len(ordered))
        for i, (login, otype, repos, projects) in enumerate(ordered):
            label = {"Organization": "🏢 Organisation", "User": "👤 Compte"}.get(otype, otype)
            cells = [login, label, str(repos) if self._remote_owners else "—", str(projects)]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col >= 2:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, col, item)
        self.btn_open.setEnabled(bool(ordered))

    # ── actions ──────────────────────────────────

    def _load_remote(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.btn_load.setEnabled(False)
        self.status.setText("Chargement depuis GitHub…")
        self._worker = TaskWorker(load_repos_job)
        self._worker.succeeded.connect(self._on_loaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(lambda: self.btn_load.setEnabled(True))
        self._worker.start()

    def _on_loaded(self, result) -> None:
        repos, owners = result
        self._remote_owners = owners
        self.btn_load.setEnabled(True)
        self.status.setText(f"{len(repos)} dépôt(s) accessible(s) chez {len(owners)} propriétaire(s).")
        self._render()

    def _on_failed(self, message: str) -> None:
        self.btn_load.setEnabled(True)
        self.status.setText(f"⚠  {message}")

    def _open_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Voktora", "Sélectionnez d'abord un propriétaire dans la liste.")
            return
        login = self.table.item(row, 0).text()
        webbrowser.open(f"https://github.com/{login}")

    def _classify(self) -> None:
        assigned = core.categorize_by_github_owner(only_uncategorized=not self.chk_reclassify.isChecked())
        if not assigned:
            QMessageBox.information(
                self, "Voktora",
                "Aucun projet à classer : soit aucun n'est lié à un dépôt GitHub, soit ils ont déjà "
                "une catégorie (cochez « Reclasser aussi… » pour les reclasser).")
            return
        total = sum(assigned.values())
        detail = "\n".join(f"• {owner} : {n}" for owner, n in sorted(assigned.items()))
        QMessageBox.information(self, "Voktora", f"{total} projet(s) classé(s) :\n{detail}")
        self.projects_changed.emit()
        self._render()

    def done(self, result: int) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        super().done(result)
