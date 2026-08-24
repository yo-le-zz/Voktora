"""
Voktora — core.git_ops
Fragment de core.py extrait lors du découpage v1.0.2 en package.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import config_store, constants, github_auth, paths

# ──────────────────────────────────────────────
# GIT — Infrastructure
# ──────────────────────────────────────────────

def _run_git(args: list, cwd: Path) -> str:
    result = subprocess.run(
        ["git"] + args, cwd=str(cwd),
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        creationflags=constants._NO_WINDOW,
    )
    return (result.stdout + result.stderr).strip()



def export_all_to_zip() -> str:
    """Exporte toutes les instances et intents dans un fichier ZIP horodaté."""
    import json as _json
    import zipfile as _zip
    from datetime import datetime as _dt

    backups_dir = paths.get_backups_dir()
    timestamp   = _dt.now().strftime("%Y%m%d_%H%M%S")
    zip_path    = backups_dir / f"voktora_export_{timestamp}.zip"

    with _zip.ZipFile(zip_path, "w", _zip.ZIP_DEFLATED) as zf:
        cfg = config_store._load_config()

        for category, prefix in [("instances", "instances"), ("intents", "intents")]:
            for entry in cfg.get(category, []):
                p = Path(entry["path"])
                if not p.exists():
                    continue
                try:
                    for f in p.rglob("*"):
                        if f.is_file() and ".git/objects" not in str(f):
                            arc = f"{prefix}/{p.name}/{f.relative_to(p)}"
                            zf.write(f, arc)
                except Exception as exc:
                    print(f"[export] {p}: {exc}")

        zf.writestr("config.json",
                    _json.dumps(cfg, indent=2, ensure_ascii=False))
        zf.writestr("export_info.txt",
                    f"Voktora export — {timestamp}\nVersion : {constants.APP_VERSION}\n")

    return str(zip_path)


class GitQueue:
    def __init__(self, path: Path, on_step: Callable | None = None):
        self._path    = path
        self._on_step = on_step
        self._cmds:   list = []

    def add(self, args: list, label: str | None = None) -> GitQueue:
        self._cmds.append((args, label))
        return self

    def run_all(self) -> list:
        outputs = []
        for args, label in self._cmds:
            out = _run_git(args, self._path)
            if self._on_step:
                self._on_step(label or " ".join(args), out)
            outputs.append(out)
        return outputs


def git_set_github_credentials(path: Path, username: str, token: str) -> str:
    _run_git(["config", "user.name", username], path)
    url = f"https://{username}:{token}@github.com/"
    _run_git(["config", "credential.helper", "store"], path)
    _run_git(["remote", "set-url", "origin", url], path)
    return f"Credentials configurées pour {username}"


def git_clone_with_auth(repo_url: str, target_path: Path, username: str, token: str) -> str:
    auth_url = repo_url.replace("https://github.com/", f"https://{username}:{token}@github.com/")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    return _run_git(["clone", auth_url, str(target_path)], target_path.parent)


def git_clone_public(repo_url: str, target_path: Path) -> str:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    return _run_git(["clone", repo_url, str(target_path)], target_path.parent)


def git_clone(repo_url: str, target_path: Path, token: str = "") -> str:
    if not token:
        token = github_auth.get_effective_token()
    if token:
        try:
            req = urllib.request.Request(
                "https://api.github.com/user",
                headers={"Authorization": f"token {token}",
                         "User-Agent": f"{constants.APP_NAME}/{constants.APP_VERSION}"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                user_data = json.loads(resp.read().decode())
                username = user_data.get("login", "voktora-user")
        except Exception:
            username = "voktora-user"
        return git_clone_with_auth(repo_url, target_path, username, token)
    else:
        return git_clone_public(repo_url, target_path)


def git_init(path: Path) -> str:
    return _run_git(["init"], path)


def git_pull(path: Path, branch: str = "main") -> str:
    return _run_git(["pull", "origin", branch.strip() or "main"], path)


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
    branch = branch.strip()
    out    = _run_git(["checkout", branch], path)
    if "error" in out.lower() or "fatal" in out.lower():
        out = _run_git(["checkout", "-b", branch], path)
    return out


def git_merge(path: Path, branch: str, token: str = "", on_step: Callable | None = None) -> None:
    gq = GitQueue(path, on_step=on_step)
    gq.add(["merge", branch.strip()], label=f"merge {branch.strip()}")
    gq.run_all()


def git_push_advanced(path: Path, repo_url: str, branches: list,
                       message: str = "", description: str = "",
                       force: bool = False, follow_tags: bool = False,
                       no_verify: bool = False, is_initial: bool = False,
                       on_step: Callable | None = None) -> None:
    branches = [b.strip() for b in branches if b.strip()] or ["main"]
    if not message:
        message = ("Initial commit — Voktora" if is_initial
                   else f"Voktora commit — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    full_message = message.strip()
    if description and description.strip():
        full_message = f"{full_message}\n\n{description.strip()}"

    gq = GitQueue(path, on_step=on_step)
    gq.add(["add", "."], label="add .")
    gq.add(["commit", "-m", full_message], label=f'commit -m "{message[:60]}"')

    existing_remotes = _run_git(["remote"], path).splitlines()
    if "origin" in existing_remotes:
        gq.add(["remote", "set-url", "origin", repo_url], label="remote set-url origin …")
    else:
        gq.add(["remote", "add", "origin", repo_url], label="remote add origin …")

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


def git_push_initial(path: Path, repo_url: str, branch: str = "main") -> str:
    lines: list = []
    git_push_advanced(path=path, repo_url=repo_url, branches=[branch],
                      force=True, is_initial=True,
                      on_step=lambda cmd, out: lines.append(f"$ git {cmd}\n{out}"))
    return "\n".join(lines)


def git_commit_and_push(path: Path, repo_url: str, branch: str = "main", message: str = "") -> str:
    lines: list = []
    git_push_advanced(path=path, repo_url=repo_url, branches=[branch], message=message,
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


