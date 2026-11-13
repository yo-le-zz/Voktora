"""Interface du DevOps Center : environnements, Git, Docker, serveurs, déploiements, pipelines, historique."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..core import deploy as deploy_mod
from ..core import environments, github
from ..core import pipeline as pipe
from ..core.docker import Docker, DockerError
from ..core.git import Git, GitError
from ..core.ssh import SSH, SSHProfile

TEMPLATES = {
    "Python : tests + lint": {"name": "python-ci", "environment": "dev", "env": {}, "notify": True, "steps": [
        {"name": "lint", "command": "ruff check .", "continue_on_error": True},
        {"name": "tests", "command": "python -m pytest -q", "retries": 1}]},
    "Node.js : installer + tests": {"name": "node-ci", "environment": "dev", "env": {}, "notify": True, "steps": [
        {"name": "install", "command": "npm ci", "timeout": 600}, {"name": "tests", "command": "npm test"}]},
    "Rust : build + tests": {"name": "rust-ci", "environment": "dev", "env": {}, "notify": True, "steps": [
        {"name": "build", "command": "cargo build --release", "timeout": 1200}, {"name": "tests", "command": "cargo test"}]},
}
TARGET_TEMPLATE = {"name": "staging-local", "source": ".", "dest": "/tmp/mon-deploiement", "ssh": "", "environment": "staging",
                   "pre": [], "post": [], "health": "", "exclude": [".git", "__pycache__", "node_modules", ".venv", "target"]}


def table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.horizontalHeader().setStretchLastSection(True)
    return t


def fill(t: QTableWidget, rows: list[list]) -> None:
    t.setRowCount(0)
    for row in rows:
        r = t.rowCount()
        t.insertRow(r)
        for c, v in enumerate(row):
            t.setItem(r, c, QTableWidgetItem(str(v)))


def _alive(fn):
    """Ignore le résultat d'une tâche asynchrone si le widget a déjà été détruit (fermeture, rechargement)."""
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except RuntimeError:
            return None
    return wrapper


class DevOpsWidget(QWidget):
    """Dépendances injectées : `store`, `runner(args, cwd, timeout, env, cancel, on_line)`, `run_async`, `http`, `token`, `notify`, `confirm`."""

    def __init__(self, store, runner, run_async=None, http=None, token=lambda: "", notify=None, confirm=None, options=None):
        super().__init__()
        self.store, self.runner, self._async = store, runner, run_async
        self.http, self.token = http, token
        self.notify = notify or (lambda msg: None)
        self.confirm = confirm or (lambda title, text: QMessageBox.question(self, title, text) == QMessageBox.Yes)
        self.opts = options or {}
        self.project: Path | None = None
        self.cancel = threading.Event()
        self.queue: list[str] = []
        self.busy = False
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain)
        self.timer.start(150)

    # ---------------------------------------------------------------- infrastructure
    def run(self, args, cwd=None, timeout=120, env=None, cancel=None, on_line=None):
        return self.runner(args, cwd=cwd, timeout=timeout, env=env, cancel=cancel, on_line=on_line)

    def bg(self, work, done=None):
        def fail(exc):
            self.busy = False
            self.status.setText(f"Erreur : {exc}")

        def ok(res):
            self.busy = False
            if done:
                done(res)
        self.busy = True
        if self._async:
            self._async(work, _alive(ok), _alive(fail))
        else:
            try:
                ok(work())
            except Exception as exc:  # noqa: BLE001
                fail(exc)

    def say(self, line: str) -> None:
        self.queue.append(line)

    def _drain(self) -> None:
        if self.queue:
            chunk, self.queue = self.queue, []
            self.live.appendPlainText("\n".join(chunk))

    def git(self) -> Git:
        return Git(self.project, lambda args, cwd=None, timeout=60: self.run(args, cwd, timeout))

    def docker(self) -> Docker:
        return Docker(lambda args, cwd=None, timeout=60: self.run(args, cwd, timeout), self.project)

    # ---------------------------------------------------------------- construction
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        self.title = QLabel("Sélectionnez un projet")
        self.status = QLabel("")
        lay.addWidget(self.title)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.status)
        self.live = QPlainTextEdit()
        self.live.setReadOnly(True)
        self.live.setMaximumHeight(150)
        self.live.setPlaceholderText("Sortie en direct…")
        lay.addWidget(self.live)
        self._tab_env()
        self._tab_git()
        self._tab_docker()
        self._tab_servers()
        self._tab_deploy()
        self._tab_pipelines()
        self._tab_history()

    def _tab_env(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)  # noqa: E741
        self.env_tools = table(["Outil", "État", "Version"])
        self.env_info = QLabel("")
        self.env_info.setWordWrap(True)
        b = QPushButton("Détecter")
        b.clicked.connect(self.refresh_env)
        for x in (b, self.env_tools, self.env_info):
            l.addWidget(x)
        self.tabs.addTab(w, "Environnements")

    def _tab_git(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)  # noqa: E741
        bar = QHBoxLayout()
        self.git_label = QLabel("")
        self.btn_git_refresh = QPushButton("Actualiser")
        self.btn_fetch = QPushButton("Fetch")
        self.btn_pull = QPushButton("Pull (fast-forward)")
        self.btn_checkout = QPushButton("Changer de branche")
        self.btn_gh_issues = QPushButton("Tickets GitHub")
        self.btn_gh_prs = QPushButton("Pull requests")
        for x in (self.git_label, self.btn_git_refresh, self.btn_fetch, self.btn_pull, self.btn_checkout, self.btn_gh_issues, self.btn_gh_prs):
            bar.addWidget(x)
        l.addLayout(bar)
        sp = QSplitter(Qt.Vertical)
        top = QSplitter()
        self.git_changes = table(["État", "Fichier"])
        self.git_branches = table(["", "Branche", "Commit", "Suivi"])
        self.git_log = table(["Commit", "Auteur", "Date", "Message"])
        top.addWidget(self.git_changes)
        top.addWidget(self.git_branches)
        sp.addWidget(top)
        sp.addWidget(self.git_log)
        self.git_diff = QPlainTextEdit()
        self.git_diff.setReadOnly(True)
        sp.addWidget(self.git_diff)
        l.addWidget(sp, 1)
        self.gh_table = table(["#", "Titre", "Auteur", "État", "Adresse"])
        l.addWidget(self.gh_table)
        self.btn_git_refresh.clicked.connect(self.refresh_git)
        self.btn_fetch.clicked.connect(lambda: self._git_op("fetch"))
        self.btn_pull.clicked.connect(lambda: self._git_op("pull"))
        self.btn_checkout.clicked.connect(self.git_checkout)
        self.btn_gh_issues.clicked.connect(lambda: self.refresh_github("issues"))
        self.btn_gh_prs.clicked.connect(lambda: self.refresh_github("pulls"))
        self.git_changes.cellClicked.connect(self._show_diff)
        self.tabs.addTab(w, "Git")

    def _tab_docker(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)  # noqa: E741
        bar = QHBoxLayout()
        self.docker_label = QLabel("")
        bar.addWidget(self.docker_label, 1)
        self.docker_btns = {}
        for key, text in (("refresh", "Actualiser"), ("start", "Démarrer"), ("stop", "Arrêter"), ("restart", "Redémarrer"),
                          ("logs", "Journaux"), ("up", "compose up"), ("down", "compose down")):
            b = QPushButton(text)
            bar.addWidget(b)
            self.docker_btns[key] = b
        l.addLayout(bar)
        self.docker_ct = table(["Nom", "Image", "État", "Ports"])
        self.docker_img = table(["Image", "Tag", "Taille"])
        self.docker_log = QPlainTextEdit()
        self.docker_log.setReadOnly(True)
        for x in (self.docker_ct, self.docker_img, self.docker_log):
            l.addWidget(x)
        self.docker_btns["refresh"].clicked.connect(self.refresh_docker)
        for verb in ("start", "stop", "restart"):
            self.docker_btns[verb].clicked.connect(lambda _=False, v=verb: self.docker_action(v))
        self.docker_btns["logs"].clicked.connect(self.docker_logs)
        self.docker_btns["up"].clicked.connect(lambda: self.compose("up"))
        self.docker_btns["down"].clicked.connect(lambda: self.compose("down"))
        self.tabs.addTab(w, "Docker")

    def _tab_servers(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)  # noqa: E741
        self.ssh_table = table(["Nom", "Hôte", "Utilisateur", "Port", "Clé", "Env."])
        form = QFormLayout()
        self.f_name, self.f_host, self.f_user, self.f_key = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.f_port = QSpinBox()
        self.f_port.setRange(1, 65535)
        self.f_port.setValue(22)
        self.f_env = QComboBox()
        self.f_env.addItems(["dev", "staging", "prod"])
        for label, wd in (("Nom", self.f_name), ("Hôte", self.f_host), ("Utilisateur", self.f_user), ("Port", self.f_port),
                          ("Clé privée (chemin)", self.f_key), ("Environnement", self.f_env)):
            form.addRow(label, wd)
        bar = QHBoxLayout()
        self.btn_ssh_save, self.btn_ssh_del, self.btn_ssh_test = QPushButton("Enregistrer le profil"), QPushButton("Supprimer"), QPushButton("Tester")
        for b in (self.btn_ssh_save, self.btn_ssh_del, self.btn_ssh_test):
            bar.addWidget(b)
        self.ssh_cmd = QLineEdit()
        self.ssh_cmd.setPlaceholderText("Commande à exécuter sur le serveur sélectionné…")
        self.btn_ssh_exec = QPushButton("Exécuter")
        row = QHBoxLayout()
        row.addWidget(self.ssh_cmd, 1)
        row.addWidget(self.btn_ssh_exec)
        self.ssh_out = QPlainTextEdit()
        self.ssh_out.setReadOnly(True)
        for x in (self.ssh_table,):
            l.addWidget(x)
        l.addLayout(form)
        l.addLayout(bar)
        l.addLayout(row)
        l.addWidget(self.ssh_out)
        self.btn_ssh_save.clicked.connect(self.ssh_save)
        self.btn_ssh_del.clicked.connect(self.ssh_delete)
        self.btn_ssh_test.clicked.connect(self.ssh_test)
        self.btn_ssh_exec.clicked.connect(self.ssh_exec)
        self.ssh_table.cellClicked.connect(self._ssh_fill_form)
        self.tabs.addTab(w, "Serveurs")

    def _tab_deploy(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)  # noqa: E741
        self.targets_list = QListWidget()
        self.target_edit = QPlainTextEdit()
        self.target_edit.setPlaceholderText("Cible de déploiement (JSON)")
        bar = QHBoxLayout()
        self.btn_t_new, self.btn_t_save, self.btn_t_del, self.btn_t_run = (QPushButton(x) for x in
                                                                           ("Nouvelle", "Enregistrer", "Supprimer", "Déployer"))
        for b in (self.btn_t_new, self.btn_t_save, self.btn_t_del, self.btn_t_run):
            bar.addWidget(b)
        l.addWidget(QLabel("Une sauvegarde est faite avant chaque déploiement ; en cas d'échec elle est restaurée automatiquement. "
                           "La production demande une confirmation."))
        sp = QSplitter()
        sp.addWidget(self.targets_list)
        sp.addWidget(self.target_edit)
        l.addWidget(sp, 1)
        l.addLayout(bar)
        self.btn_t_new.clicked.connect(lambda: self.target_edit.setPlainText(json.dumps(TARGET_TEMPLATE, indent=2, ensure_ascii=False)))
        self.btn_t_save.clicked.connect(self.target_save)
        self.btn_t_del.clicked.connect(self.target_delete)
        self.btn_t_run.clicked.connect(self.target_deploy)
        self.targets_list.currentTextChanged.connect(self._target_show)
        self.tabs.addTab(w, "Déploiements")

    def _tab_pipelines(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)  # noqa: E741
        self.pipes_list = QListWidget()
        self.pipe_edit = QPlainTextEdit()
        self.pipe_edit.setPlaceholderText("Pipeline (JSON) : étapes, conditions, tentatives, délais…")
        self.tpl = QComboBox()
        self.tpl.addItems(["Modèle…", *TEMPLATES])
        bar = QHBoxLayout()
        self.btn_p_save, self.btn_p_del, self.btn_p_run, self.btn_p_cancel = (QPushButton(x) for x in
                                                                              ("Enregistrer", "Supprimer", "Exécuter", "Annuler"))
        bar.addWidget(self.tpl)
        for b in (self.btn_p_save, self.btn_p_del, self.btn_p_run, self.btn_p_cancel):
            bar.addWidget(b)
        sp = QSplitter()
        sp.addWidget(self.pipes_list)
        sp.addWidget(self.pipe_edit)
        l.addWidget(sp, 1)
        l.addLayout(bar)
        self.btn_p_save.clicked.connect(self.pipe_save)
        self.btn_p_del.clicked.connect(self.pipe_delete)
        self.btn_p_run.clicked.connect(self.pipe_run)
        self.btn_p_cancel.clicked.connect(self.cancel.set)
        self.pipes_list.currentTextChanged.connect(self._pipe_show)
        self.tpl.currentTextChanged.connect(lambda t: t in TEMPLATES and self.pipe_edit.setPlainText(json.dumps(TEMPLATES[t], indent=2, ensure_ascii=False)))
        self.tabs.addTab(w, "Pipelines")

    def _tab_history(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)  # noqa: E741
        self.hist_table = table(["Date", "Type", "Nom", "Env.", "Résultat"])
        self.hist_log = QTextBrowser()
        self.btn_h_clear = QPushButton("Vider l'historique")
        l.addWidget(self.hist_table, 1)
        l.addWidget(self.hist_log, 1)
        l.addWidget(self.btn_h_clear)
        self.hist_table.cellClicked.connect(self._hist_show)
        self.btn_h_clear.clicked.connect(lambda: (self.store.clear_history(), self.refresh_history()))
        self.tabs.addTab(w, "Historique")

    # ---------------------------------------------------------------- projet
    def set_project(self, path) -> None:
        self.project = Path(path) if path else None
        self.title.setText(f"Projet : {self.project.name}" if self.project else "Sélectionnez un projet")
        self.refresh_all()

    def refresh_all(self) -> None:
        self.refresh_env()
        self.refresh_servers()
        self.refresh_targets()
        self.refresh_pipes()
        self.refresh_history()
        if self.project and self.opts.get("auto_refresh", True):
            self.refresh_git()

    # ---------------------------------------------------------------- environnements
    def refresh_env(self) -> None:
        def work():
            tools = environments.tool_versions(lambda a, timeout=10: self.run(a, None, timeout))
            return tools, (environments.project_environment(self.project) if self.project else {})

        def done(res):
            tools, info = res
            fill(self.env_tools, [[t["tool"], "✓" if t["ok"] else "✗", t["version"]] for t in tools])
            self.env_info.setText(f"Fichiers détectés : {', '.join(info.get('markers', [])) or '—'} · environnements virtuels : "
                                  f"{', '.join(info.get('venvs', [])) or '—'} · fichiers .env : {', '.join(info.get('env_files', [])) or '—'} "
                                  "(valeurs jamais lues)")
        self.bg(work, done)

    # ---------------------------------------------------------------- Git
    def refresh_git(self) -> None:
        if not self.project:
            return

        def work():
            g = self.git()
            if not g.is_repo():
                return None
            return g.status(), g.branches(), g.log(30)

        def done(res):
            if res is None:
                self.git_label.setText("Ce dossier n'est pas un dépôt Git.")
                for t in (self.git_changes, self.git_branches, self.git_log):
                    t.setRowCount(0)
                return
            st, branches, log = res
            self.git_label.setText(f"{st.branch} ↑{st.ahead} ↓{st.behind}" + (" · propre" if st.clean else ""))
            fill(self.git_changes, [[f"index {c}", p] for c, p in st.staged] + [[f"modifié {c}", p] for c, p in st.changed]
                 + [["non suivi", p] for p in st.untracked])
            fill(self.git_branches, [["●" if b["current"] else "", b["name"], b["sha"], b["upstream"]] for b in branches])
            fill(self.git_log, [[c["sha"], c["author"], c["date"], c["subject"]] for c in log])
        self.bg(work, done)

    def _show_diff(self, row, _col) -> None:
        path = self.git_changes.item(row, 1).text()
        kind = self.git_changes.item(row, 0).text()
        if kind == "non suivi":
            self.git_diff.setPlainText("(fichier non suivi : pas de différence à montrer)")
            return
        try:
            self.git_diff.setPlainText(self.git().diff(path, staged=kind.startswith("index")) or "(aucune différence)")
        except GitError as exc:
            self.git_diff.setPlainText(str(exc))

    def _git_op(self, op: str) -> None:
        def work():
            g = self.git()
            return (g.fetch() if op == "fetch" else g.pull()).out

        def done(out):
            self.status.setText(f"git {op} : {out.strip().splitlines()[-1] if out.strip() else 'terminé'}")
            self.refresh_git()
        self.bg_safe(work, done)

    def bg_safe(self, work, done) -> None:
        def guarded():
            try:
                return work()
            except (GitError, DockerError, deploy_mod.DeployError, github.GitHubError, ValueError) as exc:
                return exc

        def after(res):
            if isinstance(res, Exception):
                self.status.setText(f"✗ {res}")
            else:
                done(res)
        self.bg(guarded, after)

    def git_checkout(self) -> None:
        row = self.git_branches.currentRow()
        if row < 0:
            self.status.setText("Sélectionnez une branche.")
            return
        name = self.git_branches.item(row, 1).text()
        if name.startswith("origin/"):
            name = name[len("origin/"):]
        self.bg_safe(lambda: self.git().checkout(name), lambda _r: (self.status.setText(f"Branche : {name}"), self.refresh_git()))

    def refresh_github(self, what: str) -> None:
        def work():
            owner_repo = github.parse_remote(self.git().remote_url())
            if not owner_repo:
                raise github.GitHubError("Le dépôt distant n'est pas sur GitHub.")
            gh = github.GitHub(self.http, lambda a, timeout=60: self.run(a, None, timeout), self.token)
            prefer_cli = bool(self.opts.get("prefer_gh_cli")) or self.http is None
            return (gh.issues if what == "issues" else gh.pulls)(*owner_repo, prefer_cli=prefer_cli)
        self.bg_safe(work, lambda rows: fill(self.gh_table, [[r["number"], r["title"], r["author"], r["state"], r["url"]] for r in rows]))

    # ---------------------------------------------------------------- Docker
    def refresh_docker(self) -> None:
        def work():
            d = self.docker()
            ok, info = d.available()
            return (ok, info, d.containers(), d.images()) if ok else (ok, info, [], [])

        def done(res):
            ok, info, cts, imgs = res
            self.docker_label.setText(f"Docker {info}" if ok else f"Docker indisponible : {info}")
            fill(self.docker_ct, [[c["name"], c["image"], c["status"], c["ports"]] for c in cts])
            fill(self.docker_img, [[i["repo"], i["tag"], i["size"]] for i in imgs])
        self.bg_safe(work, done)

    def _selected_container(self) -> str:
        row = self.docker_ct.currentRow()
        return self.docker_ct.item(row, 0).text() if row >= 0 else ""

    def docker_action(self, verb: str) -> None:
        name = self._selected_container()
        if not name:
            self.status.setText("Sélectionnez un conteneur.")
            return
        self.bg_safe(lambda: self.docker().action(verb, name), lambda _r: self.refresh_docker())

    def docker_logs(self) -> None:
        name = self._selected_container()
        if name:
            self.bg_safe(lambda: self.docker().logs(name), self.docker_log.setPlainText)

    def compose(self, verb: str) -> None:
        if verb == "down" and not self.confirm("compose down", "Arrêter et supprimer les conteneurs du projet ?"):
            return
        self.bg_safe(lambda: self.docker().compose(verb).out, lambda out: (self.docker_log.setPlainText(out), self.refresh_docker()))

    # ---------------------------------------------------------------- Serveurs SSH
    def profiles(self) -> dict[str, SSHProfile]:
        return {p["name"]: SSHProfile(**p) for p in self.store.load("ssh", [])}

    def refresh_servers(self) -> None:
        fill(self.ssh_table, [[p.name, p.host, p.user, p.port, p.key_path, p.environment] for p in self.profiles().values()])

    def _ssh_fill_form(self, row, _c) -> None:
        p = self.profiles().get(self.ssh_table.item(row, 0).text())
        if p:
            self.f_name.setText(p.name)
            self.f_host.setText(p.host)
            self.f_user.setText(p.user)
            self.f_port.setValue(int(p.port))
            self.f_key.setText(p.key_path)
            self.f_env.setCurrentText(p.environment)

    def ssh_save(self) -> bool:
        p = SSHProfile(self.f_name.text().strip(), self.f_host.text().strip(), self.f_user.text().strip(), self.f_port.value(),
                       self.f_key.text().strip(), self.f_env.currentText())
        try:
            p.validate()
        except ValueError as exc:
            self.status.setText(f"✗ {exc}")
            return False
        items = [x for x in self.store.load("ssh", []) if x["name"] != p.name] + [p.to_dict()]
        self.store.save("ssh", sorted(items, key=lambda x: x["name"]))
        self.refresh_servers()
        return True

    def ssh_delete(self) -> None:
        name = self.f_name.text().strip()
        self.store.save("ssh", [x for x in self.store.load("ssh", []) if x["name"] != name])
        self.refresh_servers()

    def _ssh_selected(self) -> SSHProfile | None:
        row = self.ssh_table.currentRow()
        name = self.ssh_table.item(row, 0).text() if row >= 0 else self.f_name.text().strip()
        p = self.profiles().get(name)
        if p is None:
            self.status.setText("Choisissez ou enregistrez un profil.")
        return p

    def ssh_test(self) -> None:
        p = self._ssh_selected()
        if p:
            self.bg_safe(lambda: SSH(lambda a, **kw: self.run(a, None, kw.get("timeout", 60))).test(p),
                         lambda r: self.ssh_out.setPlainText(("✓ connexion réussie\n" if r.ok else "✗ échec\n") + r.out))

    def ssh_exec(self) -> None:
        p, cmd = self._ssh_selected(), self.ssh_cmd.text().strip()
        if not p or not cmd:
            return
        if p.environment == "prod" and not self.confirm("Serveur de production", f"Exécuter « {cmd} » sur {p.name} (production) ?"):
            return
        self.bg_safe(lambda: SSH(lambda a, **kw: self.run(a, None, kw.get("timeout", 60))).exec(p, cmd),
                     lambda r: (self.ssh_out.setPlainText(r.out or r.error), self._record("ssh", f"{p.name}: {cmd}", p.environment, r.ok, r.out)))

    # ---------------------------------------------------------------- Déploiements
    def refresh_targets(self) -> None:
        self.targets_list.clear()
        self.targets_list.addItems([t["name"] for t in self.store.load("targets", [])])

    def _target_show(self, name) -> None:
        for t in self.store.load("targets", []):
            if t["name"] == name:
                self.target_edit.setPlainText(json.dumps(t, indent=2, ensure_ascii=False))

    def _edited_target(self) -> deploy_mod.Target | None:
        try:
            d = json.loads(self.target_edit.toPlainText())
            return deploy_mod.Target(**{k: v for k, v in d.items() if k in deploy_mod.Target.__dataclass_fields__})
        except (ValueError, TypeError) as exc:
            self.status.setText(f"✗ JSON invalide : {exc}")
            return None

    def target_save(self) -> bool:
        t = self._edited_target()
        if not t or not t.name.strip():
            return False
        items = [x for x in self.store.load("targets", []) if x["name"] != t.name] + [t.to_dict()]
        self.store.save("targets", items)
        self.refresh_targets()
        return True

    def target_delete(self) -> None:
        item = self.targets_list.currentItem()
        if item:
            self.store.save("targets", [x for x in self.store.load("targets", []) if x["name"] != item.text()])
            self.refresh_targets()

    def target_deploy(self) -> dict | None:
        t = self._edited_target()
        if not t or not self.project:
            return None
        confirmed = True
        if t.environment == "prod":
            confirmed = self.confirm("Production", f"Déployer « {t.name} » EN PRODUCTION ?\nUne sauvegarde sera faite et restaurée en cas d'échec.")
            if not confirmed:
                return None
        profiles, backup_dir = self.profiles(), Path(self.store.base) / "backups"
        self.cancel.clear()

        def work():
            return deploy_mod.deploy(t, str(self.project), backup_dir, self.run, profiles, confirmed, self.cancel, self.say)

        def done(rec):
            self._finish("deploy", rec, t.name)
        self.bg_safe(work, done)
        return None

    # ---------------------------------------------------------------- Pipelines
    def refresh_pipes(self) -> None:
        self.pipes_list.clear()
        self.pipes_list.addItems([p["name"] for p in self.store.load("pipelines", [])])

    def _pipe_show(self, name) -> None:
        for p in self.store.load("pipelines", []):
            if p["name"] == name:
                self.pipe_edit.setPlainText(json.dumps(p, indent=2, ensure_ascii=False))

    def _edited_pipeline(self) -> pipe.Pipeline | None:
        try:
            p = pipe.Pipeline.from_dict(json.loads(self.pipe_edit.toPlainText()))
        except (ValueError, TypeError, KeyError) as exc:
            self.status.setText(f"✗ JSON invalide : {exc}")
            return None
        errs = pipe.validate(p)
        if errs:
            self.status.setText("✗ " + " ".join(errs))
            return None
        return p

    def pipe_save(self) -> bool:
        p = self._edited_pipeline()
        if not p:
            return False
        items = [x for x in self.store.load("pipelines", []) if x["name"] != p.name] + [p.to_dict()]
        self.store.save("pipelines", items)
        self.refresh_pipes()
        return True

    def pipe_delete(self) -> None:
        item = self.pipes_list.currentItem()
        if item:
            self.store.save("pipelines", [x for x in self.store.load("pipelines", []) if x["name"] != item.text()])
            self.refresh_pipes()

    def pipe_run(self) -> None:
        p = self._edited_pipeline()
        if not p or not self.project:
            return
        if p.environment == "prod" and not self.confirm("Production", f"Exécuter « {p.name} » (production) ?"):
            return
        self.cancel.clear()
        project = str(self.project)

        def work():
            try:
                branch = self.git().status().branch
            except GitError:
                branch = ""
            return pipe.run_pipeline(p, project, self.run, self.cancel, lambda k, v: k == "log" and self.say(v), branch)
        self.bg(work, lambda rec: self._finish("pipeline", rec, p.name, p.notify))

    # ---------------------------------------------------------------- Historique
    def _record(self, kind: str, name: str, env: str, ok: bool, log: str) -> None:
        self.store.add_history({"kind": kind, "name": name, "environment": env, "ok": ok, "started": time.time(), "log": log})
        self.refresh_history()

    def _finish(self, kind: str, rec: dict, name: str, notify: bool = True) -> None:
        self.store.add_history(rec)
        self.refresh_history()
        word = "réussi" if rec.get("ok") else ("annulé" if rec.get("cancelled") else "ÉCHEC")
        if rec.get("restored"):
            word += " (sauvegarde restaurée)"
        self.status.setText(f"{kind} « {name} » : {word}")
        if notify and self.opts.get("notify", True):
            self.notify(f"{kind.capitalize()} « {name} » : {word}")

    def refresh_history(self) -> None:
        self._hist = self.store.history()
        fill(self.hist_table, [[time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(h.get("started", 0))), h.get("kind", ""), h.get("name", ""),
                                h.get("environment", ""), "✓" if h.get("ok") else "✗"] for h in self._hist])

    def _hist_show(self, row, _c) -> None:
        if 0 <= row < len(self._hist):
            self.hist_log.setPlainText(self._hist[row].get("log", ""))


def ask_name(parent, title) -> str:
    text, ok = QInputDialog.getText(parent, title, "Nom :")
    return text.strip() if ok else ""
