"""Git en lecture + opérations sûres (fetch, pull --ff-only, checkout). AUCUN push : ni méthode, ni commande."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Status:
    branch: str = ""
    upstream: str = ""
    ahead: int = 0
    behind: int = 0
    staged: list = None
    changed: list = None
    untracked: list = None

    def __post_init__(self):
        self.staged, self.changed, self.untracked = self.staged or [], self.changed or [], self.untracked or []

    @property
    def clean(self) -> bool:
        return not (self.staged or self.changed or self.untracked)


class GitError(Exception):
    pass


def parse_status(text: str) -> Status:
    st = Status()
    for line in text.splitlines():
        if line.startswith("## "):
            head = line[3:]
            if head.startswith("No commits yet on "):
                st.branch = head.split(" on ", 1)[1]
                continue
            branch, _, rest = head.partition("...")
            st.branch = branch
            if rest:
                st.upstream, _, tail = rest.partition(" [")
                for part in tail.rstrip("]").split(", "):
                    if part.startswith("ahead "):
                        st.ahead = int(part[6:])
                    elif part.startswith("behind "):
                        st.behind = int(part[7:])
        elif line.startswith("?? "):
            st.untracked.append(line[3:])
        elif len(line) > 3:
            x, y, path = line[0], line[1], line[3:]
            if x not in " ?":
                st.staged.append((x, path))
            if y not in " ?":
                st.changed.append((y, path))
    return st


class Git:
    def __init__(self, repo, runner):
        self.repo, self._run = str(repo), runner

    def _git(self, *args, timeout=60, check=True):
        res = self._run(["git", *args], cwd=self.repo, timeout=timeout)
        if check and not res.ok:
            raise GitError((res.out or res.error or f"git {args[0]} a échoué").strip())
        return res

    def is_repo(self) -> bool:
        return self._git("rev-parse", "--is-inside-work-tree", check=False).out.strip() == "true"

    def status(self) -> Status:
        return parse_status(self._git("status", "--porcelain=v1", "-b").out)

    def branches(self) -> list[dict]:
        out = self._git("branch", "-a", "--format=%(HEAD)|%(refname:short)|%(objectname:short)|%(upstream:short)").out
        rows = []
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) == 4 and parts[1] and "HEAD" not in parts[1].split("/")[-1:]:
                rows.append({"current": parts[0] == "*", "name": parts[1], "sha": parts[2], "upstream": parts[3],
                             "remote": parts[1].startswith("origin/")})
        return rows

    def log(self, limit: int = 30, branch: str = "") -> list[dict]:
        args = ["log", f"-{int(limit)}", "--format=%h%x1f%an%x1f%ad%x1f%s", "--date=short"]
        if branch:
            args.append(branch)
        res = self._git(*args, check=False)
        return [dict(zip(("sha", "author", "date", "subject"), line.split("\x1f"), strict=False)) for line in res.out.splitlines() if "\x1f" in line]

    def diff(self, path: str = "", staged: bool = False) -> str:
        args = ["diff", "--no-color"] + (["--cached"] if staged else []) + (["--", path] if path else [])
        return self._git(*args).out

    def remote_url(self, name: str = "origin") -> str:
        return self._git("remote", "get-url", name, check=False).out.strip()

    def fetch(self):
        return self._git("fetch", "--prune", timeout=180)

    def pull(self):
        """Fast-forward uniquement : jamais de fusion ni de réécriture automatiques."""
        if not self.status().clean:
            raise GitError("Des modifications locales existent : pull refusé (validez ou mettez-les de côté d'abord).")
        return self._git("pull", "--ff-only", timeout=180)

    def checkout(self, branch: str):
        if branch.startswith("-"):
            raise GitError("Nom de branche invalide.")
        return self._git("checkout", branch)

    def head(self) -> str:
        return self._git("rev-parse", "HEAD", check=False).out.strip()
