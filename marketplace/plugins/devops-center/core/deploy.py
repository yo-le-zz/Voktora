"""Déploiements : sauvegarde préalable, copie, vérification, restauration AUTOMATIQUE en cas d'échec."""

from __future__ import annotations

import shlex
import shutil
import tarfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .ssh import SSH, SSHProfile


@dataclass
class Target:
    name: str
    source: str = "."                     # relatif au projet
    dest: str = ""                        # dossier local, ou chemin distant si `ssh` est renseigné
    ssh: str = ""                         # nom d'un profil SSH ; vide = déploiement local
    environment: str = "dev"              # dev | staging | prod
    pre: list = field(default_factory=list)     # commandes avant (liste de chaînes)
    post: list = field(default_factory=list)    # commandes après
    health: str = ""                      # commande de vérification (code 0 = sain)
    exclude: list = field(default_factory=lambda: [".git", "__pycache__", "node_modules", ".venv", "target"])

    def to_dict(self):
        return asdict(self)


class DeployError(Exception):
    pass


def _ignore(exclude):
    def ignore(_dir, names):
        return [n for n in names if n in exclude]
    return ignore


def backup_local(dest: Path, backup_dir: Path, label: str) -> Path | None:
    if not dest.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    out = backup_dir / f"{label}-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(dest, arcname=".")
    return out


def restore_local(archive: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        tar.extractall(dest, filter="data")   # noqa: S202 — archive créée par ce même module, filtre « data » actif


def deploy(target: Target, project: str, backup_dir: Path, runner, profiles: dict[str, SSHProfile] | None = None,
           confirmed: bool = False, cancel=None, on_line=None, clock=time.time) -> dict:
    """Retourne l'enregistrement d'historique. `prod` exige `confirmed=True`."""
    say = on_line or (lambda _l: None)
    log: list[str] = []

    def emit(line):
        log.append(line)
        say(line)

    rec = {"kind": "deploy", "name": target.name, "environment": target.environment, "started": clock(), "ok": False,
           "restored": False, "backup": ""}
    if target.environment == "prod" and not confirmed:
        raise DeployError("Déploiement en production : confirmation explicite requise.")
    if not target.dest or target.dest in ("/", "~"):
        raise DeployError("Destination invalide.")
    src = (Path(project) / target.source).resolve()
    if not src.is_dir() or not src.is_relative_to(Path(project).resolve()):
        raise DeployError("Dossier source introuvable ou hors du projet.")
    profile = None
    if target.ssh:
        profile = (profiles or {}).get(target.ssh)
        if profile is None:
            raise DeployError(f"Profil SSH inconnu : {target.ssh}")
    ssh = SSH(runner)

    def cmd(command: str) -> bool:
        args = shlex.split(command)
        res = runner(args, cwd=str(src), timeout=600, env=None, cancel=cancel, on_line=lambda ln: emit("  " + ln)) if profile is None \
            else ssh.exec(profile, command, timeout=600)
        emit(f"{'✓' if res.ok else '✗'} {command}")
        return res.ok

    try:
        for c in target.pre:
            emit(f"▶ avant : {c}")
            r = runner(shlex.split(c), cwd=str(src), timeout=600, env=None, cancel=cancel, on_line=lambda ln: emit("  " + ln))
            if not r.ok:
                raise DeployError(f"Commande « avant » en échec : {c}")
        label = "".join(ch if ch.isalnum() else "_" for ch in target.name)
        if profile is None:
            dest = Path(target.dest)
            arch = backup_local(dest, backup_dir, label)
            rec["backup"] = str(arch or "")
            emit(f"● sauvegarde : {arch or 'rien à sauvegarder (première installation)'}")
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest, dirs_exist_ok=True, ignore=_ignore(set(target.exclude)))
            emit(f"● copié vers {dest}")
        else:
            backup_dir.mkdir(parents=True, exist_ok=True)
            remote_bk = f"{target.dest.rstrip('/')}.voktora-backup.tar.gz"
            r = ssh.exec(profile, f"if [ -d {_q(target.dest)} ]; then tar czf {_q(remote_bk)} -C {_q(target.dest)} . ; fi")
            if not r.ok:
                raise DeployError("Sauvegarde distante impossible : " + r.out.strip())
            rec["backup"] = f"{profile.name}:{remote_bk}"
            emit(f"● sauvegarde distante : {remote_bk}")
            r = ssh.exec(profile, f"mkdir -p {_q(target.dest)}")
            r = ssh.upload(profile, str(src) + "/.", target.dest, recursive=True) if r.ok else r
            if not r.ok:
                raise DeployError("Envoi impossible : " + r.out.strip())
            emit("● envoyé")
        ok = all(cmd(c) for c in target.post)
        if ok and target.health:
            emit(f"▶ vérification : {target.health}")
            ok = cmd(target.health)
        if not ok:
            raise DeployError("Vérification ou commande « après » en échec.")
        rec["ok"] = True
    except DeployError as exc:
        emit(f"✗ {exc}")
        rec["error"] = str(exc)
        if rec.get("backup") or profile is None:
            _auto_restore(target, profile, ssh, rec, emit)
    rec["finished"] = clock()
    rec["log"] = "\n".join(log)
    return rec


def _q(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


def _auto_restore(target, profile, ssh, rec, emit) -> None:
    try:
        if profile is None:
            if rec["backup"]:
                restore_local(Path(rec["backup"]), Path(target.dest))
                rec["restored"] = True
                emit("↺ restauration automatique depuis la sauvegarde : effectuée")
            elif Path(target.dest).exists():
                emit("↺ pas de sauvegarde (première installation) : rien à restaurer")
        else:
            bk = rec["backup"].split(":", 1)[1]
            r = ssh.exec(profile, f"if [ -f {_q(bk)} ]; then rm -rf {_q(target.dest)}/* && tar xzf {_q(bk)} -C {_q(target.dest)}; fi")
            rec["restored"] = r.ok
            emit("↺ restauration distante : " + ("effectuée" if r.ok else "ÉCHEC — vérifiez le serveur : " + r.out.strip()))
    except Exception as exc:  # noqa: BLE001
        emit(f"↺ restauration impossible : {exc}")
