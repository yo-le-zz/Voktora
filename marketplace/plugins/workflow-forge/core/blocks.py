"""Catalogue de blocs : chacun décrit ses paramètres, ses ports de sortie, s'il a des effets de bord (ignoré en test à blanc) et son exécution."""

from __future__ import annotations

import http.client
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from . import expr as ex

REGISTRY: dict[str, Block] = {}


class BlockError(Exception):
    pass


@dataclass
class Param:
    name: str
    kind: str = "str"                 # str | text | int | bool | choice | code | expr | json
    default: object = ""
    choices: tuple = ()
    required: bool = False
    help: str = ""


@dataclass
class Block:
    type: str
    title: str
    category: str
    params: list = field(default_factory=list)
    ports: tuple = ("out",)
    side_effect: bool = False
    run: object = None
    doc: str = ""


def block(type_, title, category, params=(), ports=("out",), side_effect=False, doc=""):
    def deco(fn):
        REGISTRY[type_] = Block(type_, title, category, list(params), tuple(ports), side_effect, fn, doc)
        return fn
    return deco


class Ctx:
    """Contexte d'exécution passé aux blocs. Tous les accès réseau / processus passent par des fonctions injectables (tests, test à blanc)."""

    def __init__(self, project="", vars=None, trigger=None, cancel=None, log=None, runner=None, http=None, notify=None):   # noqa: A002
        import threading
        self.project, self.vars, self.trigger = project, dict(vars or {}), trigger or {}
        self.outputs: dict[str, dict] = {}
        self.cancel = cancel or threading.Event()
        self._log, self.runner, self.http, self._notify = log or (lambda m: None), runner, http, notify or (lambda m: None)
        self.lock = threading.RLock()
        self.node_id = ""
        self.item = None
        self.index = 0

    def names(self) -> dict:
        with self.lock:
            return {"vars": dict(self.vars), "out": {k: dict(v) for k, v in self.outputs.items()}, "trigger": dict(self.trigger),
                    "item": self.item, "index": self.index, "project": self.project, **{k: v for k, v in self.vars.items() if k.isidentifier()}}

    def log(self, msg: str) -> None:
        self._log(f"[{self.node_id}] {msg}")

    def eval(self, source: str):
        return ex.evaluate(source, self.names())

    def render(self, text):
        return ex.render(text, self.names())

    def path(self, rel: str) -> Path:
        base = Path(self.project or ".").resolve()
        p = (base / rel).resolve()
        if p != base and base not in p.parents:
            raise BlockError(f"Chemin hors du projet : {rel}")
        return p


# ------------------------------------------------------------------------------------------------- flux
@block("start", "Démarrage", "Flux", doc="Point d'entrée. Le déclencheur y dépose ses données dans `trigger`.")
def _start(ctx, p):
    return {"out": {"trigger": ctx.trigger}}


@block("end", "Fin", "Flux", ports=(), doc="Termine la branche en cours.")
def _end(ctx, p):
    return {"out": {}}


@block("fail", "Échec volontaire", "Flux", [Param("message", "str", "échec")], ports=(), doc="Arrête le workflow en erreur.")
def _fail(ctx, p):
    raise BlockError(str(p["message"]))


@block("if", "Condition", "Flux", [Param("condition", "expr", "vars.x > 0", required=True)], ports=("true", "false"))
def _if(ctx, p):
    r = bool(ctx.eval(p["condition"]))
    return {"out": {"result": r}, "port": "true" if r else "false"}


@block("loop_for", "Pour chaque", "Flux", [Param("items", "expr", "[1, 2, 3]", required=True), Param("max_items", "int", 1000)], ports=("body", "done"),
       doc="Exécute la branche « body » pour chaque élément (`item`, `index`), puis continue par « done ».")
def _loop_for(ctx, p):
    items = ctx.eval(p["items"])
    if isinstance(items, dict):
        items = list(items)
    if not isinstance(items, list):
        raise BlockError("« items » doit être une liste.")
    return {"out": {"count": len(items[:int(p['max_items'])])}, "loop": items[:int(p["max_items"])]}


@block("loop_while", "Tant que", "Flux", [Param("condition", "expr", "vars.n < 3", required=True), Param("max_iterations", "int", 100)], ports=("body", "done"))
def _loop_while(ctx, p):
    return {"out": {}, "while": p["condition"], "max": int(p["max_iterations"])}


@block("parallel", "Parallèle", "Flux", [Param("max_workers", "int", 4)], ports=("out",),
       doc="Lance toutes les branches sortantes en même temps ; elles se rejoignent sur un bloc « Joindre ».")
def _parallel(ctx, p):
    return {"out": {}, "fork": True, "workers": max(1, min(int(p["max_workers"]), 16))}


@block("join", "Joindre", "Flux", doc="Attend la fin de toutes les branches d'un bloc Parallèle.")
def _join(ctx, p):
    return {"out": {}}


@block("delay", "Attendre", "Flux", [Param("seconds", "int", 1)])
def _delay(ctx, p):
    end = time.monotonic() + min(float(p["seconds"]), 3600)
    while time.monotonic() < end:
        if ctx.cancel.is_set():
            raise BlockError("Annulé.")
        time.sleep(min(0.05, max(end - time.monotonic(), 0)))
    return {"out": {}}


@block("set_var", "Définir une variable", "Données", [Param("name", "str", "x", required=True), Param("value", "expr", "1", required=True)])
def _set_var(ctx, p):
    if not str(p["name"]).isidentifier():
        raise BlockError("Nom de variable invalide.")
    v = ctx.eval(p["value"])
    with ctx.lock:
        ctx.vars[p["name"]] = v
    return {"out": {"value": v}}


@block("transform", "Transformer (JSON)", "Données", [Param("expression", "expr", "upper(vars.name)", required=True)])
def _transform(ctx, p):
    return {"out": {"value": ctx.eval(p["expression"])}}


@block("log", "Journal", "Données", [Param("message", "str", "{{vars}}")])
def _log(ctx, p):
    ctx.log(str(p["message"]))
    return {"out": {}}


@block("notify", "Notification", "Données", [Param("message", "str", "Terminé")], side_effect=True)
def _notify(ctx, p):
    ctx._notify(str(p["message"]))
    return {"out": {}}


@block("parse_json", "Lire du JSON", "Données", [Param("text", "str", "{{out.http1.body}}", required=True)])
def _parse_json(ctx, p):
    try:
        return {"out": {"value": json.loads(p["text"]) if isinstance(p["text"], str) else p["text"]}}
    except ValueError as exc:
        raise BlockError(f"JSON invalide : {exc}") from exc


# ------------------------------------------------------------------------------------------------- système
def _run_args(ctx, args: list[str], cwd, timeout, env=None):
    if ctx.runner is None:
        raise BlockError("Exécution de processus indisponible.")
    res = ctx.runner(args, cwd=cwd, timeout=timeout, env=env, cancel=ctx.cancel, on_line=lambda ln: ctx.log("  " + ln))
    return {"code": res.code, "output": res.out, "ok": res.ok, "seconds": round(res.seconds, 3)}, res


@block("run_command", "Commande", "Système", [Param("command", "str", "echo bonjour", required=True), Param("cwd", "str", ""), Param("timeout", "int", 120),
                                              Param("fail_on_error", "bool", True)], ports=("out", "error"), side_effect=True,
       doc="Découpée avec shlex et lancée SANS shell (pas de pipes ni de redirections).")
def _run_command(ctx, p):
    try:
        args = shlex.split(str(p["command"]))
    except ValueError as exc:
        raise BlockError(f"Commande invalide : {exc}") from exc
    if not args:
        raise BlockError("Commande vide.")
    out, res = _run_args(ctx, args, str(ctx.path(p["cwd"])) if p.get("cwd") else ctx.project or None, float(p["timeout"]))
    if not res.ok:
        if p.get("fail_on_error", True):
            raise BlockError(f"Code {res.code} : {res.out.strip()[-200:] or res.error}")
        return {"out": out, "port": "error"}
    return {"out": out}


@block("read_file", "Lire un fichier", "Système", [Param("path", "str", "", required=True), Param("max_bytes", "int", 1000000)])
def _read_file(ctx, p):
    try:
        return {"out": {"text": ctx.path(p["path"]).read_text(encoding="utf-8", errors="replace")[:int(p["max_bytes"])]}}
    except OSError as exc:
        raise BlockError(str(exc)) from exc


@block("write_file", "Écrire un fichier", "Système", [Param("path", "str", "", required=True), Param("content", "text", ""), Param("append", "bool", False)],
       side_effect=True)
def _write_file(ctx, p):
    target = ctx.path(p["path"])
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a" if p.get("append") else "w", encoding="utf-8") as fh:
            fh.write(str(p["content"]))
    except OSError as exc:
        raise BlockError(str(exc)) from exc
    return {"out": {"path": str(target)}}


@block("file_exists", "Fichier existe ?", "Système", [Param("path", "str", "", required=True)], ports=("true", "false"))
def _file_exists(ctx, p):
    ok = ctx.path(p["path"]).exists()
    return {"out": {"exists": ok}, "port": "true" if ok else "false"}


@block("list_files", "Lister des fichiers", "Système", [Param("pattern", "str", "**/*.py"), Param("limit", "int", 500)])
def _list_files(ctx, p):
    base = ctx.path(".")
    files = [str(f.relative_to(base)) for f in base.glob(p["pattern"]) if f.is_file() and ".git" not in f.parts][:int(p["limit"])]
    return {"out": {"files": sorted(files), "count": len(files)}}


@block("env_var", "Variable d'environnement", "Système", [Param("name", "str", "HOME", required=True)])
def _env_var(ctx, p):
    return {"out": {"value": os.environ.get(p["name"], "")}}


# ------------------------------------------------------------------------------------------------- scripts
@block("python_script", "Script Python", "Scripts", [Param("code", "code", "result = 1 + 1", required=True), Param("timeout", "int", 30)], ports=("out", "error"),
       side_effect=True, doc="Processus Python isolé (`-I`). Lit `vars` ; affecte `result` (JSON) ; `print()` va au journal.")
def _python_script(ctx, p):
    with tempfile.TemporaryDirectory(prefix="vforge-") as tmp:
        f = Path(tmp) / "s.py"
        f.write_text("import json,sys\nvars=json.loads(sys.stdin.readline())\nresult=None\n" + str(p["code"]) +
                     "\nsys.stdout.write('\\n\\x00RES\\x00'+json.dumps(result,default=str))\n", encoding="utf-8")
        return _script(ctx, [sys.executable, "-I", str(f)], tmp, p)


@block("js_script", "Script JavaScript", "Scripts", [Param("code", "code", "result = 1 + 1", required=True), Param("timeout", "int", 30)], ports=("out", "error"),
       side_effect=True, doc="Node.js requis. `vars` en lecture ; affecter `result`.")
def _js_script(ctx, p):
    node = shutil.which("node")
    if not node:
        raise BlockError("Node.js est introuvable.")
    with tempfile.TemporaryDirectory(prefix="vforge-") as tmp:
        f = Path(tmp) / "s.js"
        f.write_text("let vars=JSON.parse(require('fs').readFileSync(0,'utf8').split('\\n')[0]);let result=null;\n" + str(p["code"]) +
                     "\nprocess.stdout.write('\\n\\u0000RES\\u0000'+JSON.stringify(result===undefined?null:result));\n", encoding="utf-8")
        return _script(ctx, [node, str(f)], tmp, p)


@block("rust_script", "Script Rust", "Scripts", [Param("code", "code", 'fn main() { println!("bonjour"); }', required=True), Param("timeout", "int", 120)],
       ports=("out", "error"), side_effect=True, doc="Compile avec `rustc` (requis) puis exécute ; la sortie standard est capturée.")
def _rust_script(ctx, p):
    rustc = shutil.which("rustc")
    if not rustc:
        raise BlockError("rustc est introuvable : installez Rust pour utiliser ce bloc.")
    with tempfile.TemporaryDirectory(prefix="vforge-") as tmp:
        src, exe = Path(tmp) / "m.rs", Path(tmp) / "m"
        src.write_text(str(p["code"]), encoding="utf-8")
        out, res = _run_args(ctx, [rustc, "--edition", "2021", "-O", str(src), "-o", str(exe)], tmp, float(p["timeout"]))
        if not res.ok:
            raise BlockError("Compilation échouée : " + res.out.strip()[-300:])
        out, res = _run_args(ctx, [str(exe)], tmp, float(p["timeout"]))
        return {"out": out, **({} if res.ok else {"port": "error"})}


def _script(ctx, cmd, tmp, p):
    if ctx.runner is None:
        raise BlockError("Exécution de processus indisponible.")
    import subprocess
    try:
        done = subprocess.run(cmd, input=json.dumps(ctx.names()["vars"], default=str) + "\n", capture_output=True, text=True, cwd=tmp,   # noqa: S603
                              timeout=float(p["timeout"]), env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"}, encoding="utf-8", errors="replace", check=False)
    except subprocess.TimeoutExpired as exc:
        raise BlockError(f"Script interrompu : délai de {p['timeout']} s dépassé.") from exc
    out = done.stdout or ""
    text, _, res = out.partition("\x00RES\x00")
    for line in text.splitlines():
        ctx.log("  " + line)
    result = None
    if res:
        try:
            result = json.loads(res)
        except ValueError:
            result = res
    if done.returncode != 0:
        raise BlockError((done.stderr or "").strip()[-300:] or f"Code {done.returncode}")
    return {"out": {"result": result, "output": text.strip()}}


# ------------------------------------------------------------------------------------------------- HTTP
@block("http_request", "Requête HTTP", "Réseau", [Param("method", "choice", "GET", ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")), Param("url", "str", "", required=True),
                                                  Param("headers", "json", "{}"), Param("body", "text", ""), Param("timeout", "int", 30),
                                                  Param("fail_on_http_error", "bool", False)], ports=("out", "error"), side_effect=True)
def _http_request(ctx, p):
    try:
        headers = json.loads(p["headers"]) if isinstance(p["headers"], str) and p["headers"].strip() else dict(p["headers"] or {})
    except ValueError as exc:
        raise BlockError(f"En-têtes JSON invalides : {exc}") from exc
    fn = ctx.http or default_http
    try:
        status, hdrs, body = fn(p["method"], p["url"], headers, str(p["body"]).encode() if p["body"] else None, float(p["timeout"]))
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise BlockError(f"Requête impossible : {exc}") from exc
    text = body.decode("utf-8", "replace")
    out = {"status": status, "body": text, "headers": dict(hdrs), "ok": 200 <= status < 400}
    try:
        out["json"] = json.loads(text)
    except ValueError:
        out["json"] = None
    if not out["ok"]:
        if p.get("fail_on_http_error"):
            raise BlockError(f"HTTP {status}")
        return {"out": out, "port": "error"}
    return {"out": out}


def default_http(method, url, headers, body, timeout):
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Adresse invalide : http:// ou https:// attendu.")
    cls = http.client.HTTPSConnection if p.scheme == "https" else http.client.HTTPConnection
    conn = cls(p.hostname, p.port, timeout=timeout)
    try:
        conn.request(method, (p.path or "/") + (("?" + p.query) if p.query else ""), body=body, headers=headers)
        r = conn.getresponse()
        return r.status, r.getheaders(), r.read(5_000_000)
    finally:
        conn.close()


# ------------------------------------------------------------------------------------------------- projet
def _git(ctx, *args, timeout=60):
    out, res = _run_args(ctx, ["git", *args], ctx.project or None, timeout)
    if not res.ok:
        raise BlockError(f"git {args[0]} : {res.out.strip()[-200:] or res.error}")
    return out["output"].strip()


@block("git_status", "Git : statut", "Projet")
def _git_status(ctx, p):
    out = _git(ctx, "status", "--porcelain=v1", "-b")
    lines = out.splitlines()
    return {"out": {"branch": lines[0][3:].split("...")[0] if lines else "", "changes": len(lines) - 1, "clean": len(lines) <= 1, "raw": out}}


@block("git_head", "Git : commit courant", "Projet")
def _git_head(ctx, p):
    return {"out": {"sha": _git(ctx, "rev-parse", "HEAD")}}


@block("git_pull", "Git : pull (fast-forward)", "Projet", side_effect=True, doc="Jamais de push dans ce plugin.")
def _git_pull(ctx, p):
    return {"out": {"output": _git(ctx, "pull", "--ff-only", timeout=180)}}


@block("project_search", "Chercher dans le projet", "Projet", [Param("pattern", "str", "TODO", required=True), Param("glob", "str", "**/*"), Param("limit", "int", 100)])
def _project_search(ctx, p):
    try:
        rx = re.compile(str(p["pattern"]))
    except re.error as exc:
        raise BlockError(f"Motif invalide : {exc}") from exc
    base, hits = ctx.path("."), []
    for f in base.glob(p["glob"]):
        if not f.is_file() or any(x in f.parts for x in (".git", "node_modules", ".venv", "__pycache__", "target")) or f.stat().st_size > 1_000_000:
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
                if rx.search(line):
                    hits.append({"file": str(f.relative_to(base)), "line": i, "text": line.strip()[:200]})
                    if len(hits) >= int(p["limit"]):
                        return {"out": {"matches": hits, "count": len(hits)}}
        except (OSError, UnicodeDecodeError):
            continue
    return {"out": {"matches": hits, "count": len(hits)}}


@block("project_command", "Commande du projet", "Projet", [Param("command", "str", "python -m pytest -q", required=True), Param("timeout", "int", 600)],
       ports=("out", "error"), side_effect=True)
def _project_command(ctx, p):
    return _run_command(ctx, {"command": p["command"], "cwd": "", "timeout": p["timeout"], "fail_on_error": False})


def catalog() -> list[dict]:
    return [{"type": b.type, "title": b.title, "category": b.category, "ports": list(b.ports), "side_effect": b.side_effect, "doc": b.doc,
             "params": [{"name": q.name, "kind": q.kind, "default": q.default, "choices": list(q.choices), "required": q.required} for q in b.params]}
            for b in REGISTRY.values()]


def defaults(type_: str) -> dict:
    return {q.name: q.default for q in REGISTRY[type_].params}
