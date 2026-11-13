"""API Studio : client HTTP réel contre le serveur mock local, auth/PKCE, chaînage, tests, scripts isolés, WebSocket, imports."""

import importlib
import json
import shutil
import sys
import types
from http.cookiejar import CookieJar
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent / "marketplace" / "plugins" / "api-studio"


@pytest.fixture(scope="module")
def pk():
    pkg = types.ModuleType("api_studio")
    pkg.__path__ = [str(PLUGIN)]
    sys.modules["api_studio"] = pkg
    yield
    for n in [n for n in sys.modules if n == "api_studio" or n.startswith("api_studio.")]:
        del sys.modules[n]


def mod(n):
    return importlib.import_module("api_studio." + n)


@pytest.fixture
def server(pk):
    m = mod("core.mock")
    s = m.MockServer([
        {"method": "GET", "path": "/users/{id}", "body": '{"id": "{{id}}", "name": "Ada"}'},
        {"method": "POST", "path": "/echo", "status": 201, "body": "{{request_body}}", "headers": {"X-Test": "1"}},
        {"method": "GET", "path": "/login", "headers": {"Set-Cookie": "sid=abc123; Path=/"}, "body": "ok"},
        {"method": "GET", "path": "/me", "body": "{{method}}"},
        {"method": "GET", "path": "/old", "status": 302, "headers": {"Location": "/users/7"}},
        {"method": "GET", "path": "/slow", "delay_ms": 600, "body": "z"},
    ]).start()
    yield s
    s.stop()


def req(**kw):
    return mod("core.model").Request(**kw)


def go(r, server, scopes=None, **kw):
    c = mod("core.client")
    prep = c.prepare(r, {"base": server.url}, *(scopes or []))
    return c.send(prep, **kw), prep


def test_variables(pk):
    v = mod("core.variables")
    out, missing = v.substitute("{{a}}/{{ b }}/{{zz}}/{{$uuid}}", {"a": "1"}, {"b": "2", "a": "x"})
    assert out.startswith("1/2/{{zz}}/") and missing == ["zz"] and len(out.split("/")[-1]) == 36


def test_get_with_params_headers_path_var(pk, server):
    r, prep = go(req(url="{{base}}/users/{{id}}", params=[{"key": "q", "value": "a b", "enabled": True}, {"key": "off", "value": "1", "enabled": False}],
                     headers=[{"key": "X-A", "value": "{{id}}", "enabled": True}]), server, [{"id": "42"}])
    assert r.status == 200 and r.json() == {"id": "42", "name": "Ada"} and r.ok
    assert "q=a+b" in prep["url"] and "off" not in prep["url"] and ("X-A", "42") in prep["headers"]
    assert server.hits[-1]["query"] == "q=a+b"


@pytest.mark.parametrize("btype,body,expect", [("json", '{"a": 1}', '{"a": 1}'), ("text", "bonjour", "bonjour"), ("xml", "<a/>", "<a/>")])
def test_body_types(pk, server, btype, body, expect):
    r, _ = go(req(method="POST", url="{{base}}/echo", body_type=btype, body=body), server)
    assert r.status == 201 and r.text == expect and r.header("x-test") == "1"
    assert server.hits[-1]["method"] == "POST"


def test_form_and_multipart(pk, server, tmp_path):
    r, _ = go(req(method="POST", url="{{base}}/echo", body_type="form", body_fields=[{"key": "a", "value": "1 2"}, {"key": "b", "value": "é"}]), server)
    assert r.text == "a=1+2&b=%C3%A9"
    f = tmp_path / "f.txt"
    f.write_text("CONTENU")
    r, _ = go(req(method="POST", url="{{base}}/echo", body_type="multipart", body_fields=[{"key": "n", "value": "v"}, {"key": "file", "file": str(f)}]), server)
    assert 'name="n"' in r.text and 'filename="f.txt"' in r.text and "CONTENU" in r.text


def test_methods_all(pk, server):
    for m in ("PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"):
        r, _ = go(req(method=m, url="{{base}}/nowhere"), server)
        assert r.status == 404 and not r.error


def test_redirect_cookies_timeout_errors(pk, server):
    r, _ = go(req(url="{{base}}/old"), server)
    assert r.status == 200 and r.redirects and r.json()["id"] == "7"
    r, _ = go(req(url="{{base}}/old"), server, follow=False)
    assert r.status == 302
    jar = CookieJar()
    go(req(url="{{base}}/login"), server, jar=jar)
    assert any(c.name == "sid" for c in jar)
    r, _ = go(req(url="{{base}}/slow"), server, timeout=0.2)
    assert r.error and not r.ok
    bad, _ = go(req(url="ftp://x"), server)
    assert bad.error
    refused, _ = go(req(url="http://127.0.0.1:1/"), server, timeout=2)
    assert refused.error


def test_auth_variants_and_pkce(pk):
    a = mod("core.auth")
    h, q = [], []
    a.apply({"type": "basic", "user": "u", "password": "p"}, h, q)
    a.apply({"type": "bearer", "token": "T"}, h, q)
    a.apply({"type": "apikey", "name": "k", "value": "v", "in": "query"}, h, q)
    a.apply({"type": "apikey", "name": "X-K", "value": "w"}, h, q)
    assert ("Authorization", "Basic dTpw") in h and ("Authorization", "Bearer T") in h and q == [("k", "v")] and ("X-K", "w") in h
    # vecteur de test de la RFC 7636, annexe B
    assert a.pkce_pair("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")[1] == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    v, c = a.pkce_pair()
    assert 43 <= len(v) <= 128 and "=" not in c
    url = a.authorization_url("https://idp/auth", "cid", "http://127.0.0.1:9/cb", "read", c, "st")
    assert "code_challenge_method=S256" in url and "state=st" in url
    assert a.parse_redirect("/cb?code=XYZ&state=st", "st") == "XYZ"
    with pytest.raises(ValueError):
        a.parse_redirect("/cb?code=XYZ&state=autre", "st")
    with pytest.raises(ValueError):
        a.parse_redirect("/cb?error=access_denied&state=st", "st")
    t = a.token_request("authorization_code", "https://idp/token", "cid", code="C", code_verifier=v, redirect_uri="http://x")
    assert "code_verifier=" + v in t["body"] and t["method"] == "POST"
    assert a.parse_token_response('{"access_token":"A","expires_in":3600}')["access_token"] == "A"
    with pytest.raises(ValueError):
        a.parse_token_response('{"error":"invalid_grant"}')


def test_oauth_token_exchange_against_mock(pk):
    m, c, a = mod("core.mock"), mod("core.client"), mod("core.auth")
    s = m.MockServer([{"method": "POST", "path": "/token", "body": '{"access_token":"tok-{{request_body}}"}'}]).start()
    try:
        tr = a.token_request("client_credentials", s.url + "/token", "cid", "sec", scope="x")
        resp = c.send({"method": "POST", "url": tr["url"], "headers": tr["headers"], "body": tr["body"].encode()})
        assert a.parse_token_response(resp.text)["access_token"].startswith("tok-")
        assert any(k == "Authorization" and v.startswith("Basic ") for k, v in tr["headers"])
    finally:
        s.stop()


def test_extract_and_tests(pk, server):
    e, c = mod("core.extract"), mod("core.client")
    r, _ = go(req(url="{{base}}/users/9"), server)
    assert e.json_path({"a": [{"b": 5}]}, "$.a[0].b") == 5 and e.json_path({"k-1": {"x y": 2}}, "$['k-1']['x y']") == 2
    with pytest.raises(KeyError):
        e.json_path({}, "$.zz")
    got, errs = e.run_extract(r, [{"var": "uid", "source": "json", "expr": "$.id"}, {"var": "ct", "source": "header", "expr": "content-type"},
                                  {"var": "n", "source": "regex", "expr": r'"name": "(\w+)"'}, {"var": "bad", "source": "json", "expr": "$.nope"}])
    assert got == {"uid": "9", "ct": "application/json", "n": "Ada"} and len(errs) == 1
    res = e.run_tests(r, [{"kind": "status", "op": "==", "value": "200"}, {"kind": "json", "expr": "$.name", "op": "==", "value": "Ada"},
                          {"kind": "header", "expr": "content-type", "op": "contains", "value": "json"}, {"kind": "time", "op": "<", "value": "5000"},
                          {"kind": "status", "op": "==", "value": "500"}, {"kind": "json", "expr": "$.absent", "op": "exists"},
                          {"kind": "body", "op": "matches", "value": "Ada"}])
    assert [t["ok"] for t in res] == [True, True, True, True, False, False, True]
    assert c.Response(status=200).ok


def test_chaining_collection_run(pk, server):
    r, m = mod("services.runner"), mod("core.model")
    col = {"name": "c", "variables": {"base": server.url}, "requests": [
        m.Request(name="un", url="{{base}}/users/5", extract=[{"var": "uid", "source": "json", "expr": "$.id"}],
                  tests=[{"kind": "status", "op": "==", "value": "200"}]).to_dict(),
        m.Request(name="deux", url="{{base}}/users/{{uid}}", tests=[{"kind": "json", "expr": "$.id", "op": "==", "value": "5"}]).to_dict(),
        m.Request(name="rate", url="{{base}}/users/{{absente}}").to_dict()]}
    out = r.run_collection(col, {})
    assert [o["ok"] for o in out] == [True, True, False] and any("absente" in e for e in out[2]["errors"])
    assert len(r.run_collection(col, {}, stop_on_failure=True)) == 3


def test_scripts_python_isolated(pk, server):
    s, r, m = mod("core.scripts"), mod("services.runner"), mod("core.model")
    out = s.run_script("python", "vars['x'] = 1 + 1\nlog('salut')\ntest('ok', True)", {"a": "b"}, {"url": "u", "method": "GET", "body": "", "headers": []})
    assert out["vars"]["x"] == "2" and out["logs"] == ["salut"] and out["tests"][0]["ok"] and out["error"] == ""
    err = s.run_script("python", "raise ValueError('boum')", {}, {"url": "", "method": "GET", "body": "", "headers": []})
    assert "boum" in err["error"]
    with pytest.raises(s.ScriptError):
        s.run_script("python", "while True: pass", {}, {}, timeout=1.0)
    leak = s.run_script("python", "import os\nvars['k'] = os.environ.get('HOME', 'absent') + str(os.getcwd().startswith('/tmp'))",
                        {}, {"url": "", "method": "GET", "body": "", "headers": []})
    assert leak["vars"]["k"].startswith("absent")
    rq = m.Request(url="{{base}}/users/{{n}}", pre_script={"lang": "python", "code": "vars['n'] = '3'"},
                   post_script={"lang": "python", "code": "vars['nom'] = response.json()['name']\ntest('statut', response.status == 200)"})
    res = r.run_request(rq, [{"base": server.url}], {})
    assert res["variables"]["nom"] == "Ada" and res["tests"][0]["ok"] and not res["errors"]


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js absent")
def test_scripts_javascript(pk):
    s = mod("core.scripts")
    out = s.run_script("javascript", "vars.y = 'z' + 1; log('js'); test('t', 1 === 1)", {}, {"url": "", "method": "GET", "body": "", "headers": []})
    assert out["vars"]["y"] == "z1" and out["logs"] == ["js"] and out["tests"][0]["ok"]
    assert "boom" in s.run_script("javascript", "throw new Error('boom')", {}, {})["error"]


def test_javascript_missing_is_reported(pk, monkeypatch):
    s = mod("core.scripts")
    monkeypatch.setattr(s.shutil, "which", lambda _n: None)
    with pytest.raises(s.ScriptError, match="Node"):
        s.run_script("javascript", "1", {}, {})
    assert not s.available("javascript") and s.available("python")


def test_websocket_roundtrip_and_protocol(pk, server):
    w = mod("core.websocket")
    c = w.WebSocketClient(f"ws://127.0.0.1:{server.port}/ws")
    c.connect()
    c.send_text("héllo")
    assert c.recv() == ("text", "héllo")
    big = "x" * 70000                      # trame à longueur 64 bits
    c.send_text(big)
    assert c.recv() == ("text", big)
    c.send_binary(b"\x00\x01")
    assert c.recv() == ("binary", b"\x00\x01")
    c.ping(b"p")
    assert c.recv() == ("pong", b"p")
    c.close()
    assert w.accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="      # exemple de la RFC 6455
    with pytest.raises(w.WebSocketError):
        w.WebSocketClient("http://x").connect()
    with pytest.raises(w.WebSocketError):
        w.WebSocketClient(f"ws://127.0.0.1:{server.port}/pas-un-ws").connect()


def test_websocket_frame_codec(pk):
    w = mod("core.websocket")
    import socket
    a, b = socket.socketpair()
    a.sendall(w.encode_frame(w.OP_TEXT, b"abc", mask=True, fin=False) + w.encode_frame(w.OP_CONT, b"def", mask=True))
    a.sendall(w.encode_frame(w.OP_PING, b"", mask=False))
    cl = w.WebSocketClient("ws://x")
    cl.sock = b
    assert cl.recv(1) == ("text", "abcdef")
    a.sendall(w.encode_frame(w.OP_CLOSE, b"\x03\xe8bye", mask=False))
    assert cl.recv(1) == ("close", (1000, "bye"))
    a.close()
    b.close()


def test_mock_unknown_route_and_hits(pk, server):
    r, _ = go(req(url="{{base}}/rien"), server)
    assert r.status == 404 and server.hits[-1]["path"] == "/rien"
    assert server.url.startswith("http://127.0.0.1:")
    assert mod("core.mock").compile_path("/a/{id}/b").match("/a/7/b").group("id") == "7"


SPEC = {"openapi": "3.0.0", "info": {"title": "Pets", "description": "d"}, "servers": [{"url": "https://api.pets.io/v1/"}], "paths": {
    "/pets/{petId}": {"parameters": [{"name": "petId", "in": "path", "required": True, "schema": {"type": "string"}}],
                      "get": {"summary": "Lire", "parameters": [{"name": "verbose", "in": "query", "schema": {"default": "1"}}],
                              "responses": {"200": {"description": "ok"}}}},
    "/pets": {"post": {"operationId": "creer", "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}}},
                       "responses": {"201": {}}}}},
    "components": {"schemas": {"Pet": {"type": "object", "properties": {"name": {"type": "string", "example": "Rex"}, "age": {"type": "integer"}}}}}}


def test_openapi_import(pk):
    o = mod("core.openapi")
    col = o.import_spec(SPEC)
    names = {r["name"]: r for r in col.requests}
    assert col.variables["baseUrl"] == "https://api.pets.io/v1" and "petId" in col.variables
    assert names["Lire"]["url"] == "{{baseUrl}}/pets/{{petId}}" and names["Lire"]["params"][0]["key"] == "verbose"
    assert json.loads(names["creer"]["body"]) == {"name": "Rex", "age": 0} and names["creer"]["tests"][0]["value"] == "201"
    for bad in ({}, {"openapi": "3", "paths": {}}):
        with pytest.raises(o.ImportError_):
            o.import_spec(bad)
    with pytest.raises(o.ImportError_):
        o.load_text("{pas json")
    assert o.load_text(json.dumps(SPEC))["info"]["title"] == "Pets"


def test_postman_roundtrip(pk):
    p, m = mod("core.postman"), mod("core.model")
    col = m.Collection("C", [m.Request(name="a", method="POST", url="{{u}}/x", headers=[{"key": "H", "value": "v", "enabled": True}],
                                       params=[{"key": "q", "value": "1", "enabled": True}], body_type="json", body='{"k":1}',
                                       auth={"type": "bearer", "token": "T"}).to_dict(),
                       m.Request(name="b", body_type="form", body_fields=[{"key": "f", "value": "1"}], url="u").to_dict()], {"u": "http://h"})
    exported = p.export_postman(col)
    assert exported["info"]["schema"].endswith("v2.1.0/collection.json")
    back = p.import_postman(json.loads(p.dumps(exported)))
    r0 = m.Request.from_dict(back.requests[0])
    assert (r0.method, r0.url, r0.body_type, r0.auth["token"], r0.params[0]["key"]) == ("POST", "{{u}}/x", "json", "T", "q") and back.variables == {"u": "http://h"}
    nested = {"info": {"name": "N"}, "item": [{"name": "dossier", "item": [{"name": "r", "request": "http://z"}]}]}
    assert p.import_postman(nested).requests[0]["name"] == "dossier / r"
    with pytest.raises(ValueError):
        p.import_postman({})


def test_store(pk, tmp_path):
    s = mod("storage.store").Store(tmp_path)
    s.save_collection("/p1", {"name": "b", "requests": []})
    s.save_collection("/p1", {"name": "a", "requests": []})
    s.save_collection("/p1", {"name": "b", "requests": [1]})
    assert [c["name"] for c in s.collections("/p1")] == ["a", "b"] and s.collections("/p2") == []
    s.delete_collection("/p1", "a")
    assert len(s.collections("/p1")) == 1
    for i in range(mod("storage.store").HISTORY_MAX + 3):
        s.add_history("/p1", {"i": i})
    assert len(s.history("/p1")) == mod("storage.store").HISTORY_MAX and s.history("/p1")[0]["i"] == mod("storage.store").HISTORY_MAX + 2
    assert s.environments("/p1") == {"active": "", "items": {}}


def test_widget_flow(pk, server, tmp_path):
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    w = mod("ui.widget").ApiStudioWidget(mod("storage.store").Store(tmp_path / "s"))
    w.set_project(tmp_path)
    w.new_collection("API")
    w.new_request()
    w.url.setText(server.url + "/users/8")
    w.extract.setPlainText('[{"var":"uid","source":"json","expr":"$.id"}]')
    w.tests.setPlainText('[{"kind":"status","op":"==","value":"200"}]')
    w.send()
    assert "200" in w.status.text() and "tests OK" in w.status.text() and w.chain["uid"] == "8" and w.hist.rowCount() == 1
    assert '"name": "Ada"' in w.resp_body.toPlainText()
    w.tests.setPlainText("[pas json")
    with pytest.raises(ValueError):
        w.read_request()
    w.tests.setPlainText("")
    assert w.run_collection() is None
    out = tmp_path / "pm.json"
    assert w.export_file(str(out)) and "schema.getpostman.com" in out.read_text()
    assert w.import_file(str(out)) == "API (2)"
    spec = tmp_path / "o.json"
    spec.write_text(json.dumps(SPEC))
    assert w.import_file(str(spec)) == "Pets"
    w.import_file(str(tmp_path / "absent.json"))
    assert "Import impossible" in w.status.text()
    w.set_project(tmp_path)                       # rechargé depuis le disque
    assert len(w.cols) == 3
    w.mock_edit.setPlainText('[{"method":"GET","path":"/a","body":"ok"}]')
    w.mock_run()
    assert w.mock and "Actif" in w.mock_label.text()
    w.mock_halt()
    w.mock_edit.setPlainText("pas json")
    w.mock_run()
    assert w.mock is None
