"""Import OpenAPI 3.x / Swagger 2.0 (JSON ; YAML si PyYAML est disponible) → collection."""

from __future__ import annotations

import json

from .model import METHODS, Collection, Request


class ImportError_(Exception):  # noqa: N801
    pass


def load_text(text: str) -> dict:
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ImportError_(f"JSON invalide : {exc}") from exc
    try:
        import yaml
    except ImportError as exc:
        raise ImportError_("Ce fichier n'est pas du JSON et PyYAML n'est pas installé : convertissez la spécification en JSON.") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ImportError_(f"YAML invalide : {exc}") from exc


def deref(spec: dict, node, depth: int = 0):
    if isinstance(node, dict) and "$ref" in node and depth < 8:
        cur = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            cur = cur.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(cur, dict) else {}
        return deref(spec, cur, depth + 1)
    return node


def example(spec: dict, schema, depth: int = 0):
    schema = deref(spec, schema)
    if not isinstance(schema, dict) or depth > 5:
        return None
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if schema.get("enum"):
        return schema["enum"][0]
    t = schema.get("type") or ("object" if "properties" in schema else "string")
    if t == "object":
        return {k: example(spec, v, depth + 1) for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return [example(spec, schema.get("items", {}), depth + 1)]
    return {"integer": 0, "number": 0.0, "boolean": False}.get(t, "string")


def import_spec(spec: dict) -> Collection:
    if not isinstance(spec, dict) or not ("openapi" in spec or "swagger" in spec):
        raise ImportError_("Ce n'est pas une spécification OpenAPI/Swagger.")
    title = (spec.get("info") or {}).get("title", "API")
    if "servers" in spec and spec["servers"]:
        base = spec["servers"][0].get("url", "")
    else:
        base = (f"{(spec.get('schemes') or ['https'])[0]}://{spec['host']}{spec.get('basePath', '')}") if spec.get("host") else ""
    col = Collection(title, [], {"baseUrl": base.rstrip("/")}, (spec.get("info") or {}).get("description", ""))
    for path, item in (spec.get("paths") or {}).items():
        item = deref(spec, item)
        shared = item.get("parameters", [])
        for method in METHODS:
            op = item.get(method.lower())
            if not op:
                continue
            req = Request(name=op.get("summary") or op.get("operationId") or f"{method} {path}", method=method,
                          url="{{baseUrl}}" + path.replace("{", "{{").replace("}", "}}"))
            for p in [deref(spec, x) for x in [*shared, *op.get("parameters", [])]]:
                if p.get("in") == "query":
                    req.params.append({"key": p["name"], "value": str((p.get("schema") or {}).get("default", "")), "enabled": bool(p.get("required"))})
                elif p.get("in") == "header":
                    req.headers.append({"key": p["name"], "value": "", "enabled": bool(p.get("required"))})
            body = deref(spec, op.get("requestBody") or {})
            content = body.get("content", {}) if isinstance(body, dict) else {}
            if "application/json" in content:
                req.body_type = "json"
                req.body = json.dumps(example(spec, content["application/json"].get("schema", {})), indent=2, ensure_ascii=False)
            elif "multipart/form-data" in content:
                req.body_type = "multipart"
                props = (deref(spec, content["multipart/form-data"].get("schema", {})).get("properties") or {})
                req.body_fields = [{"key": k, "value": ""} for k in props]
            elif "application/x-www-form-urlencoded" in content:
                req.body_type = "form"
                props = (deref(spec, content["application/x-www-form-urlencoded"].get("schema", {})).get("properties") or {})
                req.body_fields = [{"key": k, "value": ""} for k in props]
            for param in [x for x in [*shared, *op.get("parameters", [])] if deref(spec, x).get("in") == "path"]:
                col.variables.setdefault(deref(spec, param)["name"], "")
            ok_codes = [c for c in (op.get("responses") or {}) if str(c).startswith("2")]
            if ok_codes:
                req.tests.append({"kind": "status", "expr": "", "op": "==", "value": str(ok_codes[0])})
            col.requests.append(req.to_dict())
    if not col.requests:
        raise ImportError_("Aucune opération trouvée dans « paths ».")
    return col
