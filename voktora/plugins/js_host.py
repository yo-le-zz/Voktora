"""
Voktora — plugins.js_host (1.1.1)
Plugins écrits en JAVASCRIPT : `plugin.json` avec `"lang": "js"` et `"entry": "main.js"`.

Aucun code de liaison à écrire : le script s'exécute au chargement avec un objet global `voktora` qui offre TOUTE l'API
de plugins (mêmes noms qu'en Python, en camelCase) :

    voktora.notify("Bonjour");
    voktora.addMenuAction("Outils", "Dire bonjour", () => voktora.message("Salut", "Depuis JavaScript !"));
    voktora.options.addBool("gras", "Titres en gras", true);
    voktora.on("on_open", ctx => voktora.log("ouvert : " + ctx.projectPath));
    const outils = require("./outils.js");          // plusieurs fichiers : CommonJS (module.exports, JSON)
    function onUnload() { /* nettoyage facultatif */ }

ISOLATION : chaque plugin JavaScript tourne dans son PROPRE PROCESSUS (moteur QJSEngine de Qt, voir js_worker.py). Le
script n'a ni fichiers, ni réseau, ni processus, ni `fetch` : il ne peut faire que ce que l'API lui permet, avec les
permissions déclarées (vérifiées ici, côté application). Une boucle infinie ou un plantage ne touche pas Voktora :
le processus est tué après JS_TIMEOUT secondes sans réponse (le temps passé dans l'API — boîtes de dialogue, réseau —
n'est pas compté).

Types : arguments et retours passent en JSON ; les fonctions passées à l'API sont rappelées plus tard. Les objets Qt
(QAction, QWidget) ne traversent pas : les méthodes qui en retournent renvoient `undefined`. Pour une interface
graphique riche (widgets), écrivez ce plugin en Python.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import bridge

JS_TIMEOUT = 5.0
LOAD_TIMEOUT = 20.0                                   # démarrage du processus + exécution du script
WORKER_FILE = Path(__file__).with_name("js_worker.py")


def worker_command() -> tuple[list[str], dict[str, str]]:
    """Commande et environnement du processus de travail (même exécutable que l'application)."""
    keep = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "LD_LIBRARY_PATH", "VIRTUAL_ENV", "PYTHONPATH", "TMPDIR", "TEMP",
            "TMP", "SYSTEMROOT", "WINDIR", "LOCALAPPDATA", "XDG_RUNTIME_DIR"}
    # Environnement MINIMAL : le script JavaScript ne doit hériter d'aucun secret (jetons, proxys…) de l'application.
    env = {k: v for k, v in os.environ.items() if k in keep}
    env.update({"VOKTORA_JS_WORKER": "1", "QT_QPA_PLATFORM": "offscreen"})
    frozen = bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()
    return ([sys.executable] if frozen else [sys.executable, str(WORKER_FILE)]), env


class JsHost:
    def __init__(self, info: Any, api: Any) -> None:
        self.info, self.api = info, api
        self._bridge = bridge.ApiBridge(api, self._callback)
        self.root = Path(info.path).resolve()
        self._lock = threading.RLock()
        self._inbox: queue.Queue[dict] = queue.Queue()
        command, env = worker_command()
        self._proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,   # noqa: S603
                                      env=env, text=True, encoding="utf-8", bufsize=1)
        threading.Thread(target=self._read, daemon=True, name=f"js-{info.id}-out").start()
        threading.Thread(target=self._read_err, daemon=True, name=f"js-{info.id}-err").start()

    # -- canal avec le processus ------------------------------------------------------------------
    def _read(self) -> None:
        for line in self._proc.stdout:
            with contextlib.suppress(ValueError):
                self._inbox.put(json.loads(line))
        self._inbox.put({"t": "eof"})

    def _read_err(self) -> None:
        for line in self._proc.stderr:
            self.info.note_log("js", line.rstrip()[:300])

    def _send(self, message: dict) -> None:
        try:
            self._proc.stdin.write(json.dumps(message) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise RuntimeError("Le moteur JavaScript s'est arrêté.") from exc

    def _rpc(self, message: dict, timeout: float) -> str:
        """Envoie une requête puis sert les appels d'API du script jusqu'à la réponse. Ré-entrant."""
        with self._lock:
            self._send(message)
            deadline = time.monotonic() + timeout
            while True:
                try:
                    reply = self._inbox.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty:
                    self.kill()
                    raise RuntimeError(f"Le script JavaScript ne répond plus (> {timeout:g} s) : plugin arrêté.") from None
                kind = reply.get("t")
                if kind == "call":
                    self._send({"t": "reply", "value": self.dispatch(reply["name"], reply["args"])})
                    deadline = time.monotonic() + timeout          # le temps passé dans l'API n'est pas compté
                elif kind == "ret":
                    if not reply.get("ok"):
                        raise RuntimeError(reply.get("error") or "Erreur JavaScript.")
                    return reply.get("value", "")
                elif kind == "eof":
                    raise RuntimeError("Le moteur JavaScript s'est arrêté de façon inattendue.")

    # -- appels JS → Python -----------------------------------------------------------------------------
    def dispatch(self, name: str, args_json: str) -> str:
        try:
            return self._bridge.dispatch(name, json.loads(args_json))
        except ValueError as exc:
            return json.dumps({"__error": f"Arguments illisibles : {exc}"})

    def _callback(self, fn_id: int) -> Callable[..., Any]:
        def call(*args: Any) -> Any:
            payload = json.dumps([bridge.context_to_dict(a) if hasattr(a, "project_path") else a for a in args],
                                 default=bridge.json_default)
            text = self._rpc({"t": "invoke", "id": fn_id, "payload": payload}, JS_TIMEOUT)
            return json.loads(text) if text else None
        return call

    # -- cycle de vie --------------------------------------------------------------------------------------
    def start(self, entry: str) -> None:
        try:
            self._rpc({"t": "load", "root": str(self.root), "entry": entry}, LOAD_TIMEOUT)
        except Exception:
            self.kill()
            raise

    def kill(self) -> None:
        with contextlib.suppress(Exception):
            self._proc.kill()
        for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
            with contextlib.suppress(Exception):
                stream.close()

    def unload(self) -> None:
        with contextlib.suppress(Exception):
            if self._proc.poll() is None:
                self._rpc({"t": "unload"}, 2.0)
        self.kill()
        with contextlib.suppress(Exception):
            self._proc.wait(timeout=2)


def load(info: Any, api: Any) -> None:
    """Appelé par runtime._load_into pour un plugin « js »."""
    from . import manifest
    host = JsHost(info, api)
    info.teardown.append(host.unload)
    host.start(manifest.load(Path(info.path)).entry)
