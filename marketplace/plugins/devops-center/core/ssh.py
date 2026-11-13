"""Profils SSH et exécution via les programmes `ssh` / `scp` du système (clés ou agent ; aucun mot de passe stocké)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
USER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


@dataclass
class SSHProfile:
    name: str
    host: str
    user: str = ""
    port: int = 22
    key_path: str = ""
    environment: str = "dev"      # dev | staging | prod

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Nom de profil requis.")
        if not HOST.match(self.host):
            raise ValueError("Hôte invalide.")
        if self.user and not USER.match(self.user):
            raise ValueError("Utilisateur invalide.")
        if not 0 < int(self.port) < 65536:
            raise ValueError("Port invalide.")
        if self.key_path.startswith("-"):
            raise ValueError("Chemin de clé invalide.")

    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    def to_dict(self) -> dict:
        return asdict(self)


def _base_opts(p: SSHProfile, port_flag: str) -> list[str]:
    opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new", port_flag, str(int(p.port))]
    if p.key_path:
        opts += ["-i", p.key_path]
    return opts


def ssh_args(p: SSHProfile, command: str) -> list[str]:
    p.validate()
    return ["ssh", *_base_opts(p, "-p"), "--", p.target(), command]


def scp_args(p: SSHProfile, local: str, remote: str, upload: bool = True, recursive: bool = False) -> list[str]:
    p.validate()
    if local.startswith("-") or remote.startswith("-"):
        raise ValueError("Chemin invalide.")
    remote_spec = f"{p.target()}:{remote}"
    pair = [local, remote_spec] if upload else [remote_spec, local]
    return ["scp", *(["-r"] if recursive else []), *_base_opts(p, "-P"), "--", *pair]


class SSH:
    def __init__(self, runner):
        self._run = runner

    def exec(self, p: SSHProfile, command: str, timeout: float = 60, **kw):
        return self._run(ssh_args(p, command), timeout=timeout, **kw)

    def test(self, p: SSHProfile):
        return self.exec(p, "echo voktora-ok", timeout=20)

    def upload(self, p: SSHProfile, local: str, remote: str, recursive: bool = False, timeout: float = 600):
        return self._run(scp_args(p, local, remote, True, recursive), timeout=timeout)

    def download(self, p: SSHProfile, remote: str, local: str, recursive: bool = False, timeout: float = 600):
        return self._run(scp_args(p, local, remote, False, recursive), timeout=timeout)
