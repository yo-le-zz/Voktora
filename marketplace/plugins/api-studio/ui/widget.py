"""Interface d'API Studio : collections, éditeur de requête, réponse, environnements, WebSocket, mock, historique."""

from __future__ import annotations

import json
from http.cookiejar import CookieJar
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import mock as mock_mod
from ..core import openapi, postman
from ..core.model import AUTH_TYPES, BODY_TYPES, METHODS, Collection, Request
from ..core.websocket import WebSocketClient, WebSocketError
from ..services import runner


def _alive(fn):
    """Ignore le résultat d'une tâche asynchrone si le widget a déjà été détruit (fermeture, rechargement)."""
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except RuntimeError:
            return None
    return wrapper


class KV(QWidget):
    """Tableau clé / valeur éditable (avec case « actif »)."""

    def __init__(self, with_file: bool = False):
        super().__init__()
        self.with_file = with_file
        self.t = QTableWidget(0, 3)
        self.t.setHorizontalHeaderLabels(["Actif", "Clé", "Valeur"])
        self.t.horizontalHeader().setStretchLastSection(True)
        add = QPushButton("+ Ligne")
        rem = QPushButton("− Ligne")
        add.clicked.connect(lambda: self.add_row())
        rem.clicked.connect(lambda: self.t.removeRow(self.t.currentRow()) if self.t.currentRow() >= 0 else None)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.t)
        lay.addLayout(row)

    def add_row(self, key="", value="", enabled=True) -> None:
        r = self.t.rowCount()
        self.t.insertRow(r)
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        chk.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
        self.t.setItem(r, 0, chk)
        self.t.setItem(r, 1, QTableWidgetItem(key))
        self.t.setItem(r, 2, QTableWidgetItem(value))

    def set_items(self, items: list[dict]) -> None:
        self.t.setRowCount(0)
        for i in items:
            self.add_row(i.get("key", ""), i.get("file") or i.get("value", ""), i.get("enabled", True))

    def items(self) -> list[dict]:
        out = []
        for r in range(self.t.rowCount()):
            key, val = self.t.item(r, 1).text(), self.t.item(r, 2).text()
            d = {"key": key, "value": val, "enabled": self.t.item(r, 0).checkState() == Qt.Checked}
            if self.with_file and val.startswith("@"):
                d.update(file=val[1:], value="")
            out.append(d)
        return out


class ApiStudioWidget(QWidget):
    def __init__(self, store, run_async=None, notify=None, confirm=None):
        super().__init__()
        self.store, self._async = store, run_async
        self.notify = notify or (lambda m: None)
        self.confirm = confirm or (lambda t, x: QMessageBox.question(self, t, x) == QMessageBox.Yes)
        self.project: str | None = None
        self.cols: list[dict] = []
        self.cur: tuple[int, int] | None = None
        self.jar = CookieJar()
        self.chain: dict = {}
        self.mock: mock_mod.MockServer | None = None
        self.ws: WebSocketClient | None = None
        self.ws_log: list[str] = []
        self.verify_tls = True
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_ws)
        self.timer.start(200)

    # ------------------------------------------------------------------ construction
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        self.status = QLabel("")
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.status)
        main = QSplitter()
        # gauche : collections
        left = QWidget()
        ll = QVBoxLayout(left)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Collections"])
        ll.addWidget(self.tree, 1)
        self.btns = {}
        for key, text in (("newc", "Nouvelle collection"), ("newr", "Nouvelle requête"), ("del", "Supprimer"), ("runc", "Lancer la collection"),
                          ("imp", "Importer…"), ("exp", "Exporter…")):
            b = QPushButton(text)
            ll.addWidget(b)
            self.btns[key] = b
        main.addWidget(left)
        # centre : requête + réponse
        right = QSplitter(Qt.Vertical)
        top = QWidget()
        tl = QVBoxLayout(top)
        bar = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Nom de la requête")
        self.method = QComboBox()
        self.method.addItems(METHODS)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://api.exemple.com/{{ressource}}")
        self.send_btn = QPushButton("Envoyer")
        for w, s in ((self.method, 0), (self.url, 1), (self.send_btn, 0)):
            bar.addWidget(w, s)
        tl.addWidget(self.name)
        tl.addLayout(bar)
        self.req_tabs = QTabWidget()
        self.params, self.headers, self.fields = KV(), KV(), KV(with_file=True)
        self.body_type = QComboBox()
        self.body_type.addItems(BODY_TYPES)
        self.body = QPlainTextEdit()
        bw = QWidget()
        bl = QVBoxLayout(bw)
        bl.addWidget(self.body_type)
        bl.addWidget(self.body, 1)
        bl.addWidget(QLabel("Formulaire / multipart : lignes ci-dessous (valeur « @/chemin » pour envoyer un fichier)"))
        bl.addWidget(self.fields, 1)
        self.auth_type = QComboBox()
        self.auth_type.addItems(AUTH_TYPES)
        self.auth_fields = {k: QLineEdit() for k in ("user", "password", "token", "name", "value", "in", "auth_url", "token_url", "client_id",
                                                     "client_secret", "scope", "access_token")}
        aw = QWidget()
        al = QVBoxLayout(aw)
        al.addWidget(self.auth_type)
        for k, w in self.auth_fields.items():
            w.setPlaceholderText({"in": "header ou query", "name": "nom (clé d'API)", "value": "valeur (clé d'API)"}.get(k, k))
            if k in ("password", "client_secret", "token", "access_token"):
                w.setEchoMode(QLineEdit.Password)
            al.addWidget(w)
        self.btn_token = QPushButton("Obtenir un jeton OAuth2 (client_credentials)")
        al.addWidget(self.btn_token)
        al.addStretch()
        self.pre_lang, self.post_lang = QComboBox(), QComboBox()
        for c in (self.pre_lang, self.post_lang):
            c.addItems(["python", "javascript"])
        self.pre, self.post = QPlainTextEdit(), QPlainTextEdit()
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.addWidget(QLabel("Avant l'envoi : variables `vars`, requête `request` · `log()`"))
        sl.addWidget(self.pre_lang)
        sl.addWidget(self.pre)
        sl.addWidget(QLabel("Après la réponse : `response.status/.text/.json()`, `vars`, `test(nom, ok)`"))
        sl.addWidget(self.post_lang)
        sl.addWidget(self.post)
        self.extract = QPlainTextEdit()
        self.extract.setPlaceholderText('Extraction (JSON) : [{"var":"id","source":"json","expr":"$.data.id"}]  sources : json, header, regex, status')
        self.tests = QPlainTextEdit()
        self.tests.setPlaceholderText('Tests (JSON) : [{"kind":"status","op":"==","value":"200"},{"kind":"json","expr":"$.ok","op":"==","value":"true"}]')
        for w, t in ((self.params, "Paramètres"), (self.headers, "En-têtes"), (aw, "Authentification"), (bw, "Corps"), (sw, "Scripts"),
                     (self.extract, "Chaînage"), (self.tests, "Tests")):
            self.req_tabs.addTab(w, t)
        tl.addWidget(self.req_tabs, 1)
        right.addWidget(top)
        self.resp_tabs = QTabWidget()
        self.resp_info = QLabel("Aucune réponse.")
        self.resp_body = QPlainTextEdit()
        self.resp_body.setReadOnly(True)
        self.resp_headers = QPlainTextEdit()
        self.resp_headers.setReadOnly(True)
        self.resp_tests = QPlainTextEdit()
        self.resp_tests.setReadOnly(True)
        rw = QWidget()
        rl = QVBoxLayout(rw)
        rl.addWidget(self.resp_info)
        rl.addWidget(self.resp_body)
        self.resp_tabs.addTab(rw, "Réponse")
        self.resp_tabs.addTab(self.resp_headers, "En-têtes")
        self.resp_tabs.addTab(self.resp_tests, "Tests & journal")
        right.addWidget(self.resp_tabs)
        main.addWidget(right)
        main.setSizes([260, 800])
        self.tabs.addTab(main, "Requêtes")
        self._tab_env()
        self._tab_ws()
        self._tab_mock()
        self._tab_history()
        self.btns["newc"].clicked.connect(self.new_collection)
        self.btns["newr"].clicked.connect(self.new_request)
        self.btns["del"].clicked.connect(self.delete_selected)
        self.btns["runc"].clicked.connect(self.run_collection)
        self.btns["imp"].clicked.connect(lambda: self.import_file())
        self.btns["exp"].clicked.connect(lambda: self.export_file())
        self.tree.currentItemChanged.connect(self._select)
        self.send_btn.clicked.connect(self.send)
        self.btn_token.clicked.connect(self.fetch_token)

    def _tab_env(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)  # noqa: E741
        self.env_name = QComboBox()
        self.env_name.setEditable(True)
        self.env_vars = KV()
        row = QHBoxLayout()
        save, rm, clr = QPushButton("Enregistrer l'environnement"), QPushButton("Supprimer"), QPushButton("Oublier les variables chaînées et cookies")
        for b in (save, rm, clr):
            row.addWidget(b)
        l.addWidget(QLabel("Environnement actif (variables {{nom}}) — les variables de la collection et celles extraites des réponses s'y ajoutent."))
        l.addWidget(self.env_name)
        l.addWidget(self.env_vars)
        l.addLayout(row)
        self.chain_view = QPlainTextEdit()
        self.chain_view.setReadOnly(True)
        l.addWidget(self.chain_view)
        save.clicked.connect(self.env_save)
        rm.clicked.connect(self.env_delete)
        clr.clicked.connect(self.clear_chain)
        self.env_name.currentTextChanged.connect(self._env_show)
        self.tabs.addTab(w, "Environnements")

    def _tab_ws(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)  # noqa: E741
        self.ws_url = QLineEdit()
        self.ws_url.setPlaceholderText("ws://127.0.0.1:8765/ws ou wss://…")
        row = QHBoxLayout()
        self.ws_connect, self.ws_close = QPushButton("Connecter"), QPushButton("Fermer")
        row.addWidget(self.ws_url, 1)
        row.addWidget(self.ws_connect)
        row.addWidget(self.ws_close)
        self.ws_view = QPlainTextEdit()
        self.ws_view.setReadOnly(True)
        self.ws_msg = QLineEdit()
        self.ws_send = QPushButton("Envoyer")
        row2 = QHBoxLayout()
        row2.addWidget(self.ws_msg, 1)
        row2.addWidget(self.ws_send)
        for x in (row, self.ws_view, row2):
            l.addLayout(x) if not isinstance(x, QWidget) else l.addWidget(x)
        self.ws_connect.clicked.connect(self.ws_open)
        self.ws_close.clicked.connect(self.ws_shut)
        self.ws_send.clicked.connect(self.ws_post)
        self.tabs.addTab(w, "WebSocket")

    def _tab_mock(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)  # noqa: E741
        self.mock_edit = QPlainTextEdit()
        self.mock_edit.setPlainText(json.dumps([{"method": "GET", "path": "/users/{id}", "status": 200, "body": '{"id": "{{id}}"}', "delay_ms": 0}],
                                               indent=2))
        row = QHBoxLayout()
        self.mock_start, self.mock_stop = QPushButton("Démarrer (127.0.0.1)"), QPushButton("Arrêter")
        self.mock_label = QLabel("Arrêté. Écho WebSocket sur /ws.")
        for x in (self.mock_start, self.mock_stop, self.mock_label):
            row.addWidget(x)
        self.mock_hits = QPlainTextEdit()
        self.mock_hits.setReadOnly(True)
        l.addWidget(self.mock_edit, 1)
        l.addLayout(row)
        l.addWidget(self.mock_hits, 1)
        self.mock_start.clicked.connect(self.mock_run)
        self.mock_stop.clicked.connect(self.mock_halt)
        self.tabs.addTab(w, "Serveur mock")

    def _tab_history(self) -> None:
        w = QWidget()
        l = QVBoxLayout(w)  # noqa: E741
        self.hist = QTableWidget(0, 4)
        self.hist.setHorizontalHeaderLabels(["Heure", "Requête", "Code", "Durée (ms)"])
        self.hist.horizontalHeader().setStretchLastSection(True)
        self.hist.setEditTriggers(QTableWidget.NoEditTriggers)
        clr = QPushButton("Vider l'historique")
        l.addWidget(self.hist)
        l.addWidget(clr)
        clr.clicked.connect(lambda: (self.store.clear_history(self.project), self.refresh_history()))
        self.tabs.addTab(w, "Historique")

    # ------------------------------------------------------------------ projet & collections
    def set_project(self, path) -> None:
        self.project = str(path) if path else None
        self.cols = self.store.collections(self.project)
        self.refresh_tree()
        self.refresh_env()
        self.refresh_history()

    def refresh_tree(self) -> None:
        self.tree.clear()
        for ci, c in enumerate(self.cols):
            top = QTreeWidgetItem([c["name"]])
            top.setData(0, Qt.UserRole, (ci, -1))
            for ri, r in enumerate(c["requests"]):
                it = QTreeWidgetItem([f"{r.get('method', 'GET')}  {r.get('name', '')}"])
                it.setData(0, Qt.UserRole, (ci, ri))
                top.addChild(it)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)

    def _save_cols(self) -> None:
        for c in self.cols:
            self.store.save_collection(self.project, c)

    def new_collection(self, name: str | None = None) -> None:
        name = name or f"Collection {len(self.cols) + 1}"
        if any(c["name"] == name for c in self.cols):
            return
        self.cols.append(Collection(name).to_dict())
        self._save_cols()
        self.refresh_tree()

    def new_request(self) -> None:
        if not self.cols:
            self.new_collection()
        ci = self.cur[0] if self.cur else 0
        self.cols[ci]["requests"].append(Request(name=f"Requête {len(self.cols[ci]['requests']) + 1}", url="{{baseUrl}}/").to_dict())
        self._save_cols()
        self.refresh_tree()
        self.tree.setCurrentItem(self.tree.topLevelItem(ci).child(len(self.cols[ci]["requests"]) - 1))

    def delete_selected(self) -> None:
        if not self.cur:
            return
        ci, ri = self.cur
        if ri < 0:
            self.store.delete_collection(self.project, self.cols[ci]["name"])
            del self.cols[ci]
        else:
            del self.cols[ci]["requests"][ri]
            self._save_cols()
        self.cur = None
        self.refresh_tree()

    def _select(self, item, _prev=None) -> None:
        if self.cur and self.cur[1] >= 0 and self.cur[0] < len(self.cols) and self.cur[1] < len(self.cols[self.cur[0]]["requests"]):
            self.cols[self.cur[0]]["requests"][self.cur[1]] = self.read_request().to_dict()
            self._save_cols()
        self.cur = item.data(0, Qt.UserRole) if item else None
        if self.cur and self.cur[1] >= 0:
            self.load_request(Request.from_dict(self.cols[self.cur[0]]["requests"][self.cur[1]]))

    def load_request(self, r: Request) -> None:
        self.name.setText(r.name)
        self.method.setCurrentText(r.method)
        self.url.setText(r.url)
        self.params.set_items(r.params)
        self.headers.set_items(r.headers)
        self.body_type.setCurrentText(r.body_type)
        self.body.setPlainText(r.body)
        self.fields.set_items(r.body_fields)
        a = r.auth
        self.auth_type.setCurrentText(a.get("type", "none"))
        for k, w in self.auth_fields.items():
            w.setText(str(a.get(k, "")))
        self.pre_lang.setCurrentText(r.pre_script.get("lang", "python"))
        self.pre.setPlainText(r.pre_script.get("code", ""))
        self.post_lang.setCurrentText(r.post_script.get("lang", "python"))
        self.post.setPlainText(r.post_script.get("code", ""))
        self.extract.setPlainText(json.dumps(r.extract, ensure_ascii=False) if r.extract else "")
        self.tests.setPlainText(json.dumps(r.tests, ensure_ascii=False) if r.tests else "")

    def _json_list(self, edit: QPlainTextEdit, what: str) -> list:
        text = edit.toPlainText().strip()
        if not text:
            return []
        try:
            data = json.loads(text)
            if not isinstance(data, list):
                raise ValueError("une liste est attendue")
            return data
        except ValueError as exc:
            self.status.setText(f"✗ {what} : JSON invalide ({exc})")
            raise

    def read_request(self) -> Request:
        a = {"type": self.auth_type.currentText(), **{k: w.text() for k, w in self.auth_fields.items() if w.text()}}
        return Request(name=self.name.text() or "Requête", method=self.method.currentText(), url=self.url.text().strip(),
                       headers=self.headers.items(), params=self.params.items(), body_type=self.body_type.currentText(), body=self.body.toPlainText(),
                       body_fields=self.fields.items(), auth=a, pre_script={"lang": self.pre_lang.currentText(), "code": self.pre.toPlainText()},
                       post_script={"lang": self.post_lang.currentText(), "code": self.post.toPlainText()},
                       extract=self._json_list(self.extract, "Chaînage"), tests=self._json_list(self.tests, "Tests"))

    # ------------------------------------------------------------------ envoi
    def env_vars_now(self) -> dict:
        return {i["key"]: i["value"] for i in self.env_vars.items() if i["enabled"] and i["key"]}

    def scopes(self) -> list[dict]:
        col = self.cols[self.cur[0]] if self.cur else {}
        return [col.get("variables", {}), self.env_vars_now()]

    def bg(self, work, done) -> None:
        if self._async:
            self._async(work, _alive(done), _alive(lambda e: self.status.setText(f"✗ {e}")))
        else:
            done(work())

    def send(self) -> None:
        try:
            req = self.read_request()
        except ValueError:
            return
        scopes, chain, verify = self.scopes(), self.chain, self.verify_tls
        self.send_btn.setEnabled(False)
        self.status.setText("Envoi…")

        def work():
            return runner.run_request(req, scopes, chain, self.jar, verify)

        def done(res):
            self.send_btn.setEnabled(True)
            self.show_result(req, res)
        self.bg(work, done)

    def show_result(self, req: Request, res: dict) -> None:
        resp = res["response"]
        ms = round(resp.seconds * 1000)
        self.resp_info.setText(f"{resp.status} {resp.reason} · {ms} ms · {len(resp.body)} octets" + (f" · ⚠ {resp.error}" if resp.error else ""))
        body = resp.text
        if "json" in resp.header("content-type").lower():
            try:
                body = json.dumps(resp.json(), indent=2, ensure_ascii=False)
            except ValueError:
                pass
        self.resp_body.setPlainText(body)
        self.resp_headers.setPlainText("\n".join(f"{k}: {v}" for k, v in resp.headers))
        lines = [f"{'✓' if t['ok'] else '✗'} {t['name']} — {t.get('detail', '')}" for t in res["tests"]]
        self.resp_tests.setPlainText("\n".join([*lines, *res["logs"], *(f"⚠ {e}" for e in res["errors"])]))
        self.chain_view.setPlainText("\n".join(f"{k} = {v}" for k, v in self.chain.items()))
        self.store.add_history(self.project, {"name": req.name, "method": req.method, "url": res["prepared"]["url"], "status": resp.status, "ms": ms})
        self.refresh_history()
        bad = sum(not t["ok"] for t in res["tests"])
        self.status.setText(f"{resp.status} en {ms} ms" + (f" · {bad} test(s) en échec" if bad else (" · tests OK" if res["tests"] else "")))

    def run_collection(self) -> list | None:
        if not self.cur:
            self.status.setText("Sélectionnez une collection.")
            return None
        col = self.cols[self.cur[0]]
        env, verify = self.env_vars_now(), self.verify_tls

        def done(out):
            ok = sum(o["ok"] for o in out)
            self.resp_tests.setPlainText("\n".join(f"{'✓' if o['ok'] else '✗'} {o['name']} — {o['status']} ({round(o['seconds'] * 1000)} ms) "
                                                   + " ".join(o["errors"]) for o in out))
            self.resp_tabs.setCurrentIndex(2)
            self.status.setText(f"Collection : {ok}/{len(out)} requêtes réussies.")
            self.notify(f"Collection « {col['name']} » : {ok}/{len(out)} réussies")
        self.bg(lambda: runner.run_collection(col, env, self.jar, verify_tls=verify), done)
        return None

    def fetch_token(self) -> None:
        from ..core import auth as auth_mod
        from ..core import client
        f = {k: w.text() for k, w in self.auth_fields.items()}
        tr = auth_mod.token_request("client_credentials", f["token_url"], f["client_id"], f["client_secret"], scope=f["scope"])

        def work():
            return client.send({"method": "POST", "url": tr["url"], "headers": tr["headers"], "body": tr["body"].encode(), "missing": []}, 20)

        def done(resp):
            try:
                self.auth_fields["access_token"].setText(auth_mod.parse_token_response(resp.text)["access_token"])
                self.auth_type.setCurrentText("oauth2")
                self.status.setText("Jeton obtenu.")
            except ValueError as exc:
                self.status.setText(f"✗ {exc}")
        self.bg(work, done)

    # ------------------------------------------------------------------ environnements
    def refresh_env(self) -> None:
        data = self.store.environments(self.project)
        self.env_name.blockSignals(True)
        self.env_name.clear()
        self.env_name.addItems(sorted(data["items"]))
        self.env_name.setCurrentText(data.get("active", ""))
        self.env_name.blockSignals(False)
        self._env_show(self.env_name.currentText())

    def _env_show(self, name) -> None:
        items = self.store.environments(self.project)["items"].get(name, {})
        self.env_vars.set_items([{"key": k, "value": v} for k, v in items.items()])

    def env_save(self) -> None:
        name = self.env_name.currentText().strip()
        if not name:
            return
        data = self.store.environments(self.project)
        data["items"][name] = {i["key"]: i["value"] for i in self.env_vars.items() if i["key"]}
        data["active"] = name
        self.store.save_environments(self.project, data)
        self.refresh_env()

    def env_delete(self) -> None:
        data = self.store.environments(self.project)
        data["items"].pop(self.env_name.currentText(), None)
        data["active"] = ""
        self.store.save_environments(self.project, data)
        self.refresh_env()

    def clear_chain(self) -> None:
        self.chain.clear()
        self.jar.clear()
        self.chain_view.clear()

    # ------------------------------------------------------------------ import / export
    def import_file(self, path: str | None = None) -> str:
        path = path or QFileDialog.getOpenFileName(self, "Importer", "", "Collections (*.json *.yaml *.yml)")[0]
        if not path:
            return ""
        try:
            text = Path(path).read_text(encoding="utf-8")
            data = openapi.load_text(text)
            if "openapi" in data or "swagger" in data:
                col = openapi.import_spec(data)
            elif "info" in data and "item" in data:
                col = postman.import_postman(data)
            else:
                col = Collection.from_dict(data)
        except (OSError, ValueError, openapi.ImportError_) as exc:
            self.status.setText(f"✗ Import impossible : {exc}")
            return ""
        base, n = col.name, 2
        while any(c["name"] == col.name for c in self.cols):
            col.name, n = f"{base} ({n})", n + 1
        self.cols.append(col.to_dict())
        self._save_cols()
        self.refresh_tree()
        self.status.setText(f"Importé : {col.name} ({len(col.requests)} requêtes)")
        return col.name

    def export_file(self, path: str | None = None, fmt: str = "postman") -> str:
        if not self.cur:
            self.status.setText("Sélectionnez une collection.")
            return ""
        col = Collection.from_dict(self.cols[self.cur[0]])
        path = path or QFileDialog.getSaveFileName(self, "Exporter", f"{col.name}.json")[0]
        if not path:
            return ""
        data = postman.export_postman(col) if fmt == "postman" else col.to_dict()
        Path(path).write_text(postman.dumps(data), encoding="utf-8")
        self.status.setText(f"Exporté : {path}")
        return path

    # ------------------------------------------------------------------ historique
    def refresh_history(self) -> None:
        import time
        rows = self.store.history(self.project)
        self.hist.setRowCount(0)
        for h in rows:
            r = self.hist.rowCount()
            self.hist.insertRow(r)
            for c, v in enumerate([time.strftime("%H:%M:%S", time.localtime(h["time"])), f"{h['method']} {h['url']}", h["status"], h["ms"]]):
                self.hist.setItem(r, c, QTableWidgetItem(str(v)))

    # ------------------------------------------------------------------ WebSocket
    def ws_open(self) -> None:
        url = self.ws_url.text().strip()

        def work():
            c = WebSocketClient(url, verify_tls=self.verify_tls)
            c.connect()
            return c

        def done(c):
            self.ws = c
            self._ws_note(f"● connecté à {url}")
        self._guard(work, done)

    def _guard(self, work, done) -> None:
        def safe():
            try:
                return work()
            except (WebSocketError, OSError, ValueError) as exc:
                return exc

        def after(res):
            if isinstance(res, Exception):
                self._ws_note(f"✗ {res}")
            else:
                done(res)
        self.bg(safe, after)

    def ws_post(self) -> None:
        if self.ws and not self.ws.closed and self.ws_msg.text():
            try:
                self.ws.send_text(self.ws_msg.text())
                self._ws_note(f"→ {self.ws_msg.text()}")
                self.ws_msg.clear()
            except (WebSocketError, OSError) as exc:
                self._ws_note(f"✗ {exc}")

    def ws_shut(self) -> None:
        if self.ws:
            self.ws.close()
            self._ws_note("■ fermé")
            self.ws = None

    def _ws_note(self, line: str) -> None:
        self.ws_log.append(line)
        self.ws_view.setPlainText("\n".join(self.ws_log[-500:]))

    def _poll_ws(self) -> None:
        if self.ws and not self.ws.closed:
            try:
                self.ws.sock.setblocking(False)
                import select
                while select.select([self.ws.sock], [], [], 0)[0]:
                    self.ws.sock.settimeout(1)
                    kind, data = self.ws.recv(1)
                    self._ws_note(f"← {data}" if kind in ("text", "binary") else f"· {kind} {data}")
                    if kind == "close":
                        self.ws = None
                        break
            except (WebSocketError, OSError, ValueError):
                pass

    # ------------------------------------------------------------------ mock
    def mock_run(self) -> None:
        self.mock_halt()
        try:
            routes = json.loads(self.mock_edit.toPlainText())
            self.mock = mock_mod.MockServer(routes).start()
        except (ValueError, KeyError, OSError, TypeError) as exc:
            self.mock_label.setText(f"✗ {exc}")
            return
        self.mock_label.setText(f"Actif : {self.mock.url} (écho WebSocket : {self.mock.url.replace('http', 'ws')}/ws)")

    def mock_halt(self) -> None:
        if self.mock:
            self.mock.stop()
            self.mock = None
            self.mock_label.setText("Arrêté.")

    def refresh_mock_hits(self) -> None:
        if self.mock:
            self.mock_hits.setPlainText("\n".join(f"{h['method']} {h['path']} {h.get('body', '')[:80]}" for h in self.mock.hits[-100:]))

    def closeEvent(self, ev):  # noqa: N802
        self.mock_halt()
        self.ws_shut()
        super().closeEvent(ev)


