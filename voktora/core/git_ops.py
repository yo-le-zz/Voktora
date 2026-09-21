"""
Voktora — core.git_ops
Opérations Git (clone, push, pull, branches…).

Authentification : le token GitHub n'est JAMAIS écrit dans l'URL d'un remote
(donc jamais dans `.git/config`, ni dans un export ou un snapshot), ni passé
en argument de ligne de commande (visible dans la liste des processus). Il est
transmis par variables d'environnement (`GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_n`
/ `GIT_CONFIG_VALUE_n`, git ≥ 2.31) sous forme d'un en-tête HTTP limité à
https://github.com/ — un autre hôte ne le reçoit donc jamais.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import constants, github_auth, organize

# ──────────────────────────────────────────────
# GIT — Infrastructure
# ──────────────────────────────────────────────

_ALLOWED_URL_RE = re.compile(r"^(https?://|ssh://|git://|[\w.-]+@[\w.-]+:)", re.IGNORECASE)
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]*$")


def validate_clone_url(url: str) -> str:
    """Retourne l'URL nettoyée de ses identifiants, ou lève ValueError si elle est suspecte.

    Refuse les transports exotiques (ex. « ext:: », qui exécute une commande) et
    les URL commençant par « - » qui seraient lues comme une option de git.
    """
    cleaned = organize.strip_url_credentials(url or "")
    if not cleaned or not _ALLOWED_URL_RE.match(cleaned):
        raise ValueError("URL de dépôt invalide (attendu : https://…, ssh://… ou git@hôte:chemin).")
    return cleaned


def validate_ref(name: str) -> str:
    """Valide un nom de branche/référence utilisé comme argument git."""
    name = (name or "").strip()
    if not _REF_RE.match(name) or ".." in name or name.endswith((".lock", "/")):
        raise ValueError(f"Nom de branche invalide : {name!r}")
    return name


def _auth_env(token: str) -> dict | None:
    """Environnement portant l'authentification GitHub, ou None sans token."""
    if not token:
        return None
    credentials = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    env = os.environ.copy()
    try:
        index = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        index = 0
    env[f"GIT_CONFIG_KEY_{index}"] = "http.https://github.com/.extraheader"
    env[f"GIT_CONFIG_VALUE_{index}"] = f"AUTHORIZATION: basic {credentials}"
    env["GIT_CONFIG_COUNT"] = str(index + 1)
    env["GIT_TERMINAL_PROMPT"] = "0"   # jamais d'invite bloquante dans un thread
    return env


def _redact(text: str, token: str) -> str:
    """Masque le token (et son encodage) dans une sortie destinée à l'affichage."""
    if token:
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
        text = text.replace(token, "***").replace(encoded, "***")
    return text


def _run_git(args: list, cwd: Path, token: str = "") -> str:
    result = subprocess.run(
        ["git"] + args, cwd=str(cwd),
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        creationflags=constants._NO_WINDOW, check=False,
        env=_auth_env(token),
    )
    return _redact((result.stdout + result.stderr).strip(), token)


def run_git_streaming(args: list, cwd: Path, token: str = "",
                      on_line: Callable[[str], None] | None = None,
                      cancel: Callable[[], bool] | None = None) -> int:
    """Exécute git en relayant sa sortie ligne à ligne (progression comprise).

    Peut être annulée : le processus est alors arrêté et OperationCancelled levée.
    Retourne le code de sortie.
    """
    proc = subprocess.Popen(
        ["git"] + args, cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=constants._NO_WINDOW, env=_auth_env(token),
    )

    def _pump() -> None:
        buffer = b""
        while chunk := proc.stdout.read1(4096):
            buffer += chunk
            *lines, buffer = re.split(rb"[\r\n]+", buffer)
            for raw in lines:
                if raw.strip() and on_line:
                    on_line(_redact(raw.decode("utf-8", errors="replace").strip(), token))
        if buffer.strip() and on_line:
            on_line(_redact(buffer.decode("utf-8", errors="replace").strip(), token))

    reader = threading.Thread(target=_pump, daemon=True)
    reader.start()
    try:
        while proc.poll() is None:
            if cancel is not None and cancel():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise constants.OperationCancelled("Opération git annulée.")
            time.sleep(0.1)
    finally:
        reader.join(timeout=2)
    return proc.returncode


class GitQueue:
    def __init__(self, path: Path, on_step: Callable | None = None, token: str = ""):
        self._path    = path
        self._on_step = on_step
        self._token   = token
        self._cmds:   list = []

    def add(self, args: list, label: str | None = None) -> GitQueue:
        self._cmds.append((args, label))
        return self

    def run_all(self) -> list:
        outputs = []
        for args, label in self._cmds:
            out = _run_git(args, self._path, self._token)
            if self._on_step:
                self._on_step(label or " ".join(args), out)
            outputs.append(out)
        return outputs


def git_clone(repo_url: str, target_path: Path, token: str = "", branch: str = "",
              on_output: Callable[[str], None] | None = None,
              cancel: Callable[[], bool] | None = None) -> str:
    """Clone `repo_url` dans `target_path` (qui ne doit pas exister).

    Sans `token`, utilise celui du compte GitHub connecté. En cas d'échec ou
    d'annulation, le dossier partiellement créé est supprimé.
    """
    target_path = Path(target_path)
    url = validate_clone_url(repo_url)
    if target_path.exists():
        raise FileExistsError(f"Le dossier existe déjà : {target_path}")
    if not token:
        token = github_auth.get_effective_token()

    args = ["clone", "--progress"]
    if branch:
        args += ["--branch", validate_ref(branch)]
    # « -- » : ce qui suit est un opérande, jamais une option, même s'il commence par « - ».
    args += ["--", url, str(target_path)]

    target_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def _collect(line: str) -> None:
        lines.append(line)
        if on_output:
            on_output(line)

    try:
        code = run_git_streaming(args, target_path.parent, token, _collect, cancel)
    except FileNotFoundError as exc:
        raise RuntimeError("git est introuvable : installez Git et vérifiez qu'il est dans le PATH.") from exc
    except BaseException:
        shutil.rmtree(target_path, ignore_errors=True)
        raise
    if code != 0:
        shutil.rmtree(target_path, ignore_errors=True)
        detail = "\n".join(lines[-5:]) or f"code de sortie {code}"
        raise RuntimeError(f"git clone a échoué :\n{detail}")
    return "\n".join(lines)


def git_init(path: Path) -> str:
    return _run_git(["init"], path)


def git_pull(path: Path, branch: str = "main", token: str = "") -> str:
    return _run_git(["pull", "origin", validate_ref(branch.strip() or "main")], path, token)


def git_status(path: Path) -> str:
    return _run_git(["status"], path)


def git_log(path: Path, n: int = 15) -> str:
    return _run_git(
        ["log", f"--max-count={n}", "--oneline", "--decorate", "--color=never"], path,
    )


def git_list_local_branches(path: Path) -> list:
    raw = _run_git(["branch", "--format=%(refname:short)"], path)
    return [b.strip() for b in raw.splitlines() if b.strip()]


def git_checkout(path: Path, branch: str) -> str:
    branch = validate_ref(branch)
    out    = _run_git(["checkout", branch], path)
    if "error" in out.lower() or "fatal" in out.lower():
        out = _run_git(["checkout", "-b", branch], path)
    return out


def git_merge(path: Path, branch: str, token: str = "", on_step: Callable | None = None) -> None:
    branch = validate_ref(branch)
    gq = GitQueue(path, on_step=on_step, token=token)
    gq.add(["merge", branch], label=f"merge {branch}")
    gq.run_all()


def git_push_advanced(path: Path, repo_url: str, branches: list,
                       message: str = "", description: str = "",
                       force: bool = False, follow_tags: bool = False,
                       no_verify: bool = False, is_initial: bool = False,
                       on_step: Callable | None = None, token: str = "") -> None:
    branches = [validate_ref(b) for b in branches if b.strip()] or ["main"]
    # Le remote est toujours enregistré SANS identifiants ; le token voyage
    # séparément (voir _auth_env). Cela nettoie aussi les anciens remotes
    # dont l'URL contenait un token.
    clean_url = validate_clone_url(repo_url)
    if not message:
        message = ("Initial commit — Voktora" if is_initial
                   else f"Voktora commit — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    full_message = message.strip()
    if description and description.strip():
        full_message = f"{full_message}\n\n{description.strip()}"

    gq = GitQueue(path, on_step=on_step, token=token)
    gq.add(["add", "."], label="add .")
    gq.add(["commit", "-m", full_message], label=f'commit -m "{message[:60]}"')

    existing_remotes = _run_git(["remote"], path).splitlines()
    if "origin" in existing_remotes:
        gq.add(["remote", "set-url", "origin", clean_url], label="remote set-url origin …")
    else:
        gq.add(["remote", "add", "origin", clean_url], label="remote add origin …")

    for branch in branches:
        if is_initial:
            gq.add(["branch", "-M", branch], label=f"branch -M {branch}")
        push_args = ["push", "-u", "origin", branch]
        if force:
            push_args.append("--force")
        if follow_tags:
            push_args.append("--follow-tags")
        if no_verify:
            push_args.append("--no-verify")
        gq.add(push_args, label=" ".join(push_args[1:]))

    gq.run_all()


def git_push_initial(path: Path, repo_url: str, branch: str = "main", token: str = "") -> str:
    lines: list = []
    git_push_advanced(path=path, repo_url=repo_url, branches=[branch],
                      force=True, is_initial=True, token=token,
                      on_step=lambda cmd, out: lines.append(f"$ git {cmd}\n{out}"))
    return "\n".join(lines)


def git_commit_and_push(path: Path, repo_url: str, branch: str = "main", message: str = "",
                        token: str = "") -> str:
    lines: list = []
    git_push_advanced(path=path, repo_url=repo_url, branches=[branch], message=message, token=token,
                      on_step=lambda cmd, out: lines.append(f"$ git {cmd}\n{out}"))
    return "\n".join(lines)


def verify_github_repo(repo_url: str, token: str = "") -> tuple:
    url_clean = repo_url.rstrip("/").removesuffix(".git")
    parts = url_clean.rstrip("/").split("/")
    if len(parts) < 2:
        return False, "⚠  URL invalide."
    owner, repo = parts[-2], parts[-1]
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {"User-Agent": f"{constants.APP_NAME}/{constants.APP_VERSION}"}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        name = data.get("full_name", repo)
        private_label = "🔒 privé" if data.get("private") else "🌐 public"
        return True, f"✅  Repo trouvé : {name} ({private_label})"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "❌  Repo introuvable (404)."
        if e.code == 401:
            return False, "❌  Non autorisé (401)."
        return False, f"❌  Erreur HTTP {e.code}."
    except Exception as e:
        return False, f"❌  Erreur réseau : {e}"


def list_github_branches(repo_url: str, token: str = "") -> list:
    url_clean = repo_url.rstrip("/").removesuffix(".git")
    parts = url_clean.rstrip("/").split("/")
    if len(parts) < 2:
        return []
    owner, repo = parts[-2], parts[-1]
    api_url = f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100"
    headers = {"User-Agent": f"{constants.APP_NAME}/{constants.APP_VERSION}"}
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [b["name"] for b in data if isinstance(b, dict)]
    except Exception:
        return []


