"""
Voktora — ui_dialogs.forges_dialog
Hub des forges : GitHub (compte principal), GitLab, Fedora Forge / Forgejo / Codeberg… au même endroit —
comptes, test de connexion, liste des dépôts de tous les comptes avec la distinction des forks.
"""

from __future__ import annotations

import threading

import forges
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class _Worker(QObject):
    done = Signal(object, str)          # résultat, erreur


class ForgesDialog(QDialog):
    """`actions` : dict de callbacks fournis par la fenêtre principale (github_login, github_hub, clone…)."""

    def __init__(self, parent=None, actions: dict | None = None):
        super().__init__(parent)
        self.actions = actions or {}
        self.setWindowTitle("Forges — GitHub, GitLab, Fedora…")
        self.setMinimumSize(680, 540)
        tabs = QTabWidget()
        tabs.addTab(self._build_accounts(), "🔑 Comptes")
        tabs.addTab(self._build_repos(), "📚 Dépôts")
        root = QVBoxLayout(self)
        root.addWidget(tabs)
        self._worker = _Worker()
        self._worker.done.connect(self._on_done)
        self._refresh_accounts()

    # ── comptes ──────────────────────────────────────────────────────────────

    def _build_accounts(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        gh = QHBoxLayout()
        self.gh_label = QLabel("")
        gh.addWidget(self.gh_label, 1)
        for text, key in (("Connexion GitHub…", "github_login"), ("Renommer GitHub…", "github_rename"),
                          ("Compte & organisations…", "github_hub"),
                          ("Cloner un dépôt…", "clone"), ("Ajouter mes dépôts…", "sync_account")):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, k=key: self._action(k))
            gh.addWidget(btn)
        lay.addLayout(gh)
        self.accounts = QListWidget()
        lay.addWidget(self.accounts)
        row = QHBoxLayout()
        rm = QPushButton("Retirer le compte sélectionné")
        rm.clicked.connect(self._remove)
        test = QPushButton("Tester")
        test.clicked.connect(self._test)
        ren = QPushButton("Renommer")
        ren.clicked.connect(self._rename)
        row.addWidget(test)
        row.addWidget(ren)
        row.addWidget(rm)
        row.addStretch()
        lay.addLayout(row)
        form = QFormLayout()
        self.preset = QComboBox()
        for name, kind, host in forges.PRESETS:
            if kind != "github":
                self.preset.addItem(f"{name} — {host}", (name, kind, host))
        self.preset.addItem("Autre forge (GitLab, Forgejo, Gitea…)", ("", "", ""))
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.kind = QComboBox()
        for key, label in forges.KINDS.items():
            self.kind.addItem(label, key)
        self.host = QLineEdit()
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("Jeton personnel (droit de lecture des dépôts)")
        form.addRow("Forge", self.preset)
        form.addRow("Type", self.kind)
        form.addRow("Adresse", self.host)
        form.addRow("Jeton", self.token)
        lay.addLayout(form)
        add = QPushButton("➕ Ajouter et vérifier le compte")
        add.clicked.connect(self._add)
        lay.addWidget(add)
        note = QLabel("Les jetons vont dans le coffre (Vault) s'il est déverrouillé. Ils ne sont jamais écrits dans "
                      "un remote git ni synchronisés entre PC.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#7f849c;")
        lay.addWidget(note)
        self._preset_changed()
        return page

    def _preset_changed(self) -> None:
        name, kind, host = self.preset.currentData() or ("", "", "")
        self.host.setText(host)
        self.host.setReadOnly(bool(host))
        idx = self.kind.findData(kind)
        if idx >= 0:
            self.kind.setCurrentIndex(idx)
        self.kind.setEnabled(not kind)

    def _action(self, key: str) -> None:
        fn = self.actions.get(key)
        if fn:
            fn()
            self._refresh_accounts()

    def _refresh_accounts(self) -> None:
        import core
        session = core.get_github_session()
        self.gh_label.setText(f"🐙 GitHub : {'✅ @' + session.get('login', '') if session else 'non connecté'}")
        self.accounts.clear()
        for acc in forges.list_accounts():
            item = QListWidgetItem(f"{forges.KINDS.get(acc['kind'], acc['kind'])} · {acc['label']} — @{acc['login']}  "
                                   f"({acc['host']})")
            item.setData(Qt.UserRole, acc["id"])
            self.accounts.addItem(item)

    def _run(self, fn) -> None:
        def work() -> None:
            try:
                self._worker.done.emit(fn(), "")
            except forges.ForgeError as exc:
                self._worker.done.emit(None, str(exc))
            except Exception as exc:  # noqa: BLE001
                self._worker.done.emit(None, f"{type(exc).__name__}: {exc}")
        threading.Thread(target=work, daemon=True, name="voktora-forges").start()

    def _on_done(self, result, error: str) -> None:
        QGuiApplication.restoreOverrideCursor()
        if error:
            QMessageBox.warning(self, "Forge", error)
            return
        if isinstance(result, dict) and "login" in result:
            QMessageBox.information(self, "Forge", f"Connecté en tant que @{result['login']}.")
            self.token.clear()
            self._refresh_accounts()
        elif isinstance(result, list):
            self._fill_repos(result)

    def _add(self) -> None:
        kind, host, token = self.kind.currentData(), self.host.text(), self.token.text()
        label = (self.preset.currentData() or ("", "", ""))[0]
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        self._run(lambda: forges.add_account(kind, host, token, label))

    def _selected(self) -> str:
        item = self.accounts.currentItem()
        return item.data(Qt.UserRole) if item else ""

    def _test(self) -> None:
        acc = self._selected()
        if acc:
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            self._run(lambda: forges.client_for(acc).user())

    def _rename(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        acc = self._selected()
        if not acc:
            return
        current = next((a["label"] for a in forges.list_accounts() if a["id"] == acc), "")
        text, ok = QInputDialog.getText(self, "Renommer le compte", "Nom affiché :", text=current)
        if ok:
            forges.rename_account(acc, text)
            self._refresh_accounts()

    def _remove(self) -> None:
        acc = self._selected()
        if acc and QMessageBox.question(self, "Retirer", "Retirer ce compte de Voktora ?") == QMessageBox.Yes:
            forges.remove_account(acc)
            self._refresh_accounts()

    # ── dépôts ───────────────────────────────────────────────────────────────

    def _build_repos(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        top = QHBoxLayout()
        load = QPushButton("🔄 Charger les dépôts de tous mes comptes")
        load.clicked.connect(self._load_repos)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer…")
        self.filter.textChanged.connect(self._apply_filter)
        self.only_forks = QPushButton("🍴 Forks seulement")
        self.only_forks.setCheckable(True)
        self.only_forks.toggled.connect(self._apply_filter)
        top.addWidget(load)
        top.addWidget(self.filter, 1)
        top.addWidget(self.only_forks)
        lay.addLayout(top)
        self.repos = QListWidget()
        self.repos.itemDoubleClicked.connect(self._copy_clone)
        lay.addWidget(self.repos)
        hint = QLabel("Double-clic : copier l'adresse de clone (à coller dans « Cloner un dépôt »).")
        hint.setStyleSheet("color:#7f849c;")
        lay.addWidget(hint)
        self._all: list[tuple[str, forges.Repo]] = []
        return page

    def _load_repos(self) -> None:
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        self._run(forges.all_repos)

    def _fill_repos(self, pairs) -> None:
        self._all = pairs
        self._apply_filter()

    def _apply_filter(self) -> None:
        text, forks = self.filter.text().lower(), self.only_forks.isChecked()
        self.repos.clear()
        for owner, repo in self._all:
            if not repo.full_name:
                self.repos.addItem(owner)
                continue
            if (forks and not repo.fork) or (text and text not in repo.full_name.lower()):
                continue
            line = f"{'🍴 ' if repo.fork else ''}{repo.full_name}  — {owner}"
            if repo.fork and repo.parent:
                line += f"  (fork de {repo.parent})"
            if repo.private:
                line += "  🔒"
            item = QListWidgetItem(line)
            item.setData(Qt.UserRole, repo.clone_url)
            self.repos.addItem(item)

    def _copy_clone(self, item: QListWidgetItem) -> None:
        url = item.data(Qt.UserRole)
        if url:
            QGuiApplication.clipboard().setText(url)
