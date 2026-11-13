"""Tickets et pull requests GitHub : API HTTPS (jeton du coffre) ou CLI `gh`. Lecture seule."""

from __future__ import annotations

import json
import re

REMOTE = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def parse_remote(url: str) -> tuple[str, str] | None:
    m = REMOTE.search((url or "").strip())
    return (m.group(1), m.group(2)) if m else None


class GitHubError(Exception):
    pass


class GitHub:
    """`http(method, url, headers) -> (code, bytes)` fourni par l'API du plugin ; `runner` pour `gh` ; `token()` → jeton ou ''."""

    def __init__(self, http=None, runner=None, token=lambda: ""):
        self._http, self._run, self._token = http, runner, token

    def _api(self, path: str):
        if self._http is None:
            raise GitHubError("Accès réseau indisponible.")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        tok = self._token()
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        code, body = self._http("GET", "https://api.github.com" + path, headers)
        if code == 401 or code == 403:
            raise GitHubError("GitHub a refusé l'accès (jeton absent, invalide ou limite atteinte).")
        if code == 404:
            raise GitHubError("Dépôt introuvable (privé sans jeton ?).")
        if code != 200:
            raise GitHubError(f"GitHub : code {code}.")
        return json.loads(body.decode("utf-8", "replace"))

    def _gh(self, *args):
        if self._run is None:
            raise GitHubError("`gh` indisponible.")
        res = self._run(["gh", *args], timeout=60)
        if not res.ok:
            raise GitHubError((res.out or res.error).strip().splitlines()[0] if (res.out or res.error) else "gh a échoué")
        return json.loads(res.out or "[]")

    def issues(self, owner: str, repo: str, state: str = "open", prefer_cli: bool = False) -> list[dict]:
        if prefer_cli:
            rows = self._gh("issue", "list", "-R", f"{owner}/{repo}", "--state", state, "--json", "number,title,state,author,url")
            return [{"number": r["number"], "title": r["title"], "state": r["state"].lower(), "author": (r.get("author") or {}).get("login", ""),
                     "url": r["url"]} for r in rows]
        rows = self._api(f"/repos/{owner}/{repo}/issues?state={state}&per_page=50")
        return [{"number": r["number"], "title": r["title"], "state": r["state"], "author": r["user"]["login"], "url": r["html_url"]}
                for r in rows if "pull_request" not in r]

    def pulls(self, owner: str, repo: str, state: str = "open", prefer_cli: bool = False) -> list[dict]:
        if prefer_cli:
            rows = self._gh("pr", "list", "-R", f"{owner}/{repo}", "--state", state, "--json", "number,title,state,author,url,headRefName")
            return [{"number": r["number"], "title": r["title"], "state": r["state"].lower(), "author": (r.get("author") or {}).get("login", ""),
                     "url": r["url"], "branch": r.get("headRefName", "")} for r in rows]
        rows = self._api(f"/repos/{owner}/{repo}/pulls?state={state}&per_page=50")
        return [{"number": r["number"], "title": r["title"], "state": r["state"], "author": r["user"]["login"], "url": r["html_url"],
                 "branch": r["head"]["ref"]} for r in rows]
