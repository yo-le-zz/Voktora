"""
Voktora — ui_main.repo_picker
Sélecteur de dépôts GitHub : liste les dépôts accessibles au compte connecté
(compte personnel, organisations, collaborations), filtrable par propriétaire
et par recherche. Le chargement se fait dans un thread.
"""

from __future__ import annotations

import core
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .workers import TaskWorker

ALL_OWNERS = "__all__"
_ROLE_REPO = Qt.UserRole


def load_repos_job(ctx):
    """À exécuter dans un thread : (dépôts, propriétaires) du compte connecté."""
    token = core.get_effective_token()
    if not token:
        raise core.GitHubAPIError("Aucun compte GitHub connecté. Connectez-vous depuis le menu GitHub.")
    installation = core.is_using_github_app() and core.is_github_app_configured()
    repos = core.list_user_repos(token, installation=installation, cancel=ctx.is_cancelled)
    orgs = [] if installation else core.list_user_orgs(token)
    return repos, core.owners_from_repos(repos, extra_orgs=orgs)


def filter_repos(repos: list, owner: str, needle: str) -> list:
    """Filtre pur (testable) : par propriétaire puis par texte (nom, description)."""
    needle = needle.strip().lower()
    result = []
    for repo in repos:
        if owner != ALL_OWNERS and repo.owner.lower() != owner.lower():
            continue
        if needle and needle not in repo.full_name.lower() and needle not in repo.description.lower():
            continue
        result.append(repo)
    return result


class RepoPicker(QWidget):
    repo_selected = Signal(object)    # RepoInfo ou None
    repo_activated = Signal(object)   # double-clic

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._repos: list = []
        self._worker: TaskWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.owner_combo = QComboBox()
        self.owner_combo.addItem("Tous les propriétaires", ALL_OWNERS)
        self.owner_combo.setMinimumWidth(190)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Rechercher un dépôt…")
        self.search_edit.setClearButtonEnabled(True)
        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setToolTip("Recharger la liste depuis GitHub")
        self.btn_refresh.setFixedWidth(36)
        top.addWidget(self.owner_combo)
        top.addWidget(self.search_edit, 1)
        top.addWidget(self.btn_refresh)
        layout.addLayout(top)

        self.list = QListWidget()
        self.list.setMinimumHeight(230)
        layout.addWidget(self.list, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #a6adc8; font-size: 12px;")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.owner_combo.currentIndexChanged.connect(self._render)
        self.search_edit.textChanged.connect(self._render)
        self.btn_refresh.clicked.connect(self.reload)
        self.list.currentItemChanged.connect(lambda cur, _prev: self.repo_selected.emit(
            cur.data(_ROLE_REPO) if cur else None))
        self.list.itemDoubleClicked.connect(lambda item: self.repo_activated.emit(item.data(_ROLE_REPO)))

    # ── chargement ───────────────────────────────

    def reload(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.btn_refresh.setEnabled(False)
        self.status.setText("Chargement des dépôts depuis GitHub…")
        self._worker = TaskWorker(load_repos_job)
        self._worker.succeeded.connect(self._on_loaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(lambda: self.btn_refresh.setEnabled(True))
        self._worker.start()

    def stop(self) -> None:
        """À appeler avant de détruire le widget : arrête proprement le chargement."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)

    def _on_loaded(self, result) -> None:
        self._repos, owners = result
        self.btn_refresh.setEnabled(True)
        current = self.owner_combo.currentData()
        self.owner_combo.blockSignals(True)
        self.owner_combo.clear()
        self.owner_combo.addItem(f"Tous les propriétaires ({len(self._repos)})", ALL_OWNERS)
        for owner in owners:
            icon = "🏢" if owner.owner_type == "Organization" else "👤"
            self.owner_combo.addItem(f"{icon} {owner.login} ({owner.repo_count})", owner.login)
        index = self.owner_combo.findData(current)
        self.owner_combo.setCurrentIndex(max(index, 0))
        self.owner_combo.blockSignals(False)
        self._render()

    def _on_failed(self, message: str) -> None:
        self.btn_refresh.setEnabled(True)
        self.status.setText(f"⚠  {message}")

    # ── affichage ────────────────────────────────

    def _render(self) -> None:
        shown = filter_repos(self._repos, self.owner_combo.currentData() or ALL_OWNERS,
                             self.search_edit.text())
        self.list.clear()
        for repo in shown:
            badges = ("🔒 " if repo.private else "") + ("🍴 " if repo.fork else "") + ("📦 " if repo.archived else "")
            text = f"{badges}{repo.full_name}"
            if repo.description:
                text += f"\n      {repo.description[:110]}"
            item = QListWidgetItem(text)
            item.setData(_ROLE_REPO, repo)
            self.list.addItem(item)
        if self._repos:
            self.status.setText(f"{len(shown)} dépôt(s) affiché(s) sur {len(self._repos)}.")

    def selected_repo(self):
        item = self.list.currentItem()
        return item.data(_ROLE_REPO) if item else None


class RepoChooserDialog(QDialog):
    """Petite fenêtre modale pour choisir UN dépôt parmi ceux du compte connecté."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Choisir un dépôt GitHub — Voktora")
        self.setMinimumSize(560, 420)
        self.setModal(True)
        layout = QVBoxLayout(self)
        self.picker = RepoPicker()
        layout.addWidget(self.picker)
        row = QHBoxLayout()
        btn_cancel = QPushButton("Annuler")
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("✔  Choisir")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.setEnabled(False)
        self.btn_ok.clicked.connect(self.accept)
        row.addWidget(btn_cancel)
        row.addWidget(self.btn_ok)
        layout.addLayout(row)
        self.picker.repo_selected.connect(lambda repo: self.btn_ok.setEnabled(repo is not None))
        self.picker.repo_activated.connect(lambda _repo: self.accept())
        self.picker.reload()

    def selected_repo(self):
        return self.picker.selected_repo()

    def done(self, result: int) -> None:
        self.picker.stop()
        super().done(result)
