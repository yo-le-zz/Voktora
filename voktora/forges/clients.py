"""
Voktora — forges.clients
Un client par famille de forge, avec la même interface : `user()`, `list_repos()`, `repo(owner, name)`.
"""

from __future__ import annotations

import urllib.parse

from .base import ForgeError, Repo, http_json

MAX_PAGES = 10


class ForgeClient:
    kind = ""

    def __init__(self, host: str, token: str = ""):
        self.host, self.token = host, token

    # à surcharger
    def _base(self) -> str: ...
    def _headers(self) -> dict[str, str]:
        return {}
    def user(self) -> dict: ...
    def list_repos(self) -> list[Repo]: ...
    def repo(self, owner: str, name: str) -> Repo: ...

    # lecture seule (1.1.0) : tickets, demandes de fusion, intégration continue — format commun
    def issues(self, owner: str, name: str, limit: int = 30) -> list[dict]: ...
    def pulls(self, owner: str, name: str, limit: int = 30) -> list[dict]: ...
    def ci(self, owner: str, name: str) -> dict:
        """{state: success|failure|pending|none, name, url} du dernier pipeline / workflow."""
        return {"state": "none", "name": "", "url": ""}

    @staticmethod
    def _item(number, title, author, url, updated, draft=False) -> dict:
        return {"number": number, "title": str(title or "")[:200], "author": author or "", "url": url or "",
                "updated": str(updated or "")[:10], "draft": bool(draft)}

    def _get(self, path: str):
        return http_json(self._base() + path, self._headers())

    def _paged(self, path: str, size: int) -> list:
        out: list = []
        for page in range(1, MAX_PAGES + 1):
            chunk = self._get(f"{path}{'&' if '?' in path else '?'}page={page}")
            if not isinstance(chunk, list):
                raise ForgeError("Réponse inattendue de la forge.")
            out.extend(chunk)
            if len(chunk) < size:
                break
        return out


class GitHubClient(ForgeClient):
    kind = "github"

    def _base(self) -> str:
        return "https://api.github.com" if self.host in ("github.com", "api.github.com") \
            else f"https://{self.host}/api/v3"            # GitHub Enterprise

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-GitHub-Api-Version": "2022-11-28"} if self.token else {}

    def user(self) -> dict:
        raw = self._get("/user")
        return {"login": raw.get("login", ""), "name": raw.get("name") or raw.get("login", ""),
                "avatar_url": raw.get("avatar_url", "")}

    def _repo(self, raw: dict) -> Repo:
        parent = raw.get("parent") or {}
        return Repo("github", self.host, raw.get("full_name", ""), raw.get("html_url", ""), raw.get("clone_url", ""),
                    raw.get("ssh_url", ""), raw.get("description") or "", bool(raw.get("private")),
                    bool(raw.get("fork")), parent.get("full_name", ""), parent.get("html_url", ""),
                    raw.get("default_branch", ""))

    def list_repos(self) -> list[Repo]:
        return [self._repo(r) for r in self._paged("/user/repos?per_page=100&sort=updated", 100)]

    def repo(self, owner: str, name: str) -> Repo:
        return self._repo(self._get(f"/repos/{owner}/{name}"))

    def issues(self, owner: str, name: str, limit: int = 30) -> list[dict]:
        raw = self._get(f"/repos/{owner}/{name}/issues?state=open&per_page={min(100, limit + 20)}")
        return [self._item(i["number"], i["title"], (i.get("user") or {}).get("login"), i.get("html_url"), i.get("updated_at"))
                for i in raw if "pull_request" not in i][:limit]

    def pulls(self, owner: str, name: str, limit: int = 30) -> list[dict]:
        raw = self._get(f"/repos/{owner}/{name}/pulls?state=open&per_page={min(100, limit)}")
        return [self._item(i["number"], i["title"], (i.get("user") or {}).get("login"), i.get("html_url"),
                           i.get("updated_at"), i.get("draft")) for i in raw][:limit]

    def ci(self, owner: str, name: str) -> dict:
        runs = (self._get(f"/repos/{owner}/{name}/actions/runs?per_page=1") or {}).get("workflow_runs") or []
        if not runs:
            return {"state": "none", "name": "", "url": ""}
        run = runs[0]
        if run.get("status") != "completed":
            state = "pending"
        else:
            state = "success" if run.get("conclusion") == "success" else "failure"
        return {"state": state, "name": run.get("name", ""), "url": run.get("html_url", "")}


class GitLabClient(ForgeClient):
    kind = "gitlab"

    def _base(self) -> str:
        return f"https://{self.host}/api/v4"

    def _headers(self) -> dict[str, str]:
        return {"PRIVATE-TOKEN": self.token} if self.token else {}

    def user(self) -> dict:
        raw = self._get("/user")
        return {"login": raw.get("username", ""), "name": raw.get("name") or raw.get("username", ""),
                "avatar_url": raw.get("avatar_url", "")}

    def _repo(self, raw: dict) -> Repo:
        parent = raw.get("forked_from_project") or {}
        return Repo("gitlab", self.host, raw.get("path_with_namespace", ""), raw.get("web_url", ""),
                    raw.get("http_url_to_repo", ""), raw.get("ssh_url_to_repo", ""), raw.get("description") or "",
                    raw.get("visibility", "private") != "public", bool(parent),
                    parent.get("path_with_namespace", ""), parent.get("web_url") or parent.get("http_web_url", ""),
                    raw.get("default_branch") or "")

    def list_repos(self) -> list[Repo]:
        return [self._repo(r) for r in self._paged("/projects?membership=true&per_page=100&order_by=last_activity_at", 100)]

    def repo(self, owner: str, name: str) -> Repo:
        return self._repo(self._get("/projects/" + urllib.parse.quote(f"{owner}/{name}", safe="")))

    def _pid(self, owner: str, name: str) -> str:
        return urllib.parse.quote(f"{owner}/{name}", safe="")

    def issues(self, owner: str, name: str, limit: int = 30) -> list[dict]:
        raw = self._get(f"/projects/{self._pid(owner, name)}/issues?state=opened&per_page={min(100, limit)}")
        return [self._item(i["iid"], i["title"], (i.get("author") or {}).get("username"), i.get("web_url"),
                           i.get("updated_at")) for i in raw][:limit]

    def pulls(self, owner: str, name: str, limit: int = 30) -> list[dict]:
        raw = self._get(f"/projects/{self._pid(owner, name)}/merge_requests?state=opened&per_page={min(100, limit)}")
        return [self._item(i["iid"], i["title"], (i.get("author") or {}).get("username"), i.get("web_url"),
                           i.get("updated_at"), i.get("draft")) for i in raw][:limit]

    def ci(self, owner: str, name: str) -> dict:
        runs = self._get(f"/projects/{self._pid(owner, name)}/pipelines?per_page=1") or []
        if not runs:
            return {"state": "none", "name": "", "url": ""}
        status = runs[0].get("status", "")
        state = "success" if status == "success" else "failure" if status in ("failed", "canceled") else "pending"
        return {"state": state, "name": f"pipeline #{runs[0].get('id', '')}", "url": runs[0].get("web_url", "")}


class ForgejoClient(ForgeClient):
    """Forgejo et Gitea (API compatible) : forge de Fedora, Codeberg, instances auto-hébergées."""
    kind = "forgejo"

    def _base(self) -> str:
        return f"https://{self.host}/api/v1"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"token {self.token}"} if self.token else {}

    def user(self) -> dict:
        raw = self._get("/user")
        return {"login": raw.get("login", ""), "name": raw.get("full_name") or raw.get("login", ""),
                "avatar_url": raw.get("avatar_url", "")}

    def _repo(self, raw: dict) -> Repo:
        parent = raw.get("parent") or {}
        return Repo("forgejo", self.host, raw.get("full_name", ""), raw.get("html_url", ""), raw.get("clone_url", ""),
                    raw.get("ssh_url", ""), raw.get("description") or "", bool(raw.get("private")),
                    bool(raw.get("fork")), parent.get("full_name", ""), parent.get("html_url", ""),
                    raw.get("default_branch", ""))

    def list_repos(self) -> list[Repo]:
        return [self._repo(r) for r in self._paged("/user/repos?limit=50", 50)]

    def repo(self, owner: str, name: str) -> Repo:
        return self._repo(self._get(f"/repos/{owner}/{name}"))

    def issues(self, owner: str, name: str, limit: int = 30) -> list[dict]:
        raw = self._get(f"/repos/{owner}/{name}/issues?state=open&type=issues&limit={min(50, limit)}")
        return [self._item(i["number"], i["title"], (i.get("user") or {}).get("login"), i.get("html_url"),
                           i.get("updated_at")) for i in raw][:limit]

    def pulls(self, owner: str, name: str, limit: int = 30) -> list[dict]:
        raw = self._get(f"/repos/{owner}/{name}/pulls?state=open&limit={min(50, limit)}")
        return [self._item(i["number"], i["title"], (i.get("user") or {}).get("login"), i.get("html_url"),
                           i.get("updated_at"), i.get("draft")) for i in raw][:limit]

    def ci(self, owner: str, name: str) -> dict:
        branch = self.repo(owner, name).default_branch or "main"
        status = (self._get(f"/repos/{owner}/{name}/commits/{urllib.parse.quote(branch, safe='')}/status") or {}).get("state", "")
        state = {"success": "success", "failure": "failure", "error": "failure", "pending": "pending"}.get(status, "none")
        return {"state": state, "name": f"statut de {branch}", "url": ""}


CLIENTS = {"github": GitHubClient, "gitlab": GitLabClient, "forgejo": ForgejoClient}


def make_client(kind: str, host: str, token: str = "") -> ForgeClient:
    try:
        return CLIENTS[kind](host, token)
    except KeyError as exc:
        raise ForgeError(f"Type de forge inconnu : {kind or '?'}") from exc
