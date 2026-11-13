"""Pipelines personnalisables : étapes, conditions, tentatives, délai, annulation, journaux."""

from __future__ import annotations

import os
import os.path as osp
import shlex
import threading
import time
from dataclasses import asdict, dataclass, field

CONDITIONS = ("success", "always", "failure")


@dataclass
class Step:
    name: str
    command: str                       # découpé avec shlex : jamais interprété par un shell
    retries: int = 0
    retry_delay: float = 1.0
    timeout: float = 300.0
    condition: str = "success"         # success | always | failure | branch:<nom> | env:<NOM>=<valeur> | exists:<chemin>
    continue_on_error: bool = False
    cwd: str = ""                      # relatif au dossier du projet
    env: dict = field(default_factory=dict)


@dataclass
class Pipeline:
    name: str
    steps: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    notify: bool = True
    environment: str = "dev"           # dev | staging | prod

    def to_dict(self) -> dict:
        return {"name": self.name, "env": self.env, "notify": self.notify, "environment": self.environment,
                "steps": [asdict(s) for s in self.steps]}

    @staticmethod
    def from_dict(d: dict) -> Pipeline:
        steps = [Step(**{k: v for k, v in s.items() if k in Step.__dataclass_fields__}) for s in d.get("steps", [])]
        return Pipeline(d["name"], steps, dict(d.get("env", {})), bool(d.get("notify", True)), d.get("environment", "dev"))


def validate(p: Pipeline) -> list[str]:
    errs = []
    if not p.name.strip():
        errs.append("Le pipeline n'a pas de nom.")
    if not p.steps:
        errs.append("Le pipeline n'a aucune étape.")
    seen = set()
    for s in p.steps:
        if not s.name.strip():
            errs.append("Une étape n'a pas de nom.")
        if s.name in seen:
            errs.append(f"Nom d'étape en double : {s.name}")
        seen.add(s.name)
        try:
            if not shlex.split(s.command):
                errs.append(f"Étape « {s.name} » : commande vide.")
        except ValueError as exc:
            errs.append(f"Étape « {s.name} » : commande invalide ({exc}).")
        if s.retries < 0 or s.retries > 10:
            errs.append(f"Étape « {s.name} » : tentatives entre 0 et 10.")
        if not (s.condition in CONDITIONS or s.condition.split(":", 1)[0] in ("branch", "env", "exists")):
            errs.append(f"Étape « {s.name} » : condition inconnue ({s.condition}).")
        if s.cwd.startswith("/") or ".." in s.cwd.split("/"):
            errs.append(f"Étape « {s.name} » : dossier de travail hors du projet.")
    return errs


def condition_met(cond: str, previous_ok: bool, project: str, branch: str, env: dict) -> bool:
    if cond == "always":
        return True
    if cond == "success":
        return previous_ok
    if cond == "failure":
        return not previous_ok
    kind, _, arg = cond.partition(":")
    if kind == "branch":
        return branch == arg
    if kind == "env":
        name, _, value = arg.partition("=")
        return (env.get(name) if name in env else os.environ.get(name)) == value
    if kind == "exists":
        return (os.path.exists(os.path.join(project, arg)) if ".." not in arg and not arg.startswith("/") else False)
    return False


def run_pipeline(p: Pipeline, project: str, runner, cancel: threading.Event | None = None, on_event=None, branch: str = "",
                 sleep=time.sleep, clock=time.time) -> dict:
    """Exécute `p`. `runner(args, cwd, timeout, env, cancel, on_line)` → Result. Retourne l'enregistrement d'historique."""
    errs = validate(p)
    if errs:
        return {"kind": "pipeline", "name": p.name, "ok": False, "error": "; ".join(errs), "started": clock(), "steps": [], "log": ""}
    emit = on_event or (lambda *_: None)
    log: list[str] = []

    def say(line):
        log.append(line)
        emit("log", line)

    rec = {"kind": "pipeline", "name": p.name, "environment": p.environment, "started": clock(), "steps": [], "ok": True, "cancelled": False}
    previous_ok = True
    for step in p.steps:
        if cancel is not None and cancel.is_set():
            rec["cancelled"], rec["ok"] = True, False
            say("■ Annulé.")
            break
        env = {**p.env, **step.env}
        if not condition_met(step.condition, previous_ok, project, branch, env):
            rec["steps"].append({"name": step.name, "status": "skipped", "attempts": 0, "seconds": 0})
            say(f"○ {step.name} : ignorée (condition « {step.condition} »)")
            continue
        cwd = osp.join(project, step.cwd) if step.cwd else project
        attempts, res = 0, None
        for attempts in range(1, step.retries + 2):  # noqa: B007
            say(f"▶ {step.name} (essai {attempts}) : {step.command}")
            res = runner(shlex.split(step.command), cwd, step.timeout, env, cancel, lambda ln: say("  " + ln))
            if res.ok or res.cancelled or attempts > step.retries:
                break
            say(f"  ✗ code {res.code}{' (délai dépassé)' if res.timed_out else ''} — nouvel essai dans {step.retry_delay:g} s")
            sleep(step.retry_delay)
        ok = bool(res and res.ok)
        rec["steps"].append({"name": step.name, "status": "ok" if ok else "cancelled" if res and res.cancelled else "failed",
                             "attempts": attempts, "seconds": round(res.seconds if res else 0, 2), "code": res.code if res else -1})
        say(f"{'✓' if ok else '✗'} {step.name} — {'réussie' if ok else 'échec'}")
        if res and res.cancelled:
            rec["cancelled"], rec["ok"] = True, False
            break
        if not ok and not step.continue_on_error:
            rec["ok"] = False
        previous_ok = ok or step.continue_on_error
    rec["finished"] = clock()
    rec["log"] = "\n".join(log)
    emit("done", rec)
    return rec
