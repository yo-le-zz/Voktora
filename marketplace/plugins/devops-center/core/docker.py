"""Docker via la CLI (aucune dépendance) : conteneurs, images, journaux, démarrage/arrêt, compose."""

from __future__ import annotations

import json
import re

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]*$")


class DockerError(Exception):
    pass


def check_name(name: str) -> str:
    if not NAME.match(name or ""):
        raise DockerError(f"Nom invalide : {name!r}")
    return name


class Docker:
    def __init__(self, runner, cwd=None):
        self._run, self.cwd = runner, cwd

    def _d(self, *args, timeout=60):
        return self._run(["docker", *args], cwd=self.cwd, timeout=timeout)

    def available(self) -> tuple[bool, str]:
        res = self._d("version", "--format", "{{.Server.Version}}", timeout=15)
        return res.ok, (res.out.strip() if res.ok else (res.out or res.error or "docker introuvable").strip().splitlines()[0])

    @staticmethod
    def _json_lines(text: str) -> list[dict]:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
        return rows

    def containers(self, all_: bool = True) -> list[dict]:
        res = self._d("ps", *(["-a"] if all_ else []), "--format", "{{json .}}")
        if not res.ok:
            raise DockerError(res.out.strip() or res.error)
        return [{"id": r.get("ID", ""), "name": r.get("Names", ""), "image": r.get("Image", ""), "status": r.get("Status", ""),
                 "state": r.get("State", ""), "ports": r.get("Ports", "")} for r in self._json_lines(res.out)]

    def images(self) -> list[dict]:
        res = self._d("images", "--format", "{{json .}}")
        if not res.ok:
            raise DockerError(res.out.strip() or res.error)
        return [{"id": r.get("ID", ""), "repo": r.get("Repository", ""), "tag": r.get("Tag", ""), "size": r.get("Size", "")}
                for r in self._json_lines(res.out)]

    def logs(self, name: str, tail: int = 200) -> str:
        return self._d("logs", "--tail", str(int(tail)), check_name(name), timeout=30).out

    def action(self, verb: str, name: str):
        if verb not in ("start", "stop", "restart", "rm", "pause", "unpause"):
            raise DockerError(f"Action inconnue : {verb}")
        res = self._d(verb, check_name(name), timeout=120)
        if not res.ok:
            raise DockerError(res.out.strip() or res.error)
        return res

    def compose(self, verb: str, file: str = "", services: tuple = ()):
        if verb not in ("up", "down", "ps", "build", "logs", "pull"):
            raise DockerError(f"Action compose inconnue : {verb}")
        args = ["compose", *(["-f", file] if file else []), verb]
        if verb == "up":
            args.append("-d")
        if verb == "logs":
            args += ["--tail", "200"]
        args += [check_name(s) for s in services]
        return self._d(*args, timeout=600)
