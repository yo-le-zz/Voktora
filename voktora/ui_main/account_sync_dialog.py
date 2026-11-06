"""
Voktora — ui_main.account_sync_dialog
« Ajouter les dépôts de mon compte » : liste les dépôts du compte GitHub connecté (et de ses
organisations), coche ceux qui ne sont pas encore dans Voktora, puis les clone tous automatiquement
(en parallèle, avec une barre de progression globale) et les enregistre comme projets.
"""

from __future__ import annotations

import core
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from task_worker import TaskWorker

from . import task_dialog
from .repo_picker import ALL_OWNERS, filter_repos, load_repos_job

_ROLE_REPO = Qt.UserRole


def summarize(outcomes: list) -> str:
    """Texte récapitulatif d'un clonage en lot (pur, testable)."""
    cloned = [o for o in outcomes if o.status == core.CLONE_CLONED]
    skipped = [o for o in outcomes if o.status == core.CLONE_SKIPPED]
    failed = [o for o in outcomes if o.status == core.CLONE_FAILED]
    lines = [f"{len(cloned)} dépôt(s) cloné(s) et ajouté(s)."]
    if skipped:
        lines.append(f"{len(skipped)} ignoré(s) : " + ", ".join(f"{o.repo} ({o.message})" for o in skipped[:8])
                     + (" …" if len(skipped) > 8 else ""))
    if failed:
        lines.append(f"{len(failed)} en échec :")
        lines += [f"  • {o.repo} — {o.message.splitlines()[-1] if o.message else 'erreur inconnue'}" for o in failed[:10]]
    return "\n".join(lines)


class AccountSyncDialog(QDialog):
    def __init__(self, drive: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._drive = drive
        self._repos: list = []
        self._present: set[str] = set()
        self._worker: TaskWorker | None = None
        self.outcomes: list = []
        self.setWindowTitle("Ajouter les dépôts de mon compte — Voktora")
        self.setMinimumSize(680, 600)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(8)
        title = QLabel("📥  Cloner les dépôts de mon compte GitHub")
        title.setObjectName("appTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "Les dépôts cochés sont clonés dans le dossier des projets puis ajoutés à Voktora. "
            "Ceux déjà présents sont ignorés."))

        top = QHBoxLayout()
        self.owner_combo = QComboBox()
        self.owner_combo.addItem("Tous les propriétaires", ALL_OWNERS)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Rechercher un dépôt…")
        self.search_edit.setClearButtonEnabled(True)
        self.btn_reload = QPushButton("Recharger")
        top.addWidget(self.owner_combo)
        top.addWidget(self.search_edit, 1)
        top.addWidget(self.btn_reload)
        layout.addLayout(top)

        opts = QHBoxLayout()
        self.chk_forks = QCheckBox("Inclure les forks")
        self.chk_archived = QCheckBox("Inclure les archivés")
        self.chk_hide_present = QCheckBox("Masquer ceux déjà dans Voktora")
        self.chk_hide_present.setChecked(True)
        for chk in (self.chk_forks, self.chk_archived, self.chk_hide_present):
            opts.addWidget(chk)
            chk.toggled.connect(self._render)
        opts.addStretch()
        layout.addLayout(opts)

        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        layout.addWidget(self.list, 1)

        sel = QHBoxLayout()
        btn_all = QPushButton("Tout cocher")
        btn_none = QPushButton("Tout décocher")
        btn_all.clicked.connect(lambda: self._set_all(Qt.Checked))
        btn_none.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        self.count_lbl = QLabel("")
        sel.addWidget(btn_all)
        sel.addWidget(btn_none)
        sel.addStretch()
        sel.addWidget(self.count_lbl)
        layout.addLayout(sel)

        form = QHBoxLayout()
        form.addWidget(QLabel("Catégorie :"))
        self.category_combo = QComboBox()
        self.category_combo.addItem("Selon le propriétaire GitHub", "__owner__")
        self.category_combo.addItem("Aucune", None)
        for cat in core.list_categories():
            self.category_combo.addItem(cat["name"], cat["name"])
        form.addWidget(self.category_combo, 1)
        form.addWidget(QLabel("Clones simultanés :"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 8)
        self.workers_spin.setValue(3)
        form.addWidget(self.workers_spin)
        layout.addLayout(form)

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedHeight(6)
        self.busy.hide()
        layout.addWidget(self.busy)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self.status)

        btns = QHBoxLayout()
        btn_cancel = QPushButton("Fermer")
        btn_cancel.clicked.connect(self.reject)
        self.btn_start = QPushButton("📥  Cloner la sélection")
        self.btn_start.setObjectName("primary")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._start)
        btns.addWidget(btn_cancel)
        btns.addStretch()
        btns.addWidget(self.btn_start)
        layout.addLayout(btns)

        self.owner_combo.currentIndexChanged.connect(self._render)
        self.search_edit.textChanged.connect(self._render)
        self.btn_reload.clicked.connect(self.reload)
        self.list.itemChanged.connect(self._update_count)

        if core.get_github_session():
            self.reload()
        else:
            self.status.setText("Connectez-vous à GitHub (menu GitHub) pour lister vos dépôts.")
            self.btn_reload.setEnabled(False)

    # ── chargement ───────────────────────────────

    def reload(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.btn_reload.setEnabled(False)
        self.busy.show()
        self.status.setText("Chargement des dépôts depuis GitHub…")
        self._worker = TaskWorker(load_repos_job)
        self._worker.succeeded.connect(self._on_loaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(lambda: (self.btn_reload.setEnabled(True), self.busy.hide()))
        self._worker.start()

    def _on_loaded(self, result) -> None:
        self._repos, owners = result
        self.btn_reload.setEnabled(True)
        self.busy.hide()
        _to_clone, skipped = core.plan_clone_many(self._repos, self._drive)
        self._present = {o.repo for o in skipped if "déjà" in o.message}
        self.owner_combo.blockSignals(True)
        self.owner_combo.clear()
        self.owner_combo.addItem(f"Tous les propriétaires ({len(self._repos)})", ALL_OWNERS)
        for owner in owners:
            self.owner_combo.addItem(f"{owner.login} ({owner.repo_count})", owner.login)
        self.owner_combo.blockSignals(False)
        self._render()

    def _on_failed(self, message: str) -> None:
        self.btn_reload.setEnabled(True)
        self.busy.hide()
        self.status.setText(f"⚠  {message}")

    # ── affichage ────────────────────────────────

    def _visible(self) -> list:
        repos = filter_repos(self._repos, self.owner_combo.currentData() or ALL_OWNERS, self.search_edit.text())
        return [r for r in repos
                if (self.chk_forks.isChecked() or not r.fork)
                and (self.chk_archived.isChecked() or not r.archived)
                and not (self.chk_hide_present.isChecked() and r.full_name in self._present)]

    def _render(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for repo in self._visible():
            flags = [t for t, on in (("privé", repo.private), ("fork", repo.fork), ("archivé", repo.archived),
                                     ("déjà ajouté", repo.full_name in self._present)) if on]
            text = repo.full_name + (f"   [{', '.join(flags)}]" if flags else "")
            item = QListWidgetItem(text)
            item.setData(_ROLE_REPO, repo)
            present = repo.full_name in self._present
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if present else Qt.Checked)
            if present:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            if repo.description:
                item.setToolTip(repo.description)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self._repos:
            self.status.setText(f"{len(self._repos)} dépôt(s) sur le compte, {len(self._present)} déjà dans Voktora.")
        self._update_count()

    def _checked(self) -> list:
        return [self.list.item(i).data(_ROLE_REPO) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked and self.list.item(i).flags() & Qt.ItemIsEnabled]

    def _set_all(self, state) -> None:
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.flags() & Qt.ItemIsEnabled:
                item.setCheckState(state)
        self.list.blockSignals(False)
        self._update_count()

    def _update_count(self, *_args) -> None:
        n = len(self._checked())
        self.count_lbl.setText(f"{n} sélectionné(s)")
        self.btn_start.setEnabled(n > 0)

    # ── clonage ──────────────────────────────────

    def _start(self) -> None:
        repos = self._checked()
        if not repos:
            return
        category, drive, workers = self.category_combo.currentData(), self._drive, self.workers_spin.value()

        def job(ctx):
            return core.clone_many(repos, drive, category=category, workers=workers,
                                   on_progress=ctx.progress, on_output=ctx.log, cancel=ctx.is_cancelled)

        done = task_dialog.run_task(self, "Clonage des dépôts du compte", job, show_log=True,
                                    headline=f"Clonage de {len(repos)} dépôt(s)", unit="items")
        if done.outcome == task_dialog.OUTCOME_OK:
            self.outcomes = done.result
            QMessageBox.information(self, "Voktora — Dépôts ajoutés", summarize(self.outcomes))
            self.accept()
        elif done.outcome == task_dialog.OUTCOME_CANCELLED:
            QMessageBox.information(self, "Voktora", "Clonage annulé. Les dépôts déjà terminés ont été ajoutés.")
            self.accept()
        else:
            QMessageBox.critical(self, "Voktora — Clonage impossible", done.error)

    def done(self, result: int) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        super().done(result)
