"""Import / export Postman Collection v2.1 (sous-ensemble : requêtes, en-têtes, corps brut/formulaire, auth Basic/Bearer/API key, variables)."""

from __future__ import annotations

import json

from .model import Collection, Request

SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def _items(items: list, out: list, prefix: str = "") -> None:
    for it in items:
        if "item" in it:
            _items(it["item"], out, prefix + it.get("name", "") + " / ")
        elif "request" in it:
            out.append((prefix + it.get("name", "requête"), it["request"]))


def _auth(a: dict | None) -> dict:
    if not a:
        return {"type": "none"}
    t = a.get("type")
    vals = {x["key"]: x.get("value", "") for x in a.get(t, []) if isinstance(x, dict) and "key" in x}
    if t == "basic":
        return {"type": "basic", "user": vals.get("username", ""), "password": vals.get("password", "")}
    if t == "bearer":
        return {"type": "bearer", "token": vals.get("token", "")}
    if t == "apikey":
        return {"type": "apikey", "name": vals.get("key", "X-API-Key"), "value": vals.get("value", ""), "in": vals.get("in", "header")}
    return {"type": "none"}


def import_postman(data: dict) -> Collection:
    if "info" not in data or "item" not in data:
        raise ValueError("Ce n'est pas une collection Postman v2.x.")
    col = Collection(data["info"].get("name", "Postman"), [], {v["key"]: str(v.get("value", "")) for v in data.get("variable", []) if "key" in v},
                     data["info"].get("description", "") if isinstance(data["info"].get("description", ""), str) else "")
    flat: list = []
    _items(data["item"], flat)
    for name, r in flat:
        if isinstance(r, str):
            r = {"method": "GET", "url": r}
        url = r.get("url", "")
        raw = url if isinstance(url, str) else url.get("raw", "")
        req = Request(name=name, method=r.get("method", "GET").upper(), url=raw.split("?")[0],
                      headers=[{"key": h["key"], "value": h.get("value", ""), "enabled": not h.get("disabled", False)} for h in r.get("header", [])],
                      auth=_auth(r.get("auth")))
        if isinstance(url, dict):
            req.params = [{"key": q["key"], "value": q.get("value", "") or "", "enabled": not q.get("disabled", False)} for q in url.get("query", [])]
        body = r.get("body") or {}
        mode = body.get("mode")
        if mode == "raw":
            lang = ((body.get("options") or {}).get("raw") or {}).get("language", "text")
            req.body_type = lang if lang in ("json", "xml", "text") else "text"
            req.body = body.get("raw", "")
        elif mode in ("urlencoded", "formdata"):
            req.body_type = "form" if mode == "urlencoded" else "multipart"
            req.body_fields = [{"key": f["key"], "value": f.get("value", ""), **({"file": f["src"]} if f.get("type") == "file" and f.get("src") else {})}
                               for f in body.get(mode, []) if not f.get("disabled")]
        col.requests.append(req.to_dict())
    return col


def export_postman(col: Collection) -> dict:
    items = []
    for rd in col.requests:
        r = Request.from_dict(rd)
        body: dict = {}
        if r.body_type in ("json", "text", "xml"):
            body = {"mode": "raw", "raw": r.body, "options": {"raw": {"language": r.body_type}}}
        elif r.body_type == "form":
            body = {"mode": "urlencoded", "urlencoded": [{"key": f["key"], "value": f.get("value", "")} for f in r.body_fields]}
        elif r.body_type == "multipart":
            body = {"mode": "formdata", "formdata": [{"key": f["key"], "value": f.get("value", ""), "type": "text"} for f in r.body_fields]}
        a = r.auth
        auth = None
        if a.get("type") == "basic":
            auth = {"type": "basic", "basic": [{"key": "username", "value": a.get("user", "")}, {"key": "password", "value": a.get("password", "")}]}
        elif a.get("type") == "bearer":
            auth = {"type": "bearer", "bearer": [{"key": "token", "value": a.get("token", "")}]}
        elif a.get("type") == "apikey":
            auth = {"type": "apikey", "apikey": [{"key": "key", "value": a.get("name", "")}, {"key": "value", "value": a.get("value", "")},
                                                 {"key": "in", "value": a.get("in", "header")}]}
        req = {"method": r.method, "header": [{"key": h["key"], "value": h.get("value", ""), "disabled": not h.get("enabled", True)} for h in r.headers],
               "url": {"raw": r.url, "query": [{"key": q["key"], "value": q.get("value", ""), "disabled": not q.get("enabled", True)} for q in r.params]},
               **({"body": body} if body else {}), **({"auth": auth} if auth else {})}
        items.append({"name": r.name, "request": req})
    return {"info": {"name": col.name, "schema": SCHEMA, "description": col.description},
            "item": items, "variable": [{"key": k, "value": v} for k, v in col.variables.items()]}


def dumps(d: dict) -> str:
    return json.dumps(d, indent=2, ensure_ascii=False)
