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


KINDS = ("str", "text", "code", "int", "number", "duration", "bool", "choice", "path", "var", "expr", "json", "pairs")


@dataclass
class Param:
    """Schéma d'un paramètre (typé). Les anciens champs (name, kind, default, choices, required, help) gardent leur sens ; les autres sont facultatifs.

    kind : str (texte court) | text (multiligne) | code | int | number (décimal) | duration (secondes) | bool | choice (menu) | path (fichier/dossier,
    `mode` = file | dir | save) | var (variable, liste déroulante éditable) | expr (expression) | json | pairs (liste clé/valeur, stockée en JSON).
    """
    name: str
    kind: str = "str"
    default: object = ""
    choices: tuple = ()
    required: bool = False
    help: str = ""
    label: str = ""                   # libellé français (défaut : le nom technique)
    choice_labels: tuple = ()         # libellés des choix, dans le même ordre que `choices`
    minimum: float | None = None
    maximum: float | None = None
    step: float = 1
    unit: str = ""
    placeholder: str = ""
    example: str = ""
    mode: str = ""                    # path : file | dir | save ; code : langage
    essential: bool = False           # affiché dans la boîte d'édition rapide (double-clic)
    templated: bool = True            # accepte {{ … }} (sinon valeur brute)


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
    summary: str = ""                 # modèle de résumé affiché dans le bloc : « HTTP {method} {url} »
    example: str = ""
    outputs: tuple = ()               # champs déposés dans out.<bloc>.<champ>


def block(type_, title, category, params=(), ports=("out",), side_effect=False, doc="", summary="", example="", outputs=()):
    def deco(fn):
        REGISTRY[type_] = Block(type_, title, category, list(params), tuple(ports), side_effect, fn, doc, summary, example, tuple(outputs))
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
@block("start", "Démarrage", "Flux", doc="Point d'entrée. Le déclencheur y dépose ses données dans `trigger`.", summary="Point d'entrée du workflow",
       example="Reliez-le au premier bloc à exécuter.", outputs=("trigger",))
def _start(ctx, p):
    return {"out": {"trigger": ctx.trigger}}


@block("end", "Fin", "Flux", ports=(), doc="Termine la branche en cours.", summary="Fin de la branche", example="Placez-le au bout d'une branche de condition.")
def _end(ctx, p):
    return {"out": {}}


@block("fail", "Échec volontaire", "Flux",
       [Param("message", "str", "échec", label="Message d'erreur", help="Texte affiché dans le journal quand le workflow s'arrête.", essential=True, placeholder="Ex. : les tests ont échoué")],
       ports=(), doc="Arrête le workflow en erreur.", summary="Échec : {message}", example="Message : Les tests ont échoué ({{out.tests.code}})")
def _fail(ctx, p):
    raise BlockError(str(p["message"]))


@block("if", "Condition", "Flux",
       [Param("condition", "expr", "vars.x > 0", required=True, label="Condition", essential=True, placeholder="vars.x > 0",
              help="Expression vraie ou fausse. Le port « true » est suivi si elle est vraie, sinon « false ».", example="out.tests.ok and vars.count >= 3")],
       ports=("true", "false"), doc="Choisit une branche selon une expression.", summary="Si {condition}", example="Condition : out.http1.status == 200", outputs=("result",))
def _if(ctx, p):
    r = bool(ctx.eval(p["condition"]))
    return {"out": {"result": r}, "port": "true" if r else "false"}


@block("loop_for", "Pour chaque", "Flux",
       [Param("items", "expr", "[1, 2, 3]", required=True, label="Liste à parcourir", essential=True, help="Expression qui donne une liste (ou un dictionnaire : on parcourt les clés).",
              example="out.list.files"),
        Param("max_items", "int", 1000, label="Nombre maximal d'éléments", minimum=1, maximum=100000, help="Les éléments au-delà sont ignorés.")],
       ports=("body", "done"), summary="Pour chaque élément de {items}", example="Liste : out.search.matches ; dans « body », utilisez item et index.", outputs=("count",),
       doc="Exécute la branche « body » pour chaque élément (`item`, `index`), puis continue par « done ».")
def _loop_for(ctx, p):
    items = ctx.eval(p["items"])
    if isinstance(items, dict):
        items = list(items)
    if not isinstance(items, list):
        raise BlockError("« items » doit être une liste.")
    return {"out": {"count": len(items[:int(p['max_items'])])}, "loop": items[:int(p["max_items"])]}


@block("loop_while", "Tant que", "Flux",
       [Param("condition", "expr", "vars.n < 3", required=True, label="Condition de poursuite", essential=True, help="La branche « body » se répète tant que l'expression est vraie."),
        Param("max_iterations", "int", 100, label="Itérations maximales", minimum=1, maximum=100000, help="Garde-fou contre les boucles infinies.")],
       ports=("body", "done"), doc="Répète la branche « body » tant que la condition est vraie (borné).", summary="Tant que {condition} (max {max_iterations})",
       example="Condition : vars.n < 5 ; incrémentez n dans la branche « body ».")
def _loop_while(ctx, p):
    return {"out": {}, "while": p["condition"], "max": int(p["max_iterations"])}


@block("parallel", "Parallèle", "Flux", [Param("max_workers", "int", 4, label="Branches simultanées (max)", minimum=1, maximum=16, essential=True)], ports=("out",),
       summary="Jusqu'à {max_workers} branches en même temps", example="Reliez 2 à 4 blocs au port de sortie, puis rejoignez-les sur « Joindre ».",
       doc="Lance toutes les branches sortantes en même temps ; elles se rejoignent sur un bloc « Joindre ».")
def _parallel(ctx, p):
    return {"out": {}, "fork": True, "workers": max(1, min(int(p["max_workers"]), 16))}


@block("join", "Joindre", "Flux", doc="Attend la fin de toutes les branches d'un bloc Parallèle.", summary="Attend toutes les branches", example="Un seul bloc « Joindre » par bloc « Parallèle ».")
def _join(ctx, p):
    return {"out": {}}


@block("delay", "Attendre", "Flux",
       [Param("seconds", "duration", 1, label="Durée", minimum=0, maximum=3600, step=0.5, unit="s", essential=True, help="Pause en secondes (3600 s maximum).")],
       doc="Met le workflow en pause.", summary="Attendre {seconds} s", example="Durée : 2,5 s")
def _delay(ctx, p):
    end = time.monotonic() + min(float(p["seconds"]), 3600)
    while time.monotonic() < end:
        if ctx.cancel.is_set():
            raise BlockError("Annulé.")
        time.sleep(min(0.05, max(end - time.monotonic(), 0)))
    return {"out": {}}


@block("set_var", "Définir une variable", "Données",
       [Param("name", "var", "x", required=True, label="Nom de la variable", essential=True, help="Lettres, chiffres et _ ; ne commence pas par un chiffre. Choisissez une variable existante ou tapez un nouveau nom.",
              templated=False),
        Param("value", "expr", "1", required=True, label="Valeur (expression)", essential=True, placeholder="1, 'texte', vars.a + 1, out.bloc.champ",
              help="Expression évaluée ; pour un texte fixe, mettez des guillemets : 'bonjour'.", example="vars.total + 1")],
       doc="Calcule une valeur et la range dans vars.<nom>.", summary="{name} = {value}", example="Nom : compteur ; Valeur : vars.compteur + 1", outputs=("value",))
def _set_var(ctx, p):
    if not str(p["name"]).isidentifier():
        raise BlockError("Nom de variable invalide.")
    v = ctx.eval(p["value"])
    with ctx.lock:
        ctx.vars[p["name"]] = v
    return {"out": {"value": v}}


@block("transform", "Transformer (JSON)", "Données",
       [Param("expression", "expr", "upper(vars.name)", required=True, label="Expression", essential=True, help="Calcule une nouvelle valeur disponible dans out.<bloc>.value.",
              example="[x for ...] n'est pas permis ; utilisez get(out.http1.json, 'items', [])")],
       doc="Calcule une valeur à partir des variables et des sorties précédentes.", summary="Transformer : {expression}", example="join(', ', out.list.files)", outputs=("value",))
def _transform(ctx, p):
    return {"out": {"value": ctx.eval(p["expression"])}}


@block("log", "Journal", "Données",
       [Param("message", "text", "{{vars}}", label="Message", essential=True, help="Texte écrit dans le journal ; {{ … }} insère une valeur.", example="Fichiers trouvés : {{out.list.count}}"),
        Param("level", "choice", "info", ("info", "warning", "error"), label="Niveau", choice_labels=("Information", "Avertissement", "Erreur"), help="Préfixe ajouté au message.")],
       doc="Écrit un message dans le journal d'exécution.", summary="Journal : {message}", example="Message : Version {{vars.version}} prête")
def _log(ctx, p):
    prefix = {"warning": "⚠ ", "error": "✗ "}.get(str(p.get("level", "info")), "")
    ctx.log(prefix + str(p["message"]))
    return {"out": {}}


@block("notify", "Notification", "Données",
       [Param("message", "str", "Terminé", label="Message", essential=True, placeholder="Ex. : Sauvegarde terminée", help="Texte de la notification Voktora.", example="Tests : {{out.tests.ok}}")],
       side_effect=True, doc="Affiche une notification dans Voktora (ignorée en test à blanc).", summary="Notifier : {message}", example="Message : Déploiement terminé")
def _notify(ctx, p):
    ctx._notify(str(p["message"]))
    return {"out": {}}


@block("parse_json", "Lire du JSON", "Données",
       [Param("text", "text", "{{out.http1.body}}", required=True, label="Texte JSON", essential=True, help="Texte à analyser ; généralement la réponse d'un bloc précédent.",
              example="{{out.http1.body}}")],
       doc="Transforme un texte JSON en valeur utilisable (out.<bloc>.value).", summary="Lire le JSON de {text}", example="Texte : {{out.http1.body}}", outputs=("value",))
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


def _env_from(raw) -> dict:
    """Variables d'environnement saisies (JSON {nom: valeur} ou dict) -> dict de chaînes ; lève BlockError si invalide."""
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise BlockError(f"Variables d'environnement invalides : {exc}") from exc
    else:
        return {}
    if not isinstance(data, dict):
        raise BlockError("Variables d'environnement : un objet {nom: valeur} est attendu.")
    return {str(k): str(v) for k, v in data.items() if str(k).strip()}


@block("run_command", "Commande", "Système",
       [Param("command", "str", "echo bonjour", required=True, label="Commande", essential=True, placeholder="python -m pytest -q",
              help="Découpée avec shlex, lancée sans shell (pas de |, >, &&).", example="git status --short"),
        Param("cwd", "path", "", label="Dossier de travail", mode="dir", help="Relatif au projet ; vide = racine du projet."),
        Param("timeout", "duration", 120, label="Délai maximal", minimum=1, maximum=86400, unit="s", step=5, help="La commande est tuée au-delà."),
        Param("fail_on_error", "bool", True, label="Échouer si le code de sortie n'est pas 0", help="Sinon, le port « error » est suivi."),
        Param("env", "pairs", "{}", label="Variables d'environnement", help="Ajoutées à l'environnement de la commande.", templated=True, example="CI = 1")],
       ports=("out", "error"), side_effect=True, summary="$ {command}", example="Commande : python -m pytest -q", outputs=("code", "output", "ok", "seconds"),
       doc="Découpée avec shlex et lancée SANS shell (pas de pipes ni de redirections).")
def _run_command(ctx, p):
    try:
        args = shlex.split(str(p["command"]))
    except ValueError as exc:
        raise BlockError(f"Commande invalide : {exc}") from exc
    if not args:
        raise BlockError("Commande vide.")
    env = _env_from(p.get("env"))
    out, res = _run_args(ctx, args, str(ctx.path(p["cwd"])) if p.get("cwd") else ctx.project or None, float(p["timeout"]), env or None)
    if not res.ok:
        if p.get("fail_on_error", True):
            raise BlockError(f"Code {res.code} : {res.out.strip()[-200:] or res.error}")
        return {"out": out, "port": "error"}
    return {"out": out}


@block("read_file", "Lire un fichier", "Système",
       [Param("path", "path", "", required=True, label="Fichier", mode="file", essential=True, help="Chemin relatif au projet.", placeholder="README.md"),
        Param("max_bytes", "int", 1000000, label="Taille maximale", minimum=1, maximum=50_000_000, step=1000, unit="octets"),
        Param("encoding", "choice", "utf-8", ("utf-8", "latin-1", "utf-16", "ascii"), label="Encodage", help="Les caractères illisibles sont remplacés.")],
       doc="Lit un fichier texte du projet.", summary="Lire {path}", example="Fichier : package.json", outputs=("text",))
def _read_file(ctx, p):
    try:
        return {"out": {"text": ctx.path(p["path"]).read_text(encoding=str(p.get("encoding") or "utf-8"), errors="replace")[:int(p["max_bytes"])]}}
    except (OSError, LookupError) as exc:
        raise BlockError(str(exc)) from exc


@block("write_file", "Écrire un fichier", "Système",
       [Param("path", "path", "", required=True, label="Fichier", mode="save", essential=True, help="Chemin relatif au projet ; les dossiers manquants sont créés.", placeholder="build/notes.txt"),
        Param("content", "text", "", label="Contenu", essential=True, example="Version {{vars.version}}"),
        Param("mode", "choice", "w", ("w", "a", "x"), label="Mode d'ouverture", choice_labels=("Écraser le fichier", "Ajouter à la fin", "Créer (échoue s'il existe)"),
              essential=True, help="Comment ouvrir le fichier s'il existe déjà.")],
       side_effect=True, doc="Écrit du texte dans un fichier du projet (ignoré en test à blanc).", summary="Écrire {path} ({mode})", example="Fichier : logs/run.txt ; Mode : Ajouter à la fin",
       outputs=("path",))
def _write_file(ctx, p):
    target = ctx.path(p["path"])
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = str(p.get("mode") or ("a" if p.get("append") else "w"))
        if mode not in ("w", "a", "x"):
            raise BlockError(f"Mode d'ouverture inconnu : {mode}")
        with open(target, mode, encoding="utf-8") as fh:
            fh.write(str(p["content"]))
    except OSError as exc:
        raise BlockError(str(exc)) from exc
    return {"out": {"path": str(target)}}


@block("file_exists", "Fichier existe ?", "Système",
       [Param("path", "path", "", required=True, label="Fichier ou dossier", mode="file", essential=True, placeholder="pyproject.toml", help="Chemin relatif au projet.")],
       ports=("true", "false"), doc="Teste l'existence d'un fichier ou d'un dossier.", summary="{path} existe ?", example="Fichier : .env", outputs=("exists",))
def _file_exists(ctx, p):
    ok = ctx.path(p["path"]).exists()
    return {"out": {"exists": ok}, "port": "true" if ok else "false"}


@block("list_files", "Lister des fichiers", "Système",
       [Param("pattern", "str", "**/*.py", label="Motif (glob)", essential=True, help="Ex. : *.md (dossier racine), **/*.py (tous les sous-dossiers).", placeholder="**/*.py"),
        Param("limit", "int", 500, label="Nombre maximal", minimum=1, maximum=100000, step=50)],
       doc="Liste les fichiers du projet correspondant à un motif.", summary="Lister {pattern}", example="Motif : src/**/*.ts", outputs=("files", "count"))
def _list_files(ctx, p):
    base = ctx.path(".")
    files = [str(f.relative_to(base)) for f in base.glob(p["pattern"]) if f.is_file() and ".git" not in f.parts][:int(p["limit"])]
    return {"out": {"files": sorted(files), "count": len(files)}}


@block("env_var", "Variable d'environnement", "Système",
       [Param("name", "str", "HOME", required=True, label="Nom", essential=True, placeholder="HOME", templated=False, help="Nom de la variable d'environnement du système."),
        Param("fallback", "str", "", label="Valeur par défaut", help="Utilisée si la variable n'existe pas.")],
       doc="Lit une variable d'environnement du système.", summary="Variable d'environnement {name}", example="Nom : USER", outputs=("value",))
def _env_var(ctx, p):
    return {"out": {"value": os.environ.get(p["name"], str(p.get("fallback", "")))}}


# ------------------------------------------------------------------------------------------------- scripts
@block("python_script", "Script Python", "Scripts",
       [Param("code", "code", "result = 1 + 1", required=True, label="Code Python", mode="python", essential=True, help="`vars` en lecture ; affectez `result` (JSON).", example="result = len(vars['items'])"),
        Param("timeout", "duration", 30, label="Délai maximal", minimum=1, maximum=3600, unit="s", step=5)], ports=("out", "error"),
       summary="Python : {code}", example="result = sum(vars['nombres'])", outputs=("result", "output"),
       side_effect=True, doc="Processus Python isolé (`-I`). Lit `vars` ; affecte `result` (JSON) ; `print()` va au journal.")
def _python_script(ctx, p):
    with tempfile.TemporaryDirectory(prefix="vforge-") as tmp:
        f = Path(tmp) / "s.py"
        f.write_text("import json,sys\nvars=json.loads(sys.stdin.readline())\nresult=None\n" + str(p["code"]) +
                     "\nsys.stdout.write('\\n\\x00RES\\x00'+json.dumps(result,default=str))\n", encoding="utf-8")
        return _script(ctx, [sys.executable, "-I", str(f)], tmp, p)


@block("js_script", "Script JavaScript", "Scripts",
       [Param("code", "code", "result = 1 + 1", required=True, label="Code JavaScript", mode="javascript", essential=True, help="`vars` en lecture ; affectez `result`.", example="result = vars.items.length"),
        Param("timeout", "duration", 30, label="Délai maximal", minimum=1, maximum=3600, unit="s", step=5)], ports=("out", "error"),
       summary="JavaScript : {code}", example="result = vars.nom.toUpperCase()", outputs=("result", "output"),
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


@block("rust_script", "Script Rust", "Scripts",
       [Param("code", "code", 'fn main() { println!("bonjour"); }', required=True, label="Code Rust", mode="rust", essential=True, help="Programme complet avec `fn main()`."),
        Param("timeout", "duration", 120, label="Délai maximal", minimum=1, maximum=3600, unit="s", step=5)],
       ports=("out", "error"), side_effect=True, summary="Rust : {code}", example='fn main() { println!("{}", 6 * 7); }', outputs=("code", "output", "ok", "seconds"), doc="Compile avec `rustc` (requis) puis exécute ; la sortie standard est capturée.")
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
@block("http_request", "Requête HTTP", "Réseau",
       [Param("method", "choice", "GET", ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"), label="Méthode", essential=True, help="Verbe HTTP.",
              choice_labels=("GET (lire)", "POST (envoyer)", "PUT (remplacer)", "PATCH (modifier)", "DELETE (supprimer)", "HEAD (en-têtes seuls)")),
        Param("url", "str", "", required=True, label="Adresse (URL)", essential=True, placeholder="https://api.exemple.fr/items", help="http:// ou https:// ; {{ … }} permis.",
              example="https://api.github.com/repos/{{vars.repo}}"),
        Param("headers", "pairs", "{}", label="En-têtes", help="Un en-tête par ligne : nom et valeur.", example="Authorization = Bearer {{vars.token}}"),
        Param("content_type", "choice", "", ("", "application/json", "text/plain", "application/x-www-form-urlencoded"), label="Type du corps",
              choice_labels=("(ne pas préciser)", "JSON", "Texte brut", "Formulaire"), help="Ajoute l'en-tête Content-Type s'il n'est pas déjà défini."),
        Param("body", "text", "", label="Corps de la requête", help="Envoyé tel quel (POST, PUT, PATCH).", example='{"nom": "{{vars.nom}}"}'),
        Param("timeout", "duration", 30, label="Délai maximal", minimum=1, maximum=3600, unit="s", step=5),
        Param("fail_on_http_error", "bool", False, label="Échouer sur un code HTTP ≥ 400", help="Sinon, le port « error » est suivi.")],
       ports=("out", "error"), side_effect=True, doc="Envoie une requête HTTP ; la réponse est dans out.<bloc>.status / body / json / headers.",
       summary="HTTP {method} {url}", example="GET https://api.github.com/repos/yo-le-zz/Voktora → out.<bloc>.json.stargazers_count", outputs=("status", "body", "json", "headers", "ok"))
def _http_request(ctx, p):
    try:
        headers = json.loads(p["headers"]) if isinstance(p["headers"], str) and p["headers"].strip() else dict(p["headers"] or {})
    except (ValueError, TypeError) as exc:
        raise BlockError(f"En-têtes JSON invalides : {exc}") from exc
    ctype = str(p.get("content_type") or "")
    if ctype and not any(str(k).lower() == "content-type" for k in headers):
        headers["Content-Type"] = ctype
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


@block("git_status", "Git : statut", "Projet", doc="Lit l'état du dépôt (branche, modifications).", summary="Statut Git du projet", example="Condition ensuite : out.git1.clean", outputs=("branch", "changes", "clean", "raw"))
def _git_status(ctx, p):
    out = _git(ctx, "status", "--porcelain=v1", "-b")
    lines = out.splitlines()
    return {"out": {"branch": lines[0][3:].split("...")[0] if lines else "", "changes": len(lines) - 1, "clean": len(lines) <= 1, "raw": out}}


@block("git_head", "Git : commit courant", "Projet", doc="Lit l'identifiant du commit courant.", summary="Commit courant (HEAD)", example="Journal : HEAD = {{out.head.sha}}", outputs=("sha",))
def _git_head(ctx, p):
    return {"out": {"sha": _git(ctx, "rev-parse", "HEAD")}}


@block("git_pull", "Git : pull (fast-forward)", "Projet", side_effect=True, doc="Jamais de push dans ce plugin.", summary="git pull --ff-only", example="À placer avant les tests.", outputs=("output",))
def _git_pull(ctx, p):
    return {"out": {"output": _git(ctx, "pull", "--ff-only", timeout=180)}}


@block("project_search", "Chercher dans le projet", "Projet",
       [Param("pattern", "str", "TODO", required=True, label="Expression régulière", essential=True, placeholder="TODO|FIXME", help="Syntaxe regex Python, appliquée ligne par ligne.", templated=False),
        Param("glob", "str", "**/*", label="Fichiers concernés (glob)", essential=True, placeholder="**/*.py"),
        Param("limit", "int", 100, label="Nombre maximal de résultats", minimum=1, maximum=10000, step=10)],
       doc="Cherche un motif dans les fichiers texte du projet.", summary="Chercher « {pattern} » dans {glob}", example="Motif : TODO|FIXME ; Fichiers : src/**/*.py", outputs=("matches", "count"))
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


@block("project_command", "Commande du projet", "Projet",
       [Param("command", "str", "python -m pytest -q", required=True, label="Commande", essential=True, placeholder="python -m pytest -q", help="Lancée à la racine du projet, sans shell."),
        Param("timeout", "duration", 600, label="Délai maximal", minimum=1, maximum=86400, unit="s", step=30)],
       ports=("out", "error"), side_effect=True, doc="Lance une commande à la racine du projet ; le port « error » traite un code non nul.",
       summary="Projet $ {command}", example="Commande : npm test", outputs=("code", "output", "ok", "seconds"))
def _project_command(ctx, p):
    return _run_command(ctx, {"command": p["command"], "cwd": "", "timeout": p["timeout"], "fail_on_error": False})


def catalog() -> list[dict]:
    return [{"type": b.type, "title": b.title, "category": b.category, "ports": list(b.ports), "side_effect": b.side_effect, "doc": b.doc,
             "summary": b.summary, "example": b.example, "outputs": list(b.outputs),
             "params": [{"name": q.name, "kind": q.kind, "default": q.default, "choices": list(q.choices), "required": q.required, "label": q.label or q.name,
                         "help": q.help, "minimum": q.minimum, "maximum": q.maximum, "step": q.step, "unit": q.unit, "mode": q.mode, "essential": q.essential}
                        for q in b.params]}
            for b in REGISTRY.values()]


def defaults(type_: str) -> dict:
    return {q.name: q.default for q in REGISTRY[type_].params}
