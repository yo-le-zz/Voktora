"""Moteur d'exécution : fils d'exécution, annulation, délais, tentatives, branches parallèles, boucles, conditions, test à blanc."""

from __future__ import annotations

import copy
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import blocks
from . import expr as ex
from .validation import validate

MAX_STEPS = 20000


class WorkflowError(Exception):
    pass


class Run:
    def __init__(self, wf: dict, ctx: blocks.Ctx, dry_run: bool = False, on_event=None, clock=time.time, sleep=time.sleep):
        self.wf, self.ctx, self.dry, self.clock, self.sleep = wf, ctx, dry_run, clock, sleep
        self.nodes = {n["id"]: n for n in wf["nodes"]}
        self.out: dict[str, list] = {}
        for e in wf["edges"]:
            self.out.setdefault(e["src"], []).append((e.get("port", "out"), e["dst"]))
        self.on_event = on_event or (lambda *_: None)
        self.lines: list[str] = []
        self.results: list[dict] = []
        self.lock = threading.Lock()
        self.steps = 0
        ctx._log = self._log

    def _log(self, line: str) -> None:
        with self.lock:
            self.lines.append(line)
        self.on_event("log", line)

    def _alias(self, node: dict) -> None:
        label = re.sub(r"\W+", "_", str(node.get("label", ""))).strip("_")
        if label and label.isidentifier() and label not in self.nodes:
            self.ctx.outputs[label] = self.ctx.outputs[node["id"]]

    # ------------------------------------------------------------------ exécution d'un bloc
    def _call(self, node: dict, ctx) -> dict:
        b = blocks.REGISTRY[node["type"]]
        opts = node.get("options", {})
        retries = max(0, min(int(opts.get("retries", 0)), 10))
        timeout = float(opts.get("timeout", 0) or 0)
        ctx.node_id = node["id"]
        params = {q.name: node.get("params", {}).get(q.name, q.default) for q in b.params}
        last = None
        for attempt in range(1, retries + 2):
            if ctx.cancel.is_set():
                raise blocks.BlockError("Annulé.")
            try:
                rendered = {k: (v if next((q.kind for q in b.params if q.name == k), "") in ("expr", "code") else ctx.render(v)) for k, v in params.items()}
                if self.dry and b.side_effect:
                    ctx.log(f"(test à blanc) « {b.title} » non exécuté")
                    return {"out": {"dry_run": True, "skipped": True}, "attempts": attempt}
                res = self._with_timeout(b.run, ctx, rendered, timeout)
                res["attempts"] = attempt
                return res
            except (blocks.BlockError, ex.ExprError) as exc:
                last = exc
                if attempt <= retries:
                    ctx.log(f"✗ {exc} — nouvel essai {attempt + 1}/{retries + 1}")
                    self.sleep(float(opts.get("retry_delay", 1)))
        raise blocks.BlockError(str(last))

    @staticmethod
    def _with_timeout(fn, ctx, params, timeout):
        if timeout <= 0:
            return fn(ctx, params)
        box: dict = {}

        def target():
            try:
                box["r"] = fn(ctx, params)
            except BaseException as exc:  # noqa: BLE001
                box["e"] = exc
        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise blocks.BlockError(f"Délai de {timeout:g} s dépassé.")
        if "e" in box:
            raise box["e"]
        return box["r"]

    # ------------------------------------------------------------------ parcours
    def _targets(self, node_id: str, port: str) -> list[str]:
        return [d for p, d in self.out.get(node_id, []) if p == port]

    def chain(self, node_id: str, ctx, stop_at_join: bool = False):
        """Exécute à partir de `node_id`. Retourne l'identifiant du bloc « Joindre » atteint (si stop_at_join), sinon None."""
        node = self.nodes[node_id]
        if stop_at_join and node["type"] == "join":
            return node_id
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise WorkflowError("Trop d'étapes : boucle infinie probable.")
        if ctx.cancel.is_set():
            raise blocks.BlockError("Annulé.")
        b = blocks.REGISTRY[node["type"]]
        start = self.clock()
        self.on_event("node", {"id": node_id, "status": "running"})
        try:
            res = self._call(node, ctx)
            status, err = "ok", ""
        except (blocks.BlockError, ex.ExprError) as exc:
            err = str(exc)
            opts = node.get("options", {})
            res = None
            if "error" in b.ports and self._targets(node_id, "error"):
                res, status = {"out": {"error": err}, "port": "error"}, "error-handled"
            elif opts.get("continue_on_error"):
                res, status = {"out": {"error": err}, "port": "out"}, "error-ignored"
            else:
                self._record(node, "failed", start, 1, err)
                self.on_event("node", {"id": node_id, "status": "failed", "error": err})
                raise
        with ctx.lock:
            ctx.outputs[node_id] = res.get("out", {})
            self._alias(node)
        self._record(node, status, start, res.get("attempts", 1), err)
        self.on_event("node", {"id": node_id, "status": status})
        port = res.get("port", "out")
        if "loop" in res:
            for i, item in enumerate(res["loop"]):
                child = copy.copy(ctx)
                child.item, child.index = item, i
                for t in self._targets(node_id, "body"):
                    self.chain(t, child)
            return self._follow(node_id, "done", ctx, stop_at_join)
        if "while" in res:
            n = 0
            while n < res["max"] and bool(ctx.eval(res["while"])):
                child = copy.copy(ctx)
                child.index = n
                for t in self._targets(node_id, "body"):
                    self.chain(t, child)
                n += 1
            return self._follow(node_id, "done", ctx, stop_at_join)
        if res.get("fork"):
            return self._fork(node_id, ctx, res["workers"], stop_at_join)
        return self._follow(node_id, port, ctx, stop_at_join)

    def _follow(self, node_id, port, ctx, stop_at_join):
        joined = None
        for t in self._targets(node_id, port):
            j = self.chain(t, ctx, stop_at_join)
            joined = joined or j
        return joined

    def _fork(self, node_id, ctx, workers, stop_at_join):
        targets = self._targets(node_id, "out")
        joins: list[str | None] = []
        errors: list[BaseException] = []

        def branch(t):
            try:
                joins.append(self.chain(t, copy.copy(ctx), True))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                ctx.cancel.set()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(branch, targets))
        if errors:
            raise errors[0]
        reached = {j for j in joins if j}
        if len(reached) > 1:
            raise WorkflowError("Les branches parallèles aboutissent à des blocs « Joindre » différents.")
        if not reached:
            return None
        join = next(iter(reached))
        return self._after_join(join, ctx, stop_at_join)

    def _after_join(self, join_id, ctx, stop_at_join):
        node = self.nodes[join_id]
        start = self.clock()
        ctx.outputs[join_id] = {}
        self._record(node, "ok", start, 1, "")
        return self._follow(join_id, "out", ctx, stop_at_join)

    def _record(self, node, status, start, attempts, err) -> None:
        with self.lock:
            self.results.append({"id": node["id"], "type": node["type"], "status": status, "seconds": round(self.clock() - start, 3), "attempts": attempts, "error": err})

    def execute(self) -> dict:
        started = self.clock()
        rec = {"workflow": self.wf.get("name", ""), "started": started, "dry_run": self.dry, "ok": True, "cancelled": False, "error": ""}
        problems = validate(self.wf)
        if problems["errors"]:
            rec.update(ok=False, error="Workflow invalide : " + " ; ".join(problems["errors"]))
        else:
            start = next(n["id"] for n in self.wf["nodes"] if n["type"] == "start")
            try:
                self.chain(start, self.ctx)
            except (blocks.BlockError, ex.ExprError, WorkflowError) as exc:
                rec["ok"] = False
                rec["cancelled"] = self.ctx.cancel.is_set() and str(exc) == "Annulé."
                rec["error"] = str(exc)
        rec.update(finished=self.clock(), nodes=self.results, log="\n".join(self.lines))
        self.on_event("done", rec)
        return rec


def run_workflow(wf: dict, project: str = "", trigger: dict | None = None, variables: dict | None = None, dry_run: bool = False, cancel=None, runner=None,
                 http=None, notify=None, on_event=None, **kw) -> dict:
    ctx = blocks.Ctx(project, variables, trigger, cancel, None, runner, http, notify)
    return Run(wf, ctx, dry_run, on_event, **kw).execute()
