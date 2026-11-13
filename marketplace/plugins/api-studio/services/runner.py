"""Exécution complète d'une requête : variables → script avant → envoi → script après → extraction → tests."""

from __future__ import annotations

from ..core import client, extract, scripts
from ..core.model import Request


def run_request(req: Request, scopes: list[dict], variables: dict, jar=None, verify_tls: bool = True,
                send=client.send, scripter=scripts.run_script) -> dict:
    """`variables` : variables modifiables (chaînage) — elles sont mises à jour sur place et prioritaires.
    Retourne {"response", "prepared", "tests", "logs", "errors", "variables"}."""
    errors: list[str] = []
    logs: list[str] = []
    tests: list[dict] = []
    # script avant : peut modifier vars et request
    if req.pre_script.get("code", "").strip():
        try:
            pre = scripter(req.pre_script.get("lang", "python"), req.pre_script["code"], {**{k: v for s in reversed(scopes) for k, v in s.items()}, **variables},
                           {"url": req.url, "method": req.method, "body": req.body, "headers": []})
            variables.update(pre["vars"])
            logs += [f"[avant] {x}" for x in pre["logs"]]
            if pre["error"]:
                errors.append("Script avant : " + pre["error"])
            req = Request.from_dict({**req.to_dict(), "url": pre["request"].get("url", req.url), "body": pre["request"].get("body", req.body),
                                     "headers": [*req.headers, *[{"key": k, "value": v, "enabled": True} for k, v in pre["request"].get("headers", [])]]})
        except scripts.ScriptError as exc:
            errors.append(f"Script avant : {exc}")
    prepared = client.prepare(req, variables, *scopes)
    if prepared["missing"]:
        errors.append("Variables non définies : " + ", ".join(prepared["missing"]))
    try:
        resp = send(prepared, req.timeout, req.follow_redirects, jar, verify_tls)
    except ValueError as exc:
        resp = client.Response(error=str(exc))
    if resp.error:
        errors.append(resp.error)
    if not resp.error or resp.status:
        got, ex_err = extract.run_extract(resp, req.extract)
        variables.update(got)
        errors += [f"Extraction : {e}" for e in ex_err]
        tests += extract.run_tests(resp, req.tests)
        if req.post_script.get("code", "").strip():
            try:
                post = scripter(req.post_script.get("lang", "python"), req.post_script["code"], {**{k: v for s in reversed(scopes) for k, v in s.items()}, **variables},
                                {"url": prepared["url"], "method": prepared["method"], "body": "", "headers": []},
                                {"status": resp.status, "headers": [list(h) for h in resp.headers], "text": resp.text, "seconds": resp.seconds})
                variables.update(post["vars"])
                logs += [f"[après] {x}" for x in post["logs"]]
                tests += post["tests"]
                if post["error"]:
                    errors.append("Script après : " + post["error"])
            except scripts.ScriptError as exc:
                errors.append(f"Script après : {exc}")
    return {"response": resp, "prepared": prepared, "tests": tests, "logs": logs, "errors": errors, "variables": variables}


def run_collection(col: dict, env_vars: dict, jar=None, stop_on_failure: bool = False, **kw) -> list[dict]:
    """Exécute toutes les requêtes dans l'ordre en partageant les variables extraites (chaînage)."""
    chain: dict = {}
    out = []
    for rd in col["requests"]:
        req = Request.from_dict(rd)
        res = run_request(req, [col.get("variables", {}), env_vars], chain, jar, **kw)
        failed = bool(res["errors"]) or not res["response"].ok or any(not t["ok"] for t in res["tests"])
        out.append({"name": req.name, "status": res["response"].status, "seconds": res["response"].seconds, "tests": res["tests"],
                    "errors": res["errors"], "ok": not failed})
        if failed and stop_on_failure:
            break
    return out
